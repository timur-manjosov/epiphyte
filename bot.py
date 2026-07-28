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

Phase 15 adds one more signal, reactions, but wires it in a deliberately
different shape from breadth and rhythm: ``on_raw_reaction_add`` tops up a
reactor's presence weight (the same anti-farmed, per-person diminishing-returns
shape watering itself uses — see ``_water_reactor_presence``), a self-reaction
counts for nothing, and the guild's current reaction warmth
(``_guild_reaction_warmth``, read the same way author breadth is) is handed to
``structure.grow`` every tick — but that value only ever gets *used* on the one
step a bloom already earned by Phase 9's gate begins, becoming that bloom's
fixed vividness for its whole duration. It is never a second gate on bloom
itself, and it never touches growth, branching or moisture.

Phase 16 adds a fourth: threads. ``on_message`` also records activity in any
thread it fires for, and ``on_thread_create`` records a thread's creation
instant and owner — both standard, non-privileged events, no new intent.
``_guild_thread_depth`` aggregates that per-thread activity into how many
currently-live threads clear ``structure.thread_qualifies`` (genuinely
multi-participant, not a burst, not a monologue) and hands the resulting
``structure.thread_depth`` reading into every tick's growth step alongside
breadth and rhythm — a channel whose conversations regularly spin off into
sustained threads grows a more deeply nested branch structure than one whose
activity stays flat, at the same size and the same crown width.

Everything the plant says about itself, it says in the first person: the living
message's heading and text are spoken by ``voice``, which reads them from the
body and the moisture. Where those words land — the accent colour, which
instruments stand beside them, whether the picture leads or accompanies them —
is decided by ``presentation``, from the same state. Operational replies —
permissions, an unreachable channel, the setup notice, ``/help`` — deliberately
stay plain and hold one fixed colour, so nobody has to read poetry to find out
what broke. See "Die Stimme der Pflanze" and "Präsentation" in ``CLAUDE.md``.

This module is the thin Discord adapter: client, commands, events, the scheduler
wiring and the living-message I/O. The interesting computation lives in the pure
``moisture``, ``structure``, ``voice`` and ``presentation`` modules; ``render``
isolates the Pillow drawing and ``storage`` the SQLite persistence.
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
from discord.ext import tasks

import moisture
import presentation
import render
import storage
import structure
import voice

_log = logging.getLogger("epiphyte")

#: Name of the required environment variable holding the bot token.
TOKEN_ENV = "EPIPHYTE_TOKEN"
#: Name of the optional environment variable holding the test guild id.
GUILD_ENV = "EPIPHYTE_GUILD_ID"

#: Real time between metabolic ticks: the plant's heartbeat. Each tick grows every
#: plant exactly one step, so this constant *is* the real duration of one growth
#: step — a big tree is the reward of weeks of ticks, not one busy evening. It sits
#: far above Discord's message-edit rate limit, so re-rendering once per tick never
#: edits too often. Deliberately left unchanged through Phase 8 and 9: a week's worth
#: of growth should cost a week's worth of ticks, not a debugging session's worth.
TICK_INTERVAL_SECONDS = 60 * 60  # 1 hour

#: How many ticks a fully dead plant lingers as a bare grey body before a
#: successor germinates in its place — a short, visible dead phase.
DEAD_PHASE_TICKS = 3

#: Presence weight below which an author's recorded row is dropped as negligible.
#: Checked once per metabolic tick alongside the breadth calculation, so the
#: author_presence table (and its in-memory mirror) stays bounded to genuinely
#: still-relevant recent voices rather than growing with every person who has
#: ever posted once, long after their presence has decayed away.
AUTHOR_PRESENCE_PRUNE_FLOOR = 0.01

#: Seconds in a whole day — the bucket size structure.day_bucket() groups
#: messages into for structure.temporal_rhythm().
DAY_SECONDS = 24 * 60 * 60

#: Attachment filename referenced by the embed's image.
PLANT_IMAGE_FILENAME = "plant.png"

#: Nord accent used for the /help embeds. Operational surfaces hold one fixed
#: colour on purpose: unlike the living message, they are not a readout of
#: anything, and somebody reading them wants an explanation, not a mood.
HELP_EMBED_COLOR = presentation.PLAIN_ACCENT

#: Project repository, credited once in /help.
REPO_URL = "https://github.com/timur-manjosov/epiphyte"

#: How often the bot's presence rotates to its next in-fiction status line.
PRESENCE_ROTATE_MINUTES = 10

#: Discord's activity type per activity kind named in :data:`voice.PRESENCE_LINES`.
#: The lines themselves live with the rest of the plant's speech in ``voice``,
#: which stays free of ``import discord``; this is the one mapping that needs both.
ACTIVITY_TYPES: dict[str, discord.ActivityType] = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
}


@dataclass
class WateringWindow:
    """A person's diminishing-returns window.

    ``window_start`` is when the current window began; ``count`` is how many
    times the person has watered within it. Kept in memory only — losing it on a
    restart cannot help a flooder, since the persisted moisture keeps decaying.
    """

    window_start: float
    count: int


