"""Epiphyte — a Discord bot that renders a single plant in one channel.

Phase 3 (fairness & durability): each guild picks a watering channel with
``/epiphyte-channel``; every message there passively waters the plant, and
silence lets it decay over days. Repeated watering by the same person yields
diminishing returns, so one flooder cannot keep the plant alive while genuine
activity from several people can. All state is persisted in SQLite, so a restart
does not change the plant.

This module is the thin Discord adapter from the architecture: client, commands,
event and sync wiring. The interesting computation lives in the pure ``moisture``
and ``lsystem`` modules; ``render`` isolates the Pillow drawing and ``storage``
isolates the SQLite persistence.
"""

from __future__ import annotations

import asyncio
import io
import os
import time
from dataclasses import dataclass

import discord
from discord import app_commands

import lsystem
import moisture
import render
import storage
from moisture import Stage

#: Name of the required environment variable holding the bot token.
TOKEN_ENV = "EPIPHYTE_TOKEN"
#: Name of the optional environment variable holding the test guild id.
GUILD_ENV = "EPIPHYTE_GUILD_ID"

#: Nord-themed embed colour per growth stage (driest to lushest).
STAGE_COLORS: dict[Stage, int] = {
    Stage.WITHERED: 0x5E4A3B,  # rooted stem brown
    Stage.DRY: 0x8FBCBB,       # pale living stem
    Stage.HEALTHY: 0xA3BE8C,   # leaf green
    Stage.THRIVING: 0x88C0D0,  # bud accent
}

#: Human-readable label per growth stage.
STAGE_LABELS: dict[Stage, str] = {
    Stage.WITHERED: "Withered",
    Stage.DRY: "Dry",
    Stage.HEALTHY: "Healthy",
    Stage.THRIVING: "Thriving",
}

#: Attachment filename referenced by the embed's image.
PLANT_IMAGE_FILENAME = "plant.png"


@dataclass
class WateringWindow:
    """A person's diminishing-returns window.

    ``window_start`` is when the current window began; ``count`` is how many
    times the person has watered within it. Kept in memory only — losing it on a
    restart cannot help a flooder, since the persisted moisture keeps decaying.
    """

    window_start: float
    count: int


def render_plant_png(value: float) -> io.BytesIO:
    """Run the full pipeline for a moisture value and return a PNG buffer.

    Chains moisture -> stage -> depth -> expand -> interpret -> render. This is
    synchronous (the Pillow drawing), so callers should run it in a thread to
    keep the event loop responsive.
    """
    depth = lsystem.depth_for_stage(moisture.stage(value))
    commands = lsystem.expand(lsystem.PLANT_AXIOM, lsystem.PLANT_RULES, depth)
    segments = lsystem.interpret(commands, lsystem.PLANT_ANGLE, lsystem.PLANT_STEP)
    return render.render(segments)


def build_plant_embed(value: float, plant_stage: Stage) -> discord.Embed:
    """Build the Nord-themed embed that frames the plant image and its values."""
    embed = discord.Embed(title="🌱 The plant", color=STAGE_COLORS[plant_stage])
    embed.add_field(name="Moisture", value=f"{value:.0%}")
    embed.add_field(name="Stage", value=STAGE_LABELS[plant_stage])
    embed.set_image(url=f"attachment://{PLANT_IMAGE_FILENAME}")
    return embed


