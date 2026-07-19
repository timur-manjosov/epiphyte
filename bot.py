"""Epiphyte — a Discord bot that grows a single plant in one channel.

Phase 6 (its own life): the plant now lives in the channel instead of being
summoned on demand. A recurring metabolic tick — the plant's heartbeat — grows
every plant one step and re-renders a single living message the bot keeps updated
in place, so the plant visibly grows and withers over days without any command.

Each guild binds a channel with ``/epiphyte-channel``; every message there
passively waters the plant, and silence lets its moisture decay over days. The
tick grows one step per beat, gated by the current moisture, so an active channel
drives the plant forward and a quiet one lets it stagnate. ``/plant`` no longer
grows anything: it shows an immediate personal snapshot and brings the living
message back into view if it has scrolled away.

Growth is gated by moisture, and moisture is subject to the per-person
diminishing returns from Phase 3, so spam cannot farm a big tree.

This module is the thin Discord adapter: client, commands, events, the scheduler
wiring and the living-message I/O. The interesting computation lives in the pure
``moisture`` and ``structure`` modules; ``render`` isolates the Pillow drawing and
``storage`` the SQLite persistence.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import random
import time
from dataclasses import dataclass, replace

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord import app_commands

import moisture
import render
import storage
import structure
from moisture import Stage

_log = logging.getLogger("epiphyte")

#: Name of the required environment variable holding the bot token.
TOKEN_ENV = "EPIPHYTE_TOKEN"
#: Name of the optional environment variable holding the test guild id.
GUILD_ENV = "EPIPHYTE_GUILD_ID"

#: Real time between metabolic ticks: the plant's heartbeat. Each tick grows every
#: plant exactly one step, so this constant *is* the real duration of one growth
#: step — a big tree is the reward of weeks of ticks, not one busy evening. It sits
#: far above Discord's message-edit rate limit, so re-rendering once per tick never
#: edits too often. Adjustable during Phase 8 calibration.
TICK_INTERVAL_SECONDS = 60 * 60  # 1 hour

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


def build_plant_embed(value: float, plant_stage: Stage, step_count: int) -> discord.Embed:
    """Build the Nord-themed embed that frames the plant image and its values."""
    embed = discord.Embed(title="🌱 The plant", color=STAGE_COLORS[plant_stage])
    embed.add_field(name="Moisture", value=f"{value:.0%}")
    embed.add_field(name="Stage", value=STAGE_LABELS[plant_stage])
    embed.add_field(name="Age", value=f"{step_count} steps")
    embed.set_image(url=f"attachment://{PLANT_IMAGE_FILENAME}")
    return embed


class EpiphyteClient(discord.Client):
    """Discord client with its own command tree (slash commands only).

    Uses the default intents exclusively: the bot only needs to know *that* a
    message arrived, never *what* it said. Per-guild plant state is loaded from
    SQLite on startup and written back on every change; the per-person watering
    windows are kept in memory. An APScheduler job drives the metabolic tick.
    """

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self._storage: storage.Storage | None = None
        self._states: dict[int, storage.GuildState] = {}
        self._windows: dict[tuple[int, int], WateringWindow] = {}
        self._scheduler: AsyncIOScheduler | None = None

    async def setup_hook(self) -> None:
        """Open the database, load states, sync commands, and start the tick.

        If ``EPIPHYTE_GUILD_ID`` is set, the commands are copied into that test
        guild and synced there (visible immediately); otherwise a global sync is
        performed, whose delivery by Discord can take up to an hour. The metabolic
        tick's first beat is one interval away, by when the bot is ready.
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

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.metabolic_tick,
            "interval",
            seconds=TICK_INTERVAL_SECONDS,
            coalesce=True,
            max_instances=1,
            id="metabolic_tick",
        )
        self._scheduler.start()
        _log.info("Metabolic tick scheduled every %s seconds.", TICK_INTERVAL_SECONDS)

    async def close(self) -> None:
        """Shut down cleanly: stop the scheduler and close the database."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._storage is not None:
            self._storage.close()
        await super().close()

    # --- state ---------------------------------------------------------------

    def _store(self, state: storage.GuildState) -> None:
        """Update the in-memory cache and persist the state immediately."""
        self._states[state.guild_id] = state
        if self._storage is not None:
            self._storage.save(state)

    def state(self, guild_id: int) -> storage.GuildState | None:
        """Return a guild's plant state, or ``None`` if it has no plant yet."""
        return self._states.get(guild_id)

    def set_channel(self, guild_id: int, channel_id: int, now: float) -> None:
        """Bind the guild's plant to a channel.

        On a guild's first contact this germinates a fresh plant from a new random
        seed — the seed is what makes each server's plant an individual. Rebinding
        to a *different* channel clears the tracked living message so a fresh one
        is posted there; rebinding to the same channel is a no-op.
        """
        state = self._states.get(guild_id)
        if state is None:
            seed = random.getrandbits(63)
            self._store(
                storage.GuildState(
                    guild_id=guild_id,
                    structure=structure.germinate(seed),
                    moisture=moisture.MIN_MOISTURE,
                    last_update=now,
                    channel_id=channel_id,
                    message_id=None,
                )
            )
        elif state.channel_id != channel_id:
            self._store(replace(state, channel_id=channel_id, message_id=None))

    def water_plant(self, guild_id: int, user_id: int, now: float) -> None:
        """Water a guild's plant with diminishing returns for the author.

        The author's repeated waterings within their window add progressively
        less (see :func:`moisture.next_watering`), so a single person cannot farm
        the plant. Decays to ``now``, adds the discounted amount, restamps and
        persists. Growth is not advanced here — the metabolic tick grows the plant.
        """
        state = self._states.get(guild_id)
        if state is None:
            return  # no plant yet; watering only happens once a channel is set

        window = self._windows.get((guild_id, user_id))
        start = window.window_start if window is not None else None
        count = window.count if window is not None else 0
        amount, new_start, new_count = moisture.next_watering(start, count, now)
        self._windows[(guild_id, user_id)] = WateringWindow(new_start, new_count)

        current = moisture.decay(state.moisture, now - state.last_update)
        self._store(replace(state, moisture=moisture.water(current, amount), last_update=now))

    def grow_one_step(self, guild_id: int, now: float) -> None:
        """Advance one guild's plant by a single growth step (the tick's core).

        Decays moisture to ``now``, grows exactly one step gated by that moisture —
        high moisture grows briskly, a dry plant barely at all — and persists. The
        growth itself is the pure logic in :mod:`structure`; this only reads the
        clock and stores the result.
        """
        state = self._states[guild_id]
        current = moisture.decay(state.moisture, now - state.last_update)
        genome = structure.genome_from_seed(state.structure.seed)
        grown = structure.grow(state.structure, genome, current, 1)
        self._store(replace(state, structure=grown, moisture=current, last_update=now))

    async def on_message(self, message: discord.Message) -> None:
        """Water the plant when a message arrives in the guild's bound channel.

        Ignores the bot's own messages, direct messages, and messages outside the
        bound channel. Only the fact that a message arrived matters — never its
        content.
        """
        if message.author == self.user:
            return
        if message.guild is None:
            return
        state = self.state(message.guild.id)
        if state is None or state.channel_id is None or message.channel.id != state.channel_id:
            return
        self.water_plant(message.guild.id, message.author.id, time.time())

    # --- the metabolic tick --------------------------------------------------

    async def metabolic_tick(self) -> None:
        """The plant's heartbeat: grow every plant one step and refresh its message.

        Runs at a fixed real interval while the bot is live. Each guild is handled
        independently, so one unreachable channel never stops the others.
        """
        now = time.time()
        for guild_id, state in list(self._states.items()):
            if state.channel_id is None:
                continue
            try:
                self.grow_one_step(guild_id, now)
                await self.refresh_channel_message(guild_id)
            except Exception:  # noqa: BLE001 — one guild must not break the rest
                _log.exception("Metabolic tick failed for guild %s.", guild_id)

    # --- the living channel message (I/O) ------------------------------------

    async def _text_channel(self, channel_id: int) -> discord.TextChannel | None:
        """Resolve a channel id to a text channel, or ``None`` if unavailable."""
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _render_bytes(self, plant: structure.Structure, moisture_value: float) -> bytes:
        """Render a structure to PNG bytes off the event loop (Pillow is sync).

        ``moisture_value`` is the vitality that modulates the plant's look; the
        genome is recomputed from the seed so the render matches this individual.
        """
        genome = structure.genome_from_seed(plant.seed)
        buffer = await asyncio.to_thread(render.render, plant, moisture_value, genome)
        return buffer.getvalue()

    def _embed_for(self, state: storage.GuildState) -> discord.Embed:
        """Build the living message's embed from a guild's current stored state."""
        return build_plant_embed(
            state.moisture, moisture.stage(state.moisture), state.structure.step_count
        )

    async def refresh_channel_message(self, guild_id: int) -> None:
        """Edit the living plant message in place, posting it if it is missing.

        Renders the guild's current structure and edits the tracked message; if
        that message was deleted (or none has been posted yet) a fresh one is
        posted and its id stored. Called by the tick and after a channel is bound.
        """
        state = self._states.get(guild_id)
        if state is None or state.channel_id is None:
            return
        channel = await self._text_channel(state.channel_id)
        if channel is None:
            return  # channel unreachable right now; the next tick will retry
        png = await self._render_bytes(state.structure, state.moisture)
        embed = self._embed_for(state)

        if state.message_id is not None:
            try:
                await channel.get_partial_message(state.message_id).edit(
                    embed=embed,
                    attachments=[discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME)],
                )
                return
            except discord.NotFound:
                pass  # the message is gone — fall through and post a fresh one

        message = await channel.send(
            embed=embed, file=discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME)
        )
        self._store(replace(self._states[guild_id], message_id=message.id))

    async def reanchor_channel_message(self, guild_id: int) -> None:
        """Move the living message back to the bottom of the channel.

        Best-effort deletes the current living message and posts a fresh one, so a
        plant that has scrolled out of view returns to where people are talking.
        """
        state = self._states.get(guild_id)
        if state is None or state.channel_id is None:
            return
        channel = await self._text_channel(state.channel_id)
        if channel is None:
            return
        if state.message_id is not None:
            await self._delete_message(channel, state.message_id)
        png = await self._render_bytes(state.structure, state.moisture)
        message = await channel.send(
            embed=self._embed_for(state),
            file=discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME),
        )
        self._store(replace(self._states[guild_id], message_id=message.id))

    def living_message_needs_reanchor(self, state: storage.GuildState) -> bool:
        """True if the living message is missing or has newer messages below it."""
        if state.message_id is None:
            return True
        channel = self.get_channel(state.channel_id) if state.channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return False
        last = channel.last_message_id
        return last is not None and last != state.message_id

    async def _delete_message(self, channel: discord.TextChannel, message_id: int) -> None:
        """Best-effort delete a message by id, ignoring an already-gone one."""
        try:
            await channel.get_partial_message(message_id).delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    async def _remove_stale_message(self, channel_id: int, message_id: int) -> None:
        """Delete a living message left behind in a channel the plant moved away from."""
        channel = await self._text_channel(channel_id)
        if channel is not None:
            await self._delete_message(channel, message_id)