def build_plant_embed(moisture_value: float, plant: structure.Structure) -> discord.Embed:
    """Build the embed framing the plant image, its words and its instruments.

    Every decision worth making here — the accent colour, which instruments are
    shown, whether the picture leads or accompanies the text, the footer — is made
    in :mod:`presentation` as a pure function of the plant's state, so it is
    testable without Discord. This function is only the pour: it turns that
    :class:`presentation.Panel` into the Discord object it was designed for and
    knows nothing else.
    """
    panel = presentation.compose(plant, moisture_value, TICK_INTERVAL_SECONDS)
    embed = discord.Embed(title=panel.title, description=panel.body, color=panel.accent)
    for field in panel.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    if panel.image is presentation.ImagePlacement.THUMBNAIL:
        embed.set_thumbnail(url=f"attachment://{PLANT_IMAGE_FILENAME}")
    else:
        embed.set_image(url=f"attachment://{PLANT_IMAGE_FILENAME}")
    embed.set_footer(text=panel.footer)
    return embed


def build_help_pages() -> list[discord.Embed]:
    """Build the /help embeds, one per page, in display order.

    The cited durations are computed from :mod:`moisture`'s own constants rather
    than restated as free-standing numbers, so a future recalibration keeps this
    text honest without a separate edit. Split across pages instead of one long
    embed so each page stays a short read; :class:`HelpView` pages through them.
    """
    tick_hours = TICK_INTERVAL_SECONDS // 3600
    hour_word = "hour" if tick_hours == 1 else "hours"
    wither_days = round(3 * moisture.DEFAULT_HALF_LIFE_SECONDS / (24 * 60 * 60))

    overview = discord.Embed(
        title="🌱 Epiphyte",
        description=(
            "A single plant lives in this server, shaped by its whole history rather "
            "than any one moment. Every message sent anywhere in the server waters it "
            f"a little; it grows on its own about once every {tick_hours} {hour_word}, "
            f"and roughly {wither_days} days of real silence dry it from thriving back "
            "down to withered. Neglect that lasts long enough leaves permanent scars "
            "and can kill it outright — but a mutated successor always regrows in its "
            "place. Nothing here can be farmed, and there is no leaderboard."
        ),
        color=HELP_EMBED_COLOR,
    )

    commands_page = discord.Embed(
        title="Commands",
        description=(
            "`/epiphyte-channel <channel>` — bind or move the plant to a channel "
            "(on a server's first use, this asks for confirmation before it "
            "germinates anything)\n\n"
            "`/plant` — a private, on-the-spot look at your plant right now\n\n"
            "`/help` — this explanation"
        ),
        color=HELP_EMBED_COLOR,
    )

    on_its_own_time = discord.Embed(
        title="On Its Own Time",
        description=(
            "Growth, blooming, seeding and the rare secondary epiphyte all happen by "
            "themselves as the plant lives — none of it can be triggered on demand. "
            "Check back after some real activity, not right after a test message."
        ),
        color=HELP_EMBED_COLOR,
    )

    persistence = discord.Embed(
        title="Persistence & Permanence",
        description=(
            "Each server's plant is permanent for as long as the server has one: "
            "kicking the bot and re-inviting it later does **not** reset anything. "
            "State lives independently of the bot's membership, so the plant just "
            "picks up where it left off. There is deliberately no delete or reset "
            "command — that would make removing and re-adding the bot a loophole."
        ),
        color=HELP_EMBED_COLOR,
    )

    pages = [overview, commands_page, on_its_own_time, persistence]
    for index, page in enumerate(pages, start=1):
        page.set_footer(text=f"Page {index}/{len(pages)} · Open source, MIT licensed · {REPO_URL}")
    return pages