class EpiphyteClient(discord.Client):
    """Discord client with its own command tree (slash commands only).

    Uses the default intents exclusively: the bot only needs to know *that* a
    message arrived, never *what* it said. Per-guild plant state is loaded from
    SQLite on startup and written back on every change; the per-person watering
    windows are kept in memory.
    """

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self._storage: storage.Storage | None = None
        self._states: dict[int, storage.GuildState] = {}
        self._windows: dict[tuple[int, int], WateringWindow] = {}

    async def setup_hook(self) -> None:
        """Open the database, load the guild states, then sync the commands.

        If ``EPIPHYTE_GUILD_ID`` is set, the commands are copied into that test
        guild and synced there (visible immediately); otherwise a global sync is
        performed, whose delivery by Discord can take up to an hour.
        """
        self._storage = storage.Storage()
        self._states = self._storage.load_all()

        guild_id = os.getenv(GUILD_ENV)
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    def _store(self, state: storage.GuildState) -> None:
        """Update the in-memory cache and persist the state immediately."""
        self._states[state.guild_id] = state
        if self._storage is not None:
            self._storage.save(state)

    def channel_id(self, guild_id: int) -> int | None:
        """Return the guild's configured watering channel, or ``None`` if unset."""
        state = self._states.get(guild_id)
        return state.channel_id if state is not None else None

    def current_moisture(self, guild_id: int, now: float) -> float:
        """Return a guild's current moisture without mutating its state.

        Decays the stored moisture from its ``last_update`` up to ``now``. A
        guild that has never been watered is fully withered at ``0.0``.
        """
        state = self._states.get(guild_id)
        if state is None:
            return moisture.MIN_MOISTURE
        return moisture.decay(state.moisture, now - state.last_update)

    def set_channel(self, guild_id: int, channel_id: int, now: float) -> None:
        """Set the guild's watering channel, preserving the current moisture."""
        current = self.current_moisture(guild_id, now)
        self._store(storage.GuildState(guild_id, current, now, channel_id))

    def water_plant(self, guild_id: int, user_id: int, now: float) -> None:
        """Water a guild's plant with diminishing returns for the author.

        The author's repeated waterings within their window add progressively
        less (see :func:`moisture.next_watering`), so a single person cannot farm
        the plant. Decays to ``now``, adds the discounted amount, restamps and
        persists.
        """
        window = self._windows.get((guild_id, user_id))
        start = window.window_start if window is not None else None
        count = window.count if window is not None else 0
        amount, new_start, new_count = moisture.next_watering(start, count, now)
        self._windows[(guild_id, user_id)] = WateringWindow(new_start, new_count)

        current = self.current_moisture(guild_id, now)
        self._store(
            storage.GuildState(
                guild_id=guild_id,
                moisture=moisture.water(current, amount),
                last_update=now,
                channel_id=self.channel_id(guild_id),
            )
        )

    async def on_message(self, message: discord.Message) -> None:
        """Water the plant when a message arrives in the guild's watering channel.

        Ignores the bot's own messages, direct messages, and messages outside the
        configured channel. Only the fact that a message arrived matters — never
        its content.
        """
        if message.author == self.user:
            return
        if message.guild is None:
            return
        watering_channel = self.channel_id(message.guild.id)
        if watering_channel is None or message.channel.id != watering_channel:
            return
        self.water_plant(message.guild.id, message.author.id, time.time())


client = EpiphyteClient()


@client.tree.command(name="plant", description="Show the current state of the plant.")
async def plant(interaction: discord.Interaction) -> None:
    """Render the current plant as an image and send it in a Nord-themed embed."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Epiphyte only grows on servers, not in direct messages.",
            ephemeral=True,
        )
        return
    if client.channel_id(interaction.guild_id) is None:
        await interaction.response.send_message(
            "No watering channel set yet. Use `/epiphyte-channel` to choose which "
            "channel waters the plant.",
            ephemeral=True,
        )
        return
    value = client.current_moisture(interaction.guild_id, time.time())
    png = await asyncio.to_thread(render_plant_png, value)
    file = discord.File(png, filename=PLANT_IMAGE_FILENAME)
    embed = build_plant_embed(value, moisture.stage(value))
    await interaction.response.send_message(embed=embed, file=file)


@client.tree.command(
    name="epiphyte-channel",
    description="Choose the channel whose messages water the plant.",
)
@app_commands.describe(channel="The text channel whose messages water the plant.")
async def epiphyte_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    """Set the guild's watering channel."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Epiphyte only grows on servers, not in direct messages.",
            ephemeral=True,
        )
        return
    client.set_channel(interaction.guild_id, channel.id, time.time())
    await interaction.response.send_message(
        f"🌱 The plant now drinks from {channel.mention}. Every message there waters it."
    )


def main() -> None:
    """Read the token from the environment and start the bot.

    The token is read here, not at import time, so the module can be imported
    without a token (smoke test).
    """
    token = os.getenv(TOKEN_ENV)
    if not token:
        raise SystemExit(
            f"Environment variable {TOKEN_ENV} is not set. "
            "The bot cannot start without a token."
        )
    client.run(token)


if __name__ == "__main__":
    main()