client = EpiphyteClient()


@client.tree.command(
    name="plant",
    description="Show the plant right now, and bring it back into view.",
)
async def plant(interaction: discord.Interaction) -> None:
    """Render an immediate personal snapshot and re-anchor the living message.

    Growth is the metabolic tick's job now, so this never grows the plant. It
    renders the current state (moisture decayed to this moment, for display) as an
    ephemeral snapshot for the caller, and if the living channel message has
    scrolled out of view it quietly moves it back to the bottom.
    """
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Epiphyte only grows on servers, not in direct messages.",
            ephemeral=True,
        )
        return
    state = client.state(interaction.guild_id)
    if state is None or state.channel_id is None:
        await interaction.response.send_message(
            "No channel set yet. Use `/epiphyte-channel` to choose which channel "
            "the plant lives in.",
            ephemeral=True,
        )
        return

    now = time.time()
    display_moisture = moisture.decay(state.moisture, now - state.last_update)
    genome = structure.genome_from_seed(state.structure.seed)
    buffer = await asyncio.to_thread(render.render, state.structure, display_moisture, genome)
    embed = build_plant_embed(
        display_moisture, moisture.stage(display_moisture), state.structure.step_count
    )
    await interaction.response.send_message(
        embed=embed,
        file=discord.File(buffer, filename=PLANT_IMAGE_FILENAME),
        ephemeral=True,
    )

    if client.living_message_needs_reanchor(state):
        await client.reanchor_channel_message(interaction.guild_id)


@client.tree.command(
    name="epiphyte-channel",
    description="Choose the channel the plant lives in and is watered by.",
)
@app_commands.describe(channel="The text channel the plant lives in; messages there water it.")
async def epiphyte_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    """Bind the plant to a channel and post its living message there."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Epiphyte only grows on servers, not in direct messages.",
            ephemeral=True,
        )
        return

    previous = client.state(interaction.guild_id)
    client.set_channel(interaction.guild_id, channel.id, time.time())
    await interaction.response.send_message(
        f"🌱 The plant now lives in {channel.mention}. Every message there waters it, "
        "and it will grow there on its own over time.",
        ephemeral=True,
    )

    # If the plant moved channels, remove the stale living message it left behind.
    if (
        previous is not None
        and previous.message_id is not None
        and previous.channel_id not in (None, channel.id)
    ):
        await client._remove_stale_message(previous.channel_id, previous.message_id)
    # Post (or refresh) the living message in the now-current channel.
    await client.refresh_channel_message(interaction.guild_id)


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