class HelpView(discord.ui.View):
    """Previous/Next pagination for /help, usable only by the person who ran it.

    Buttons are disabled in place once the view times out, instead of being left
    clickable but silently dead.
    """

    def __init__(self, pages: list[discord.Embed], author_id: int) -> None:
        super().__init__(timeout=180)
        self._pages = pages
        self._author_id = author_id
        self._index = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the person who ran ``/help`` may page through it."""
        if interaction.user.id != self._author_id:
            await interaction.response.send_message(
                "Only the person who ran `/help` can page through this.", ephemeral=True
            )
            return False
        return True

    def _update_buttons(self) -> None:
        """Disable Previous/Next at the first/last page instead of wrapping."""
        self.previous_page.disabled = self._index == 0
        self.next_page.disabled = self._index == len(self._pages) - 1

    async def on_timeout(self) -> None:
        """Grey out both buttons on the original message once the view expires."""
        self.previous_page.disabled = True
        self.next_page.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Step back one page."""
        self._index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._pages[self._index], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Step forward one page."""
        self._index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._pages[self._index], view=self)


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
        #: Per guild, per author: (presence weight, last_seen). Mirrors
        #: ``self._states`` so a rapid run of messages from the same author can
        #: never read stale data between one update and the next; see
        #: ``_water_author_presence``.
        self._author_presence: dict[int, dict[int, tuple[float, float]]] = {}
        #: Per guild, per calendar day bucket: raw message count. Feeds
        #: ``structure.temporal_rhythm`` via ``_guild_rhythm``; see
        #: ``_record_daily_activity``.
        self._daily_activity: dict[int, dict[int, int]] = {}
        #: Per guild, per reactor: (presence weight, last_seen). Mirrors
        #: ``self._author_presence`` exactly, but for genuine (non-self)
        #: reactions rather than messages; see ``_water_reactor_presence``.
        self._reactor_presence: dict[int, dict[int, tuple[float, float]]] = {}
        #: Per-reactor diminishing-returns window, kept apart from
        #: ``self._windows`` (message watering) since reacting and posting are
        #: separate actions with their own anti-farming curves.
        self._reaction_windows: dict[tuple[int, int], WateringWindow] = {}
        #: Per guild, per thread, per author: (message count, first_seen,
        #: last_seen). Feeds ``structure.thread_depth`` via
        #: ``_guild_thread_depth``; see ``_record_thread_activity``. Carries no
        #: decayed weight, unlike ``self._author_presence`` — a thread's short
        #: life is plain counts and timestamps, not a value that fades over
        #: weeks (see storage.py's module docstring).
        self._thread_activity: dict[int, dict[int, dict[int, tuple[int, float, float]]]] = {}
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
        self._author_presence = self._storage.load_all_author_presence()
        self._daily_activity = self._storage.load_all_daily_activity()
        self._reactor_presence = self._storage.load_all_reactor_presence()
        self._thread_activity = self._storage.load_all_thread_activity()

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

    async def germinate_plant(self, guild_id: int, channel_id: int, now: float) -> bool:
        """Germinate a guild's very first plant, bound to the given channel.

        A fresh random seed makes this server's plant an individual. Only ever
        called after the user has confirmed the persistence notice shown by
        ``/epiphyte-channel`` on a guild's first use — the rebind case in
        :meth:`set_channel` never reaches here.

        Guards against two confirmations racing for the same guild: if two
        people each open ``/epiphyte-channel`` before either confirms, both get
        their own view, and both may later be confirmed. The existence check
        below and the cache write inside :meth:`_store` have no ``await``
        between them, so no other task can run in between — asyncio only
        switches tasks at an ``await`` point, and there isn't one here. The
        first confirmation to actually execute this method therefore always
        makes the guild non-``None`` before a second one can check, so the
        loser sees the plant already there and returns ``False`` instead of
        overwriting it with a fresh seed and generation 1. Returns ``True`` if
        this call germinated the plant, ``False`` if the guild already had one.
        """
        if self._states.get(guild_id) is not None:
            return False
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
        return True

    async def set_channel(self, guild_id: int, channel_id: int) -> None:
        """Rebind an already-germinated guild's plant to a (possibly new) channel.

        Clears the tracked living message so a fresh one is posted in the new
        channel; rebinding to the same channel is a no-op. A guild with no plant
        yet is a no-op here too — first-time germination is a separate, confirmed
        step (see :meth:`germinate_plant`), not something this silently does.
        """
        state = self._states.get(guild_id)
        if state is not None and state.channel_id != channel_id:
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
        await self._water_author_presence(guild_id, user_id, amount, now)
        await self._record_daily_activity(guild_id, now)

    async def _water_author_presence(
        self, guild_id: int, author_id: int, amount: float, now: float
    ) -> None:
        """Add this message's anti-farmed watering amount to the author's presence weight.

        Reuses ``amount`` — already discounted by the same per-person diminishing
        returns as moisture (see :func:`moisture.next_watering`) — so a single
        account can only build genuine presence by returning across several
        distinct real days, exactly as it can only meaningfully water the plant
        that way (see :func:`structure.author_breadth`). The in-memory cache is
        updated synchronously, mirroring :meth:`_store_watering`, so a second
        message from the same author an instant later always sees this one's
        update; only the disk write trails behind.
        """
        guild_presence = self._author_presence.setdefault(guild_id, {})
        weight, last_seen = guild_presence.get(author_id, (0.0, now))
        decayed = moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
        updated = moisture.water(decayed, amount)
        guild_presence[author_id] = (updated, now)
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(
                    self._storage.upsert_author_presence, guild_id, author_id, updated, now
                )

    async def _record_daily_activity(self, guild_id: int, now: float) -> None:
        """Count one message toward its calendar day, feeding temporal rhythm.

        Deliberately counts every message, not a diminishing-returns-discounted
        amount like :meth:`_water_author_presence` does: rhythm reads *when*
        activity happens, not who it came from, and its farming resistance comes
        from a different property — see :func:`structure.temporal_rhythm`'s
        docstring — so there is no per-person amount to reuse here. The in-memory
        cache is updated synchronously, mirroring :meth:`_water_author_presence`,
        so a second message an instant later always sees this one's update.
        """
        bucket = structure.day_bucket(now)
        guild_days = self._daily_activity.setdefault(guild_id, {})
        guild_days[bucket] = guild_days.get(bucket, 0) + 1
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.increment_daily_activity, guild_id, bucket)

    async def _water_reactor_presence(self, guild_id: int, reactor_id: int, now: float) -> None:
        """Add a genuine reaction's anti-farmed watering amount to the reactor's presence weight.

        Mirrors :meth:`_water_author_presence` exactly, but keyed by its own
        window (``self._reaction_windows``) and its own table
        (``reactor_presence``): reacting and posting are separate actions, each
        with its own per-person diminishing-returns curve computed from
        :func:`moisture.next_watering`, so a single account cannot buy a wide
        reaction-warmth reading either by flooding one day or by trading
        reactions with the same handful of people — only distinct reactors,
        each sustaining real presence over real days, cross
        :data:`structure.AUTHOR_PRESENCE_FLOOR` and start to count (see
        :meth:`_guild_reaction_warmth`). Only ever called for a genuine
        reaction — the caller (:meth:`on_raw_reaction_add`) has already
        excluded a message author reacting to their own message, which counts
        for nothing here or anywhere else.
        """
        window = self._reaction_windows.get((guild_id, reactor_id))
        start = window.window_start if window is not None else None
        count = window.count if window is not None else 0
        amount, new_start, new_count = moisture.next_watering(start, count, now)
        self._reaction_windows[(guild_id, reactor_id)] = WateringWindow(new_start, new_count)

        guild_reactors = self._reactor_presence.setdefault(guild_id, {})
        weight, last_seen = guild_reactors.get(reactor_id, (0.0, now))
        decayed = moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
        updated = moisture.water(decayed, amount)
        guild_reactors[reactor_id] = (updated, now)
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(
                    self._storage.upsert_reactor_presence, guild_id, reactor_id, updated, now
                )

    async def _guild_reaction_warmth(self, guild_id: int, now: float) -> float:
        """Decay this guild's recorded reactors to ``now``, drop the negligible
        ones, and return its current reaction-warmth score.

        Deliberately reuses :func:`structure.author_breadth` rather than a
        parallel calculation: "how many distinct people cleared the presence
        floor, saturating at a modest count" is exactly the same anti-clique,
        anti-farming property reaction warmth needs, and there is no reason to
        calibrate it a second time. Mirrors :meth:`_guild_author_breadth`'s
        pruning, over ``self._reactor_presence`` instead.
        """
        guild_reactors = self._reactor_presence.get(guild_id, {})
        stale: list[int] = []
        weights: list[float] = []
        for reactor_id, (weight, last_seen) in list(guild_reactors.items()):
            decayed = moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
            if decayed < AUTHOR_PRESENCE_PRUNE_FLOOR:
                stale.append(reactor_id)
                del guild_reactors[reactor_id]
            else:
                weights.append(decayed)
        if stale and self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.delete_reactor_presence, guild_id, stale)
        return structure.author_breadth(weights)

    async def _guild_author_breadth(self, guild_id: int, now: float) -> float:
        """Decay this guild's recorded voices to ``now``, drop the negligible ones,
        and return its current author-breadth score (see :func:`structure.author_breadth`).

        Pruning here — once per metabolic tick — is the one place the table (and
        its in-memory mirror) is swept, so it stays bounded to genuinely
        still-relevant recent voices.
        """
        guild_presence = self._author_presence.get(guild_id, {})
        stale: list[int] = []
        weights: list[float] = []
        for author_id, (weight, last_seen) in list(guild_presence.items()):
            decayed = moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
            if decayed < AUTHOR_PRESENCE_PRUNE_FLOOR:
                stale.append(author_id)
                del guild_presence[author_id]
            else:
                weights.append(decayed)
        if stale and self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.delete_author_presence, guild_id, stale)
        return structure.author_breadth(weights)

    async def _guild_rhythm(self, guild_id: int, now: float) -> float:
        """Prune this guild's daily-activity window to now, and return its rhythm.

        Drops day buckets older than :data:`structure.RHYTHM_WINDOW_DAYS`
        (mirroring the pruning :meth:`_guild_author_breadth` does for presence,
        just on a calendar-day cadence rather than a decayed weight), then
        zero-fills every day in the window that has no recorded messages before
        handing the list to :func:`structure.temporal_rhythm` — silence is a data
        point for rhythm, not a gap to skip.
        """
        today = structure.day_bucket(now)
        window_start = today - structure.RHYTHM_WINDOW_DAYS + 1
        guild_days = self._daily_activity.get(guild_id, {})
        stale = [bucket for bucket in guild_days if bucket < window_start]
        for bucket in stale:
            del guild_days[bucket]
        if stale and self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.prune_daily_activity, guild_id, window_start)
        counts = [guild_days.get(bucket, 0) for bucket in range(window_start, today + 1)]
        return structure.temporal_rhythm(counts)

    async def _record_thread_activity(
        self, guild_id: int, thread_id: int, author_id: int, now: float, increment: bool
    ) -> None:
        """Record one author's activity in one thread, feeding thread depth.

        Mirrors :meth:`_water_author_presence`'s cache-then-persist shape, but
        carries no decayed weight — see storage.py's module docstring for why a
        thread's short life is tracked as plain counts and timestamps instead.
        ``increment`` distinguishes an actual message (called from
        :meth:`on_message`) from a thread's creation instant (called from
        :meth:`on_thread_create`); either way ``last_seen`` advances to ``now``
        and an existing row's ``first_seen`` is preserved, so a row's span
        always starts at whichever of the two events reached this author first.
        """
        guild_threads = self._thread_activity.setdefault(guild_id, {})
        thread_rows = guild_threads.setdefault(thread_id, {})
        count, first_seen, _ = thread_rows.get(author_id, (0, now, now))
        thread_rows[author_id] = (count + (1 if increment else 0), first_seen, now)
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(
                    self._storage.upsert_thread_activity, guild_id, thread_id, author_id, now, increment
                )

    async def _guild_thread_depth(self, guild_id: int, now: float) -> float:
        """Aggregate this guild's recorded thread activity into its thread-depth score.

        Groups the per-(thread, author) rows this guild has accumulated by
        thread, drops threads that have gone fully stale (no message from
        anyone within :data:`structure.THREAD_RECENCY_SECONDS` of ``now`` —
        mirroring :meth:`_guild_author_breadth`'s and :meth:`_guild_rhythm`'s
        own per-tick pruning), and counts how many of the threads left clear
        :func:`structure.thread_qualifies`. Every thread left after pruning is,
        by construction, still within the recency window, so only whether it
        ever qualified remains to check.
        """
        guild_threads = self._thread_activity.get(guild_id, {})
        cutoff = now - structure.THREAD_RECENCY_SECONDS
        stale_threads = [
            thread_id
            for thread_id, rows in guild_threads.items()
            if max(last_seen for _, _, last_seen in rows.values()) < cutoff
        ]
        for thread_id in stale_threads:
            del guild_threads[thread_id]
        if stale_threads and self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.prune_thread_activity, guild_id, cutoff)

        qualifying = sum(
            1
            for rows in guild_threads.values()
            if structure.thread_qualifies(
                [count for count, _, _ in rows.values()],
                min(first_seen for _, first_seen, _ in rows.values()),
                max(last_seen for _, _, last_seen in rows.values()),
            )
        )
        return structure.thread_depth(qualifying)

    async def _clear_author_presence(self, guild_id: int) -> None:
        """Wipe a guild's recorded voices when its successor germinates.

        Breadth is this life's own accumulated crowd, not the lineage's — like
        :class:`structure.LifeStats`, a new generation starts unheard and must
        earn its own again.
        """
        self._author_presence.pop(guild_id, None)
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.clear_author_presence, guild_id)

    async def _clear_reactor_presence(self, guild_id: int) -> None:
        """Wipe a guild's recorded reactors when its successor germinates.

        Mirrors :meth:`_clear_author_presence`: reaction warmth is this life's
        own accumulated crowd, not the lineage's.
        """
        self._reactor_presence.pop(guild_id, None)
        if self._storage is not None:
            async with self._db_lock:
                await asyncio.to_thread(self._storage.clear_reactor_presence, guild_id)

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
        that moisture and, for its shape, by the guild's current author breadth,
        temporal rhythm and thread depth — see :meth:`_guild_author_breadth`,
        :meth:`_guild_rhythm` and :meth:`_guild_thread_depth`), or — if it is
        dead — counts down a brief dead phase and germinates a mutated successor
        when it elapses, wiping the recorded voices (and reactors) along with it.
        The recorded daily activity behind rhythm, and the recorded thread
        activity behind thread depth, are deliberately *not* wiped on rebirth —
        see ``storage.py``'s module docstring. The guild's current reaction
        warmth (:meth:`_guild_reaction_warmth`) is also passed into every growth
        step, but — unlike breadth, rhythm and thread depth — it shapes nothing
        about growth itself; :func:`structure.grow` only ever samples it on the
        one step a bloom begins. All the growth, death and heredity is the pure
        logic in :mod:`structure`; this only reads the clock, runs the small
        state machine and stores the result.
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
                await self._clear_author_presence(guild_id)
                await self._clear_reactor_presence(guild_id)
                await self._reclaim_after_reseed()
            else:
                await self._store(replace(state, moisture=current, last_update=now, dead_ticks=dead_ticks))
            return

        genome = structure.genome_from_seed(state.structure.seed)
        breadth = await self._guild_author_breadth(guild_id, now)
        rhythm = await self._guild_rhythm(guild_id, now)
        reaction_warmth = await self._guild_reaction_warmth(guild_id, now)
        thread_depth = await self._guild_thread_depth(guild_id, now)
        grown = structure.grow(
            state.structure, genome, current, 1, breadth, rhythm, reaction_warmth, thread_depth
        )
        await self._store(replace(state, structure=grown, moisture=current, last_update=now, dead_ticks=0))

    async def on_message(self, message: discord.Message) -> None:
        """Water the plant when a message arrives anywhere in a guild with a plant.

        Ignores the bot's own messages, direct messages, and guilds that have not
        yet germinated a plant (no ``/epiphyte-channel`` call). Once a plant
        exists, every channel in the guild counts, not just the one the living
        message is displayed in. Only the fact that a message arrived matters —
        never its content. If the message landed in a thread, it also feeds
        that thread's activity toward thread depth (see
        :meth:`_record_thread_activity`) — a standard, non-privileged event
        already covered by the same intents watering itself uses.
        """
        if message.author == self.user:
            return
        if message.guild is None:
            return
        state = self.state(message.guild.id)
        if state is None or state.channel_id is None:
            return
        now = time.time()
        await self.water_plant(message.guild.id, message.author.id, now)
        if isinstance(message.channel, discord.Thread):
            await self._record_thread_activity(
                message.guild.id, message.channel.id, message.author.id, now, increment=True
            )

    async def on_thread_create(self, thread: discord.Thread) -> None:
        """Register a new thread's creation instant and owner, feeding thread depth.

        Threads are a standard, non-privileged gateway event — no new intent.
        Recording the creation moment (rather than only the first tracked
        message) anchors :data:`structure.THREAD_MIN_SPAN_SECONDS` to the
        thread's actual lifespan: a thread that sits open and silent for a
        while before anyone replies does not get a falsely short span just
        because its first *message* landed late. The owner is recorded with
        zero messages so far — see :func:`structure.thread_qualifies`, an
        entry below :data:`structure.THREAD_MIN_MESSAGES_PER_PARTICIPANT`
        never counts toward the participant bar on its own, so this alone can
        never qualify a thread.
        """
        if thread.owner_id is None:
            return
        state = self.state(thread.guild.id)
        if state is None or state.channel_id is None:
            return
        await self._record_thread_activity(
            thread.guild.id, thread.id, thread.owner_id, time.time(), increment=False
        )

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Credit a genuine reaction toward the guild's reaction-warmth reading.

        Uses the raw event (rather than ``on_reaction_add``) so this fires even
        for messages outside the client's cache, exactly like ``on_message``
        needs no cache either. Reactions are a standard, non-privileged gateway
        event — ``discord.Intents.default()`` already covers them, so this adds
        no new intent. Ignores DMs, the bot's own reactions, guilds with no
        plant yet, and — the anti-farming rule at the heart of this signal — a
        message author reacting to their own message: ``message_author_id`` is
        included on the raw payload for every ``REACTION_ADD``, so a
        self-reaction is detected and excluded here before it ever reaches
        :meth:`_water_reactor_presence`, rather than merely discounted.
        """
        if payload.guild_id is None:
            return
        if payload.user_id == (self.user.id if self.user else None):
            return
        if payload.message_author_id is None or payload.user_id == payload.message_author_id:
            return
        state = self.state(payload.guild_id)
        if state is None or state.channel_id is None:
            return
        await self._water_reactor_presence(payload.guild_id, payload.user_id, time.time())

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
        kind, name = voice.PRESENCE_LINES[self._presence_index % len(voice.PRESENCE_LINES)]
        self._presence_index += 1
        await self.change_presence(activity=discord.Activity(type=ACTIVITY_TYPES[kind], name=name))

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

    async def _mark_channel_unreachable(self, state: storage.GuildState) -> None:
        """Record that the living message currently cannot be delivered, if not already.

        Shared by both causes the living-message I/O can hit: the bound channel
        no longer resolves at all (deleted, or the bot lost access to it), and
        the channel resolves fine but the bot lacks permission to post there
        (``discord.Forbidden`` on the send/edit itself). Both are surfaced through
        this one timestamp; :meth:`_channel_trouble_message` re-derives which of
        the two currently applies for /plant's wording rather than this storing
        that distinction, so no schema change is needed for it. Re-reads the
        guild's current cached state by id rather than trusting the caller's own
        copy, since a concurrent watering may have updated it in the meantime
        (network I/O and rendering both happen before this is called).
        """
        current = self._states.get(state.guild_id)
        if current is not None and current.channel_unreachable_since is None:
            await self._store(replace(current, channel_unreachable_since=time.time()))

    async def _mark_channel_reachable(self, state: storage.GuildState) -> None:
        """Clear the unreachable timestamp once delivery is confirmed working again.

        Only writes if it was actually set, so a healthy channel costs no extra
        write on every tick. See :meth:`_mark_channel_unreachable` for why this
        re-reads the current cached state rather than trusting ``state`` as passed.
        """
        current = self._states.get(state.guild_id)
        if current is not None and current.channel_unreachable_since is not None:
            await self._store(replace(current, channel_unreachable_since=None))

    async def _channel_trouble_message(self, channel_id: int) -> str:
        """Explain, for /plant, why the living message currently isn't showing.

        Only meaningful once :attr:`storage.GuildState.channel_unreachable_since`
        is set. Re-checks live whether the bound channel still resolves at all:
        that one cheap lookup is enough to tell the two causes apart without
        persisting which one applies — if it resolves, the most likely explanation
        is a missing Send Messages permission there; if it does not, the channel
        itself is gone or the bot has lost access to it entirely.
        """
        channel = await self._text_channel(channel_id)
        if channel is None:
            return (
                "The plant itself is fine and still growing — it just looks like its "
                "bound channel isn't there anymore. Run `/epiphyte-channel` again to "
                "give it a new home."
            )
        return (
            "The plant itself is fine and still growing — it just can't post in its "
            "bound channel right now, most likely a missing **Send Messages** "
            "permission there. Fix that permission, or run `/epiphyte-channel` again "
            "to move it somewhere it can post."
        )

    async def refresh_channel_message(self, guild_id: int) -> None:
        """Edit the living plant message in place, posting it if it is missing.

        Renders the guild's current structure and edits the tracked message; if
        that message was deleted (or none has been posted yet) a fresh one is
        posted and its id stored. Called by the tick and after a channel is bound.
        Holds the guild's :meth:`_message_lock` for its whole body, so it can
        never race a concurrent :meth:`reanchor_channel_message` into posting twice.
        Records when the living message first becomes undeliverable — the bound
        channel no longer resolves, or it resolves but posting there is
        ``discord.Forbidden`` — and clears that record once delivery succeeds
        again; growth itself is unaffected either way.
        """
        async with self._message_lock(guild_id):
            state = self._states.get(guild_id)
            if state is None or state.channel_id is None:
                return
            channel = await self._text_channel(state.channel_id)
            if channel is None:
                await self._mark_channel_unreachable(state)
                return  # channel unreachable right now; the next tick will retry
            png = await self._render_bytes(state.structure, state.moisture)
            embed = self._embed_for(state)

            if state.message_id is not None:
                try:
                    await channel.get_partial_message(state.message_id).edit(
                        embed=embed,
                        attachments=[discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME)],
                    )
                    await self._mark_channel_reachable(state)
                    return
                except discord.NotFound:
                    pass  # the message is gone — fall through and post a fresh one
                except discord.Forbidden:
                    await self._mark_channel_unreachable(state)
                    return
                except discord.HTTPException:
                    _log.exception("Failed to edit the living message for guild %s.", guild_id)
                    return

            try:
                message = await channel.send(
                    embed=embed, file=discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME)
                )
            except discord.Forbidden:
                await self._mark_channel_unreachable(state)
                return
            except discord.HTTPException:
                _log.exception("Failed to post the living message for guild %s.", guild_id)
                return
            await self._mark_channel_reachable(state)
            await self._store(replace(self._states[guild_id], message_id=message.id))

    async def reanchor_channel_message(self, guild_id: int) -> None:
        """Move the living message back to the bottom of the channel.

        Best-effort deletes the current living message and posts a fresh one, so a
        plant that has scrolled out of view returns to where people are talking.
        Shares :meth:`refresh_channel_message`'s per-guild lock, so the two can
        never both find no tracked message and each post their own. Records or
        clears the unreachable-channel timestamp for exactly the same two causes
        as its sibling (see :meth:`_mark_channel_unreachable`).
        """
        async with self._message_lock(guild_id):
            state = self._states.get(guild_id)
            if state is None or state.channel_id is None:
                return
            channel = await self._text_channel(state.channel_id)
            if channel is None:
                await self._mark_channel_unreachable(state)
                return
            if state.message_id is not None:
                await self._delete_message(channel, state.message_id)
            png = await self._render_bytes(state.structure, state.moisture)
            try:
                message = await channel.send(
                    embed=self._embed_for(state),
                    file=discord.File(io.BytesIO(png), filename=PLANT_IMAGE_FILENAME),
                )
            except discord.Forbidden:
                await self._mark_channel_unreachable(state)
                return
            except discord.HTTPException:
                _log.exception("Failed to re-anchor the living message for guild %s.", guild_id)
                return
            await self._mark_channel_reachable(state)
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


