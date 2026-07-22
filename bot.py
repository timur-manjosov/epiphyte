"""Epiphyte — a Discord bot that grows a single plant per server.

Phase 6 (its own life): the plant now lives in the channel instead of being
summoned on demand. A recurring metabolic tick — the plant's heartbeat — advances
every plant one life-step and re-renders a single living message the bot keeps
updated in place, so the plant visibly grows and withers over days without any
command. Phase 8 closes the loop: a plant that dies of a lasting drought lingers a
few ticks as a bare grey body, then a mutated successor germinates in the same
message — the same message showing death and rebirth, generation after generation.
Phase 9 adds the rare states at the far end of that life: a plant kept healthy for
long enough comes into bloom, sets seed, and — if it grows very old on a channel
that never lets it go — takes on an epiphyte. The tick surfaces all of it; there is
still nothing to command.

Each guild binds a channel with ``/epiphyte-channel`` — that only decides where
the living message is shown. Once a guild has a plant, every message anywhere in
that guild passively waters it, and silence lets its moisture decay over days.
The tick grows one step per beat, gated by the current moisture, so a guild that
is active anywhere drives its plant forward and a quiet one lets it stagnate.
``/plant`` no longer grows anything: it shows an immediate personal snapshot and
brings the living message back into view if it has scrolled away.

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
from collections.abc import Callable
from dataclasses import dataclass, replace

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord import app_commands
from discord.ext import tasks

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

#: How many ticks a fully dead plant lingers as a bare grey body before a
#: successor germinates in its place — a short, visible dead phase.
DEAD_PHASE_TICKS = 3

#: Nord-themed embed colour per growth stage (driest to lushest).
STAGE_COLORS: dict[Stage, int] = {
    Stage.WITHERED: 0x5E4A3B,  # rooted stem brown
    Stage.DRY: 0x8FBCBB,       # pale living stem
    Stage.HEALTHY: 0xA3BE8C,   # leaf green
    Stage.THRIVING: 0x88C0D0,  # bud accent
}

#: Nord dark grey for the embed of a dead plant.
DEAD_EMBED_COLOR = 0x4C566A

#: Human-readable label per growth stage.
STAGE_LABELS: dict[Stage, str] = {
    Stage.WITHERED: "Withered",
    Stage.DRY: "Dry",
    Stage.HEALTHY: "Healthy",
    Stage.THRIVING: "Thriving",
}

#: Attachment filename referenced by the embed's image.
PLANT_IMAGE_FILENAME = "plant.png"

#: How often the bot's presence rotates to its next in-fiction status line.
PRESENCE_ROTATE_MINUTES = 10

#: Rotating status lines the bot "speaks" through its presence. Each pairs an
#: activity type with either a fixed string or a callable that builds one from
#: live data already on hand (e.g. the guild count) — no extra lookups needed.
PRESENCE_ACTIVITIES: tuple[tuple[discord.ActivityType, str | Callable[["EpiphyteClient"], str]], ...] = (
    (discord.ActivityType.playing, "growing quietly"),
    (discord.ActivityType.watching, "the light"),
    (discord.ActivityType.playing, "photosynthesizing"),
    (discord.ActivityType.listening, "for the next message"),
    (discord.ActivityType.watching, lambda client: f"over {len(client.guilds)} channels"),
)


@dataclass
class WateringWindow:
    """A person's diminishing-returns window.

    ``window_start`` is when the current window began; ``count`` is how many
    times the person has watered within it. Kept in memory only — losing it on a
    restart cannot help a flooder, since the persisted moisture keeps decaying.
    """

    window_start: float
    count: int


def describe_milestones(plant: structure.Structure, moisture_value: float) -> str:
    """Name the rare states the plant is showing, or an empty string for none."""
    marks = []
    if structure.is_blooming(plant, moisture_value):
        marks.append("🌸 in bloom")
    if structure.has_seeded(plant):
        marks.append("🌰 seeded")
    if plant.epiphyte is not None:
        marks.append("🌿 epiphyte")
    return " · ".join(marks)


def describe_lineage(plant: structure.Structure) -> str:
    """Say where the plant stands in its line, and how much of that line flowered."""
    if plant.lineage_blooms:
        return f"{plant.generation} · {plant.lineage_blooms} flowered before it"
    return str(plant.generation)


def build_plant_embed(moisture_value: float, plant: structure.Structure) -> discord.Embed:
    """Build the Nord-themed embed framing the plant image, values and lineage.

    A living plant shows its moisture, stage and age; a fully dead one shows that
    it has died and a successor is coming. Both show the lineage, so the plant's
    descent stays visible as it dies and is reborn, and both name whatever rare
    states the body is carrying — a bloom, the seed it has set, an epiphyte.
    """
    if structure.is_dead(plant):
        embed = discord.Embed(title="🥀 The plant has died", color=DEAD_EMBED_COLOR)
        embed.add_field(name="Status", value="A new seed will sprout soon")
        embed.add_field(name="Lived", value=f"{plant.step_count} steps")
    else:
        plant_stage = moisture.stage(moisture_value)
        blooming = structure.is_blooming(plant, moisture_value)
        embed = discord.Embed(
            title="🌸 The plant is in bloom" if blooming else "🌱 The plant",
            color=STAGE_COLORS[plant_stage],
        )
        embed.add_field(name="Moisture", value=f"{moisture_value:.0%}")
        embed.add_field(name="Stage", value=STAGE_LABELS[plant_stage])
        embed.add_field(name="Age", value=f"{plant.step_count} steps")
    embed.add_field(name="Generation", value=describe_lineage(plant))
    milestones = describe_milestones(plant, moisture_value)
    if milestones:
        embed.add_field(name="Milestones", value=milestones, inline=False)
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
        self._message_locks: dict[int, asyncio.Lock] = {}
        self._db_lock = asyncio.Lock()
        self._presence_index = 0
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
        """Shut down cleanly: stop the presence loop, the scheduler, and the database."""
        if self._rotate_presence.is_running():
            self._rotate_presence.cancel()
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._storage is not None:
            self._storage.close()
        await super().close()

    # --- state ---------------------------------------------------------------

    def _message_lock(self, guild_id: int) -> asyncio.Lock:
        """Return the guild's living-message lock, creating it on first use.

        Serializes :meth:`refresh_channel_message` and :meth:`reanchor_channel_message`
        per guild, so a slash command and the metabolic tick can never both find no
        tracked message at once and each post their own.
        """
        lock = self._message_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._message_locks[guild_id] = lock
        return lock

    async def _store(self, state: storage.GuildState) -> None:
        """Update the in-memory cache and persist the state immediately.

        The in-memory cache is updated synchronously, before any ``await``, so
        every reader of :attr:`_states` sees it immediately; only the disk write
        (matching the Pillow render's off-loop pattern) trails behind, serialized
        through :attr:`_db_lock` since the shared connection may only be touched
        by one thread at a time.
        """
        self._states[state.guild_id] = state
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.save, state)

    async def _store_watering(self, state: storage.GuildState) -> None:
        """Persist a watering, which moves the moisture but never the body.

        Kept apart from :meth:`_store` because this runs on every message, while an
        old plant's body is large enough that writing it out each time would cost
        real work in the one place the bot must stay cheap.
        """
        self._states[state.guild_id] = state
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.save_moisture, state)

    def state(self, guild_id: int) -> storage.GuildState | None:
        """Return a guild's plant state, or ``None`` if it has no plant yet."""
        return self._states.get(guild_id)

    async def set_channel(self, guild_id: int, channel_id: int, now: float) -> None:
        """Bind the guild's plant to a channel.

        On a guild's first contact this germinates a fresh plant from a new random
        seed — the seed is what makes each server's plant an individual. Rebinding
        to a *different* channel clears the tracked living message so a fresh one
        is posted there; rebinding to the same channel is a no-op.
        """
        state = self._states.get(guild_id)
        if state is None:
            seed = random.getrandbits(63)
            await self._store(
                storage.GuildState(
                    guild_id=guild_id,
                    structure=structure.germinate(seed),
                    moisture=moisture.MIN_MOISTURE,
                    last_update=now,
                    channel_id=channel_id,
                    message_id=None,
                    dead_ticks=0,
                )
            )
        elif state.channel_id != channel_id:
            await self._store(replace(state, channel_id=channel_id, message_id=None))

    async def water_plant(self, guild_id: int, user_id: int, now: float) -> None:
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
        await self._store_watering(
            replace(state, moisture=moisture.water(current, amount), last_update=now)
        )

    def _prune_watering_windows(self, now: float) -> None:
        """Drop watering windows whose window has fully elapsed.

        Without this, every (guild, user) pair that has ever watered would stay in
        memory for the bot's entire uptime — tracking everyone who ever has,
        instead of just who currently does. Run once per metabolic tick, since it
        already sweeps on a steady real-time interval.
        """
        expired = [
            key
            for key, window in self._windows.items()
            if now - window.window_start >= moisture.WATERING_WINDOW_SECONDS
        ]
        for key in expired:
            del self._windows[key]

    async def _reclaim_after_reseed(self) -> None:
        """Run VACUUM after a generational reseed, off the event loop.

        A death-to-rebirth reseed is a naturally rare event (unlike per-message or
        per-tick writes), and exactly when a large gone structure blob's freed
        pages become worth returning to the OS. Serialized through the same
        :attr:`_db_lock` as ordinary saves, so it never runs concurrently with one.
        """
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.vacuum)

    async def advance_life(self, guild_id: int, now: float) -> None:
        """Advance one guild's plant by a single life-step (the tick's core).

        Decays moisture to ``now``, then either grows the plant one step (gated by
        that moisture), or — if it is dead — counts down a brief dead phase and
        germinates a mutated successor when it elapses. All the growth, death and
        heredity is the pure logic in :mod:`structure`; this only reads the clock,
        runs the small state machine and stores the result.
        """
        state = self._states[guild_id]
        current = moisture.decay(state.moisture, now - state.last_update)

        if structure.is_dead(state.structure):
            dead_ticks = state.dead_ticks + 1
            if dead_ticks >= DEAD_PHASE_TICKS:
                successor = structure.germinate_successor(state.structure)
                await self._store(
                    replace(state, structure=successor, moisture=current,
                            last_update=now, dead_ticks=0)
                )
                await self._reclaim_after_reseed()
            else:
                await self._store(replace(state, moisture=current, last_update=now, dead_ticks=dead_ticks))
            return

        genome = structure.genome_from_seed(state.structure.seed)
        grown = structure.grow(state.structure, genome, current, 1)
        await self._store(replace(state, structure=grown, moisture=current, last_update=now, dead_ticks=0))

    async def on_message(self, message: discord.Message) -> None:
        """Water the plant when a message arrives anywhere in a guild with a plant.

        Ignores the bot's own messages, direct messages, and guilds that have not
        yet germinated a plant (no ``/epiphyte-channel`` call). Once a plant
        exists, every channel in the guild counts, not just the one the living
        message is displayed in. Only the fact that a message arrived matters —
        never its content.
        """
        if message.author == self.user:
            return
        if message.guild is None:
            return
        state = self.state(message.guild.id)
        if state is None or state.channel_id is None:
            return
        await self.water_plant(message.guild.id, message.author.id, time.time())

    # --- the metabolic tick --------------------------------------------------

    async def metabolic_tick(self) -> None:
        """The plant's heartbeat: advance every plant one life-step and refresh it.

        Runs at a fixed real interval while the bot is live. Each guild is handled
        independently, so one unreachable channel never stops the others. Growth,
        death and rebirth all flow through here, so the living message shows the
        whole life cycle without any command.
        """
        now = time.time()
        self._prune_watering_windows(now)
        for guild_id, state in list(self._states.items()):
            if state.channel_id is None:
                continue
            try:
                await self.advance_life(guild_id, now)
                await self.refresh_channel_message(guild_id)
            except Exception:  # noqa: BLE001 — one guild must not break the rest
                _log.exception("Metabolic tick failed for guild %s.", guild_id)

    # --- the rotating presence -------------------------------------------------

    @tasks.loop(minutes=PRESENCE_ROTATE_MINUTES)
    async def _rotate_presence(self) -> None:
        """Advance to the next in-fiction status line and apply it.

        Purely cosmetic flavour text — never a stand-in for the plant's real
        state, which only ever shows in the living message and embeds.
        """
        activity_type, text = PRESENCE_ACTIVITIES[self._presence_index % len(PRESENCE_ACTIVITIES)]
        self._presence_index += 1
        name = text(self) if callable(text) else text
        await self.change_presence(activity=discord.Activity(type=activity_type, name=name))

    async def on_ready(self) -> None:
        """Start the presence rotation once connected.

        ``on_ready`` can fire again on every reconnect, unlike ``setup_hook``, so
        the loop is only started if it is not already running.
        """
        if not self._rotate_presence.is_running():
            self._rotate_presence.start()

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
        return build_plant_embed(state.moisture, state.structure)

    async def refresh_channel_message(self, guild_id: int) -> None:
        """Edit the living plant message in place, posting it if it is missing.

        Renders the guild's current structure and edits the tracked message; if
        that message was deleted (or none has been posted yet) a fresh one is
        posted and its id stored. Called by the tick and after a channel is bound.
        Holds the guild's :meth:`_message_lock` for its whole body, so it can
        never race a concurrent :meth:`reanchor_channel_message` into posting twice.
        """
        async with self._message_lock(guild_id):
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
                except (discord.Forbidden, discord.HTTPException):
                    _log.exception("Failed to edit the living message for guild %s.", guild_id)
                    return

            try:
                message = await channel.send(
                    embed=embed, file=discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME)
                )
            except (discord.Forbidden, discord.HTTPException):
                _log.exception("Failed to post the living message for guild %s.", guild_id)
                return
            await self._store(replace(self._states[guild_id], message_id=message.id))

    async def reanchor_channel_message(self, guild_id: int) -> None:
        """Move the living message back to the bottom of the channel.

        Best-effort deletes the current living message and posts a fresh one, so a
        plant that has scrolled out of view returns to where people are talking.
        Shares :meth:`refresh_channel_message`'s per-guild lock, so the two can
        never both find no tracked message and each post their own.
        """
        async with self._message_lock(guild_id):
            state = self._states.get(guild_id)
            if state is None or state.channel_id is None:
                return
            channel = await self._text_channel(state.channel_id)
            if channel is None:
                return
            if state.message_id is not None:
                await self._delete_message(channel, state.message_id)
            png = await self._render_bytes(state.structure, state.moisture)
            try:
                message = await channel.send(
                    embed=self._embed_for(state),
                    file=discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME),
                )
            except (discord.Forbidden, discord.HTTPException):
                _log.exception("Failed to re-anchor the living message for guild %s.", guild_id)
                return
            await self._store(replace(self._states[guild_id], message_id=message.id))

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
    embed = build_plant_embed(display_moisture, state.structure)
    try:
        await interaction.response.send_message(
            embed=embed,
            file=discord.File(buffer, filename=PLANT_IMAGE_FILENAME),
            ephemeral=True,
        )
    except (discord.Forbidden, discord.HTTPException):
        _log.exception("Failed to send the /plant snapshot for guild %s.", interaction.guild_id)
        return

    if client.living_message_needs_reanchor(state):
        await client.reanchor_channel_message(interaction.guild_id)


@client.tree.command(
    name="epiphyte-channel",
    description="Choose the channel the plant is displayed in.",
)
@app_commands.describe(channel="The text channel the plant's living message is posted in.")
async def epiphyte_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    """Bind the plant's display channel and post its living message there."""
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Epiphyte only grows on servers, not in direct messages.",
            ephemeral=True,
        )
        return

    previous = client.state(interaction.guild_id)
    await client.set_channel(interaction.guild_id, channel.id, time.time())
    try:
        await interaction.response.send_message(
            f"🌱 The plant now lives in {channel.mention}. Activity anywhere in this "
            "server waters it, and it will grow there on its own over time.",
            ephemeral=True,
        )
    except (discord.Forbidden, discord.HTTPException):
        _log.exception("Failed to confirm channel binding for guild %s.", interaction.guild_id)

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