async def require_guild(interaction: discord.Interaction) -> int | None:
    """Return the interaction's guild id, or reply with the DM error and ``None``.

    Every slash command is guild-only, since a server is what the plant belongs
    to. Shared so the three commands give the exact same ephemeral refusal
    instead of drifting apart over time.
    """
    if interaction.guild_id is not None:
        return interaction.guild_id
    await interaction.response.send_message(
        "Epiphyte only grows on servers, not in direct messages.",
        ephemeral=True,
    )
    return None


async def require_manage_channels(interaction: discord.Interaction) -> bool:
    """Return whether the invoker may configure the plant's channel; refuse if not.

    Only Manage Channels (or Administrator, which implies it) may bind or move
    the plant: unlike every other interaction with Epiphyte, this is a
    permanent, server-wide fixture rather than an ordinary member-facing
    action, so it is gated the same way a channel's own settings would be.
    Checked via :attr:`discord.Interaction.permissions` — the invoker's already
    -resolved permissions in the channel the command was run from — so this
    needs no extra API call and reflects the same permissions Discord itself
    used to decide whether to show the command at all.
    """
    permissions = interaction.permissions
    if permissions.manage_channels or permissions.administrator:
        return True
    await interaction.response.send_message(
        "Setting or moving the plant's channel needs the **Manage Channels** "
        "permission (or Administrator) — it's a permanent, server-wide fixture, "
        "not something every member can relocate.",
        ephemeral=True,
    )
    return False


@client.tree.command(
    name="plant",
    description="Show the plant right now, and bring it back into view.",
)
async def plant(interaction: discord.Interaction) -> None:
    """Render an immediate personal snapshot and re-anchor the living message.

    Growth is the metabolic tick's job now, so this never grows the plant. It
    renders the current state (moisture decayed to this moment, for display) as an
    ephemeral snapshot for the caller, and if the living channel message has
    scrolled out of view it quietly moves it back to the bottom. If the living
    message currently cannot be delivered — the bound channel is gone, or it's
    there but the bot can't post in it — this is also the one place that says
    so, with a wording matched to whichever of the two it currently is (see
    :meth:`EpiphyteClient._channel_trouble_message`): the living channel message
    itself can hardly speak up when it cannot even be posted.
    """
    guild_id = await require_guild(interaction)
    if guild_id is None:
        return
    state = client.state(guild_id)
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
    content = None
    if state.channel_unreachable_since is not None:
        content = await client._channel_trouble_message(state.channel_id)
    try:
        await interaction.response.send_message(
            content=content,
            embed=embed,
            file=discord.File(buffer, filename=PLANT_IMAGE_FILENAME),
            ephemeral=True,
        )
    except (discord.Forbidden, discord.HTTPException):
        _log.exception("Failed to send the /plant snapshot for guild %s.", guild_id)
        return

    if client.living_message_needs_reanchor(state):
        await client.reanchor_channel_message(guild_id)


class ConfirmGerminationView(discord.ui.View):
    """One-time confirmation gate before a guild's first, permanent plant germinates.

    Only ever shown from the ``client.state(guild_id) is None`` branch of
    ``/epiphyte-channel`` — rebinding an existing plant to a new channel never
    goes through this view, and never re-triggers this notice. Silently expires
    with no plant created if nobody presses the button.
    """

    def __init__(self, guild_id: int, channel: discord.TextChannel, author_id: int) -> None:
        super().__init__(timeout=180)
        self._guild_id = guild_id
        self._channel = channel
        self._author_id = author_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the person who ran the command may press the confirm button."""
        if interaction.user.id != self._author_id:
            await interaction.response.send_message(
                "Only the person who ran this command can confirm it.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        """Grey out the confirm button on the original message once the window expires."""
        self.confirm.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content=(
                        "This confirmation window has expired and nothing was created. "
                        "Run `/epiphyte-channel` again if you'd still like to plant one."
                    ),
                    view=self,
                )
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Understood — plant it", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Germinate the plant and post its living message in the chosen channel.

        If another confirmation already germinated this guild's plant while
        this view was open — two people confirming moments apart — this
        dialog no longer applies: it says so instead of silently resetting the
        plant that just came up (see :meth:`EpiphyteClient.germinate_plant`).
        """
        planted = await client.germinate_plant(self._guild_id, self._channel.id, time.time())
        self.stop()
        if not planted:
            await interaction.response.edit_message(
                content=(
                    "This server already has a plant now — another confirmation "
                    "must have gone through first. This dialog no longer applies; "
                    "run `/epiphyte-channel` again if you want to move the existing plant."
                ),
                view=None,
            )
            return
        state = client.state(self._guild_id)
        greeting = voice.germination_greeting(state.structure.seed) if state else ""
        await interaction.response.edit_message(
            content=(
                f"{greeting}\n\n"
                f"It lives in {self._channel.mention} from now on. Activity anywhere in "
                "this server waters it, and it will grow there on its own over time."
            ),
            view=None,
        )
        await client.refresh_channel_message(self._guild_id)


@client.tree.command(
    name="epiphyte-channel",
    description="Choose the channel the plant is displayed in.",
)
@app_commands.describe(channel="The text channel the plant's living message is posted in.")
async def epiphyte_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    """Bind the plant's display channel and post its living message there.

    Restricted to members with Manage Channels or Administrator (see
    :func:`require_manage_channels`) — both on a guild's very first binding
    and on every later rebind, since either can move or create this permanent,
    server-wide fixture. A guild's very first binding does not germinate on
    the spot: it shows a one-time persistence notice with a confirm button
    (see :class:`ConfirmGerminationView`) so nobody creates a permanent plant
    by accident. Rebinding an already-germinated plant to a new channel needs
    no such confirmation and proceeds immediately, as before.
    """
    guild_id = await require_guild(interaction)
    if guild_id is None:
        return
    if not await require_manage_channels(interaction):
        return

    if client.state(guild_id) is None:
        view = ConfirmGerminationView(guild_id, channel, interaction.user.id)
        await interaction.response.send_message(
            "🌱 This server doesn't have a plant yet. Starting one here creates "
            "**one permanent plant tied to this server's id** — every message sent "
            "anywhere in the server waters it, and it grows into a shape drawn from "
            "its own history over time.\n\n"
            "Kicking the bot and re-inviting it later does **not** reset it: the "
            "state lives independently of the bot's membership, so the plant just "
            "picks up where it left off. There is deliberately no delete or reset "
            "command.\n\n"
            f"Plant it in {channel.mention}?",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()
        return

    previous = client.state(guild_id)
    await client.set_channel(guild_id, channel.id)
    try:
        await interaction.response.send_message(
            f"🌱 The plant now lives in {channel.mention}. Activity anywhere in this "
            "server waters it, and it will grow there on its own over time.",
            ephemeral=True,
        )
    except (discord.Forbidden, discord.HTTPException):
        _log.exception("Failed to confirm channel binding for guild %s.", guild_id)

    # If the plant moved channels, remove the stale living message it left behind.
    if (
        previous is not None
        and previous.message_id is not None
        and previous.channel_id not in (None, channel.id)
    ):
        await client._remove_stale_message(previous.channel_id, previous.message_id)
    # Post (or refresh) the living message in the now-current channel.
    await client.refresh_channel_message(guild_id)


@client.tree.command(
    name="help",
    description="Explain what Epiphyte is and what its commands do.",
)
async def help_command(interaction: discord.Interaction) -> None:
    """Send a private, paginated explanation of the project's mechanic and commands."""
    guild_id = await require_guild(interaction)
    if guild_id is None:
        return
    pages = build_help_pages()
    view = HelpView(pages, interaction.user.id)
    try:
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
        view.message = await interaction.original_response()
    except (discord.Forbidden, discord.HTTPException):
        _log.exception("Failed to send the /help embed for guild %s.", guild_id)


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
