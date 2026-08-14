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

Phase 17 adds a fifth, and the quietest: time spent together in voice channels.
``on_voice_state_update`` — like every event above, a standard gateway event,
and already covered by ``discord.Intents.default()``, which enables
``voice_states`` (only ``members``, ``presences`` and ``message_content`` are
privileged, and all three stay off) — tracks who is *audibly* in each voice
channel, and time only accrues while at least ``structure.VOICE_MIN_AUDIBLE``
people are audible in the same one, so idling alone earns nothing. Each
``structure.VOICE_CREDIT_SECONDS`` of that shared time becomes one credit
through the same per-person diminishing-returns window watering uses. The
resulting reading (``_voice_activity``, read the same way author breadth and
reaction warmth are) never reaches ``structure.grow`` at all: it is handed to
``render.render``, where it draws the plant's root system and thickens its trunk
base. That is what makes it independent of breadth, rhythm and thread depth by
construction rather than by calibration — it shares no term with any of them.

Phase 19 adds no signal at all, and is the first phase that does not: it adds a
second *picture*. ``advance_life`` folds each tick into its calendar year's
record (``_record_year``) — the observed ticks, the vitality they ran at, and the
wood that tick's dieback killed — because none of the tables above reach back
further than weeks and a tree ring needs a whole finished year. Once a year, for
one day, ``_cross_section`` hands those finished years to ``render.render_rings``
and the living message shows the inside of the trunk instead of the plant. The
window needs no stored anniversary: the current year's own tick count is how long
ago that year turned. Nothing here touches growth, moisture or any signal — it is
the same data the plant already lived through, read backward.

Phase 20 adds the smallest thing in the whole project, and adds no signal
either: the wind. ``on_typing`` — the highest-frequency event here, and, like
all of the above, a standard non-privileged one — writes a single timestamp per
guild, and ``_wind`` turns it into a bool the renderer leans the crown by while
it lasts. Nothing is stored, nothing accumulates, nothing is pruned, and no
render happens that was not going to happen anyway: a gust only shows in the
heartbeat, a ``/plant`` snapshot or a re-anchor that fell inside it. It is the
plant's weather, not its life.

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
import datetime
import io
import logging
import math
import os
import random
import sqlite3
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

#: Most distinct threads one guild's ``_thread_activity`` cache (and the
#: matching rows in storage) will hold onto at once. Every other per-guild
#: cache is naturally bounded — author/reactor/voice presence by how many
#: genuine Discord accounts have shown up recently, daily_activity by a fixed
#: number of calendar-day buckets — but a thread id is free for one member to
#: mint: ``on_thread_create`` fires for every thread regardless of whether it
#: will ever clear ``structure.thread_qualifies``. Once a guild is at the
#: ceiling, a brand-new thread is simply not recorded until
#: ``_guild_thread_depth``'s once-a-tick pruning ages an old one out — the
#: same trade :data:`structure.THREAD_RECENCY_SECONDS` already makes for
#: staleness, just also bounding count. Far above
#: :data:`structure.THREAD_DEPTH_SATURATION_THREADS` (3), so no guild's
#: genuine thread habit is ever the thing that hits it.
MAX_TRACKED_THREADS_PER_GUILD = 300

#: Seconds in a whole day — the bucket size structure.day_bucket() groups
#: messages into for structure.temporal_rhythm().
DAY_SECONDS = 24 * 60 * 60

#: How many ticks after a calendar year turns the plant shows its cross-section
#: instead of itself. Twenty-four — one real day at one tick an hour.
#:
#: This constant is also the whole trigger, and it needs no stored anniversary
#: date to be one: ``yearly_ring`` counts the ticks observed in each year, so the
#: current year's count *is* how long ago that year began, and a window defined
#: as "while that count is still small" opens exactly once per year and closes by
#: itself. Nothing has to be persisted to remember whether the cross-section has
#: already been shown — the same "the state is the key" property the plant's
#: words rely on (see ``CLAUDE.md``, "Tick-Stabilität").
#:
#: A bot that was down when the year turned shows it late rather than not at all,
#: because the count starts at the first tick actually observed. That is the
#: deliberate trade: the record is worth more shown a week late than missed for a
#: year. A day is long enough that nobody who opens the server that day misses
#: it, and short enough that it never becomes the plant's normal face.
RING_DISPLAY_TICKS = 24

#: Attachment filename referenced by the embed's image.
PLANT_IMAGE_FILENAME = "plant.png"

#: Nord accent used for the /help embeds. Operational surfaces hold one fixed
#: colour on purpose: unlike the living message, they are not a readout of
#: anything, and somebody reading them wants an explanation, not a mood.
HELP_EMBED_COLOR = presentation.PLAIN_ACCENT

#: Project repository, credited once in /help.
REPO_URL = "https://github.com/timur-manjosov/epiphyte"

#: How long ``/plant``'s readings toggle stays live before greying itself out.
#: The same window ``/help``'s pagination uses, and for the same reason: long
#: enough to read the panel and turn it back over, far short of the fifteen
#: minutes after which Discord stops accepting edits to the response at all.
PLANT_VIEW_TIMEOUT_SECONDS = 180

#: Minimum spacing between one person's ``/plant`` calls. Its most expensive path
#: (``reanchor_channel_message``: delete + render + repost + a full-state write)
#: is otherwise callable in as tight a loop as Discord's own rate limit allows,
#: with nothing else in the bot slowing it down. Keyed on the user alone, not
#: per guild: every guild's writes still funnel through one shared, process-wide
#: database lock, so a per-guild cooldown would still let one person hammer that
#: shared lock by round-robining the same command across several guilds.
PLANT_COMMAND_COOLDOWN_SECONDS = 5.0

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


@dataclass
class VoiceSession:
    """Who is currently audible in one voice channel, and since when.

    ``audible`` holds the user ids that pass :func:`structure.voice_is_audible`
    right now; ``since`` is the moment that set last changed (or was last
    settled), so the interval between then and now is one stretch during which
    the room's headcount was constant — which is exactly what
    :func:`structure.shared_voice_seconds` needs to judge.

    Kept in memory only, like :class:`WateringWindow`. A restart therefore
    forgets any call in progress and starts counting again from the next voice
    event; against a week-long presence half-life that loses at most one
    session's fragment, and rebuilding it would mean reading the guild's voice
    channel membership on startup, which is a good deal more machinery than the
    inaccuracy is worth.
    """

    audible: set[int]
    since: float


def _audible_channel_id(state: discord.VoiceState, afk_channel_id: int | None) -> int | None:
    """Return the voice channel this state counts as audibly present in, else ``None``.

    The whole judgement is :func:`structure.voice_is_audible`'s; this only maps
    Discord's four separate flags onto its two. Each pair is OR'd because the
    self-set and the server-set flag mean the same thing here — someone muted by
    a moderator contributes exactly as much to a conversation as someone who
    muted themselves, which is nothing.
    """
    channel = state.channel
    if channel is None:
        return None
    audible = structure.voice_is_audible(
        connected=True,
        muted=state.mute or state.self_mute,
        deafened=state.deaf or state.self_deaf,
        in_afk_channel=afk_channel_id is not None and channel.id == afk_channel_id,
    )
    return channel.id if audible else None


def _pour(panel: presentation.Panel) -> discord.Embed:
    """Turn a composed :class:`presentation.Panel` into the Discord object it describes.

    The only function in this module that knows what an embed is. Every decision
    worth making — the accent colour, which instruments appear, whether the picture
    leads or accompanies, the footer — was already made in :mod:`presentation` as a
    pure function of the plant's state, so it is testable without Discord; this is
    the pour and nothing else. Shared by both panels, which is what guarantees the
    two faces of ``/plant`` differ only in what :mod:`presentation` decided they
    differ in.
    """
    embed = discord.Embed(title=panel.title, description=panel.body, color=panel.accent)
    for field in panel.fields:
        embed.add_field(name=field.name, value=field.value, inline=True)
    if panel.image is presentation.ImagePlacement.THUMBNAIL:
        embed.set_thumbnail(url=f"attachment://{PLANT_IMAGE_FILENAME}")
    else:
        embed.set_image(url=f"attachment://{PLANT_IMAGE_FILENAME}")
    embed.set_footer(text=panel.footer)
    return embed


def build_plant_embed(
    moisture_value: float,
    plant: structure.Structure,
    rings: tuple[structure.Ring, ...] = (),
) -> discord.Embed:
    """Build the ambient embed: the full-size plant, and what it has to say.

    This is what the living channel message wears on every heartbeat, and what
    ``/plant`` opens on. It carries no instrument row — see
    :func:`presentation.compose` for why, and for the single exception (the
    once-a-year cross-section) that keeps one.

    ``rings`` is non-empty only during that window, in which the attached image is
    the plant's cross-section rather than the plant (see
    :meth:`EpiphyteClient._cross_section`); the frame that goes around it is
    :mod:`presentation`'s decision as usual, not this function's.
    """
    return _pour(presentation.compose(plant, moisture_value, TICK_INTERVAL_SECONDS, rings))


def build_instrument_embed(
    moisture_value: float,
    plant: structure.Structure,
    rings: tuple[structure.Ring, ...] = (),
) -> discord.Embed:
    """Build the readings embed: the same plant, measured rather than listened to.

    Only ever reached from the button on ``/plant``'s ephemeral response — the
    living channel message has no path to this function at all, by design. Takes
    the same arguments as :func:`build_plant_embed` and is meant to be called
    beside it, from one reading of the state, so the readings describe the same
    instant as the picture they are attached to.
    """
    return _pour(
        presentation.compose_instruments(plant, moisture_value, TICK_INTERVAL_SECONDS, rings)
    )


def build_help_pages() -> list[discord.Embed]:
    """Build the /help embeds, one per page, in display order.

    Written as a short essay about the project rather than as a manual for it: the
    thesis first, then what the plant is actually reading, then the three commands,
    then the things that arrive on their own, then what is permanent. That order is
    the point — someone who stops after page one should have understood what
    Epiphyte *is*, and someone who reads to the end should know everything it does.

    The register is deliberately not the plant's. The persona bible puts ``/help``
    on the plain side of its spoken/plain line, and it stays there: a reference
    page has to be legible under a moderator's thumb, and a diary voice would bury
    the one sentence they came here for. "Crafted" here means the narrator is
    warm and specific, never that the plant is talking.

    Everything asserted below is checked against reality by
    ``tests/test_bot.py``'s help-accuracy tests: the commands and their arguments
    against the live command tree, the permission gate against the function that
    enforces it, and the promised readings against a real readings panel. The cited
    durations are computed from :mod:`moisture`'s own constants rather than restated
    as free-standing numbers, so a future recalibration keeps this text honest
    without a separate edit. The two places where prose beat derivation — "a day"
    and "half of the one before it", which no formatter turns into readable
    English — are literals whose constants are asserted directly, so a
    recalibration fails a test instead of quietly lying. :class:`HelpView` pages
    through the result.
    """
    tick_hours = TICK_INTERVAL_SECONDS // 3600
    tick_phrase = "once an hour" if tick_hours == 1 else f"once every {tick_hours} hours"
    wither_days = round(3 * moisture.DEFAULT_HALF_LIFE_SECONDS / (24 * 60 * 60))
    window_hours = round(moisture.WATERING_WINDOW_SECONDS / 3600)
    window_phrase = "a day" if window_hours == 24 else f"{window_hours} hours"
    wind_seconds = round(structure.WIND_LINGER_SECONDS)
    wind_phrase = "a minute and a half" if wind_seconds == 90 else f"{wind_seconds} seconds"

    overview = discord.Embed(
        title="🌱 Epiphyte",
        description=(
            "One server. One plant. One measure of how alive the place is, "
            "accumulating for as long as the server lasts.\n\n"
            "Every message sent anywhere here waters it. Silence dries it out — "
            f"about {wither_days} days of real quiet takes it from thriving down to "
            f"withered. It grows on its own roughly {tick_phrase}, but only while it "
            "has the moisture to afford the step, so a large plant is the record of "
            "weeks of genuine life rather than of one loud evening.\n\n"
            "What has grown, stays grown. The plant is not a readout of this "
            "afternoon; it is the shape its whole history has left behind, and no "
            "two servers end up with the same one.\n\n"
            "None of it is a score. There is no leaderboard, nothing to configure, "
            "and nothing that rewards trying to work at it. The plant is simply "
            "honest, which is occasionally uncomfortable and entirely the point."
        ),
        color=HELP_EMBED_COLOR,
    )

    signals = discord.Embed(
        title="What It Reads",
        description=(
            "The plant is not a moisture gauge with leaves on it. Six readings of "
            "this server's life shape six different parts of its body, and not one "
            "of them can be manufactured by a single person working at it alone.\n\n"
            "**Messages** water it, with steeply diminishing returns per person: "
            f"within {window_phrase}, each further message from the same person is "
            "worth half of the one before it. Ten people saying one thing each is "
            "worth far more than one person saying ten.\n"
            "**How many different people** speak decides how broadly the crown "
            "branches. A room with one voice in it grows narrow.\n"
            "**How evenly** activity falls across the weeks decides how symmetrical "
            "it grows. Bursts make knotted wood; steadiness makes calm wood.\n"
            "**Reactions** decide how richly it flowers — counted per person, and "
            "never counted at all for reacting to yourself.\n"
            "**Threads** that genuinely hold several people for a while decide how "
            "deep the branching runs before it stops.\n"
            "**Shared voice time** — two or more people audible in a channel "
            "together — feeds the roots and thickens the base of the trunk. Sitting "
            "alone in a voice channel is worth exactly nothing.\n\n"
            "Epiphyte never reads what anybody writes. It cannot: it runs without "
            "the permissions that would let it, and only ever learns that a message "
            "happened."
        ),
        color=HELP_EMBED_COLOR,
    )

    commands_page = discord.Embed(
        title="Commands",
        description=(
            "Three, and there will not be more. Everything else the plant does, it "
            "does by living.\n\n"
            "**`/epiphyte-channel <channel>`**\n"
            "Chooses the channel the plant is displayed in, and moves it there if it "
            "already lives somewhere else. Needs **Manage Channels** — a plant is a "
            "permanent, server-wide fixture, not something any member should be able "
            "to relocate. A server's first use asks for confirmation before anything "
            "germinates.\n\n"
            "**`/plant`**\n"
            "A private look at the plant as it stands this second, visible only to "
            "you. A button on that reply turns it over and shows every reading "
            "behind the picture — moisture, stage, age, growing tips, and whatever "
            "else this particular plant currently has to measure. Running it also "
            "nudges the living message back to the bottom of its channel if the "
            "conversation has buried it.\n\n"
            "**`/help`**\n"
            "This."
        ),
        color=HELP_EMBED_COLOR,
    )

    on_its_own_time = discord.Embed(
        title="On Its Own Time",
        description=(
            "Some of what the plant does cannot be asked for — only earned, and then "
            "waited out.\n\n"
            "It flowers once it has banked enough sustained health to afford it, sets "
            "seed if that flowering lasts, and — rarely, and only on an old and large "
            "body — comes to carry a second small plant riding on one of its limbs. "
            "That last one is what the project is named after.\n\n"
            "A deep enough drought kills wood outright. That wood is never cleared "
            "away and never comes back, so a plant that has been through a bad month "
            "goes on saying so for the rest of its life. A drought that goes on long "
            "enough takes all of it, and a successor germinates in its place carrying "
            "a mutated version of the same genome — recognisably related, and not the "
            "same individual.\n\n"
            "Once a calendar year has finished, the plant spends a single day showing "
            "a cross-section of its trunk instead of itself: one ring per completed "
            "year, read from the middle outward. Wide and dark where the server was "
            "alive, thin and pale where it was quiet, grey where a drought cost it "
            "wood. It comes around by itself, like everything else here.\n\n"
            "And when somebody is typing right now, the air moves a little — for "
            f"{wind_phrase} after the last keystroke, and then it stands still again. "
            "That one means nothing at all: it is weather rather than a measurement, "
            "stored nowhere and gone on the next restart."
        ),
        color=HELP_EMBED_COLOR,
    )

    persistence = discord.Embed(
        title="Persistence & Permanence",
        description=(
            "A server's plant lasts as long as the server does. Removing the bot and "
            "inviting it back later resets **nothing**: the state does not live in "
            "the bot's membership, so the plant picks up exactly where it left off — "
            "several days drier, and otherwise unchanged.\n\n"
            "There is deliberately no delete command and no reset command. Adding one "
            "would turn kicking and re-adding the bot into a way to erase a bad "
            "month, and a record you can erase is not a record.\n\n"
            "Every server's plant is its own, grown from its own history alone. "
            "Nothing here is shared between servers, ranked against them, or "
            "compared to them."
        ),
        color=HELP_EMBED_COLOR,
    )

    pages = [overview, signals, commands_page, on_its_own_time, persistence]
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


#: Button label while the plant is on show — what pressing it will reveal.
READINGS_LABEL = "Readings"
#: Button label while the readings are on show — what pressing it will bring back.
PLANT_LABEL = "The plant"


class PlantSnapshotView(discord.ui.View):
    """The one button in the project: turn ``/plant``'s reply over and back.

    Both faces are composed once, up front, from a single reading of the guild's
    state, and this view only chooses which of the two is currently displayed.
    That is deliberate on two counts. The readings can never disagree with the
    picture beside them, because both describe the same instant rather than the
    instant each was last asked for. And the toggle stays honest about what it is:
    a way of looking at one snapshot, not a live gauge that keeps ticking while
    somebody stares at it — for that, the plant is in its channel, growing.

    Nothing here is stored anywhere. Each ``/plant`` gets its own view object
    bound to its own ephemeral reply, so two people running the command seconds
    apart — or one person running it twice — share no state at all: neither
    invocation can move the other's message, and neither leaves anything behind
    once it times out. This is why a toggle does not count as configuration under
    the surface-minimalism rule: it changes nothing for the next viewer, nothing
    for the living channel message, and nothing for the next invocation.
    """

    def __init__(
        self, plant_embed: discord.Embed, readings_embed: discord.Embed, author_id: int
    ) -> None:
        super().__init__(timeout=PLANT_VIEW_TIMEOUT_SECONDS)
        self._faces = (plant_embed, readings_embed)
        self._showing_readings = False
        self._author_id = author_id
        self.message: discord.Message | None = None
        self._update_button()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the person who ran ``/plant`` may turn this snapshot over."""
        if interaction.user.id != self._author_id:
            await interaction.response.send_message(
                "Only the person who ran `/plant` can use this button.", ephemeral=True
            )
            return False
        return True

    @property
    def embed(self) -> discord.Embed:
        """Whichever face is currently on show."""
        return self._faces[1 if self._showing_readings else 0]

    def _update_button(self) -> None:
        """Label the button with what it will show, never with what is already shown."""
        self.toggle.label = PLANT_LABEL if self._showing_readings else READINGS_LABEL

    async def on_timeout(self) -> None:
        """Grey the button out on the original reply instead of leaving it dead-but-clickable."""
        self.toggle.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label=READINGS_LABEL, style=discord.ButtonStyle.secondary)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Swap the two faces in place.

        Edits only the embed: the rendered PNG is already attached and both faces
        reference it by the same ``attachment://`` name, so turning the message
        over costs no render and no upload — one of them just puts it in the
        thumbnail slot instead of the image slot.
        """
        self._showing_readings = not self._showing_readings
        self._update_button()
        await interaction.response.edit_message(embed=self.embed, view=self)


class EpiphyteClient(discord.Client):
    """Discord client with its own command tree (slash commands only).

    Uses the default intents exclusively: the bot only needs to know *that* a
    message arrived, never *what* it said. That set already includes
    ``voice_states``, which Phase 17 needs — ``Intents.default()`` is every
    intent except the three privileged ones (``members``, ``presences``,
    ``message_content``), all of which stay off, so no phase so far has had to
    ask for a new intent and none of them is gated behind Discord's
    verification. Per-guild plant state is loaded from SQLite on startup and
    written back on every change; the per-person watering windows are kept in
    memory. An APScheduler job drives the metabolic tick.
    """

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        #: The one connection reserved for operations that are not guild-scoped:
        #: startup's ``load_all_*``, the one-time command-cleanup flag, and
        #: ``VACUUM`` (see :meth:`_reclaim_after_reseed`) — all of which either
        #: run before any guild has its own connection open, or inherently touch
        #: the whole file rather than one guild's rows. Every ordinary guild
        #: write instead goes through its own connection; see
        #: :meth:`_guild_storage`.
        self._storage: storage.Storage | None = None
        #: The on-disk path :attr:`_storage` was opened against, remembered so
        #: :meth:`_guild_storage` can open each guild's own connection to the
        #: same file. ``None`` until :meth:`setup_hook` runs, mirroring
        #: :attr:`_storage` itself.
        self._storage_path: str | None = None
        #: Per guild: that guild's own database connection, opened lazily on
        #: first use and cached for the rest of the process's life. See
        #: :meth:`_guild_storage`.
        self._guild_storages: dict[int, storage.Storage] = {}
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
        #: weeks (see storage.py's module docstring). Each guild's thread count
        #: is capped at ``MAX_TRACKED_THREADS_PER_GUILD``.
        self._thread_activity: dict[int, dict[int, dict[int, tuple[int, float, float]]]] = {}
        #: Per guild, per person: (presence weight, last_seen) earned by genuine
        #: shared voice time. Mirrors ``self._author_presence`` exactly, just fed
        #: from voice credits rather than messages; feeds ``render`` (not
        #: ``structure.grow``) via ``_voice_activity``.
        self._voice_presence: dict[int, dict[int, tuple[float, float]]] = {}
        #: Per-person diminishing-returns window for voice credits, kept apart
        #: from the message and reaction windows for the same reason those two
        #: are kept apart from each other: talking, posting and reacting are
        #: separate actions, each with its own curve.
        self._voice_windows: dict[tuple[int, int], WateringWindow] = {}
        #: Per guild, per voice channel: who is audible there and since when; see
        #: ``VoiceSession`` and ``_settle_voice_channel``.
        self._voice_sessions: dict[int, dict[int, VoiceSession]] = {}
        #: Per (guild, person): shared voice seconds accrued but not yet worth a
        #: whole credit, carried forward so several short calls add up the same
        #: as one long one (see ``structure.voice_credits``).
        self._voice_seconds: dict[tuple[int, int], float] = {}
        #: Per guild: when somebody in it was last typing. One float per guild
        #: with a plant, overwritten in place — the smallest piece of state in
        #: this class and the only one that is never persisted, never decayed and
        #: never read by anything but the renderer. A restart forgets it, which is
        #: the correct lifetime for weather; see ``on_typing`` and ``_wind``.
        self._typing: dict[int, float] = {}
        #: Per guild, per calendar year: that year's accumulated record. The only
        #: thing here that reaches back further than weeks, and the only reason
        #: the cross-section can exist at all; see ``_record_year``. Never feeds
        #: growth — ``advance_life`` writes to it and never reads it.
        self._yearly: dict[int, dict[int, structure.YearRecord]] = {}
        self._message_locks: dict[int, asyncio.Lock] = {}
        self._rebirth_locks: dict[int, asyncio.Lock] = {}
        #: Per guild: the lock guarding that guild's own connection in
        #: :attr:`_guild_storages`, mirroring :attr:`_message_locks` and
        #: :attr:`_rebirth_locks`. See :meth:`_guild_db_lock`.
        self._db_locks: dict[int, asyncio.Lock] = {}
        #: Guards :attr:`_storage`, the one connection several guilds' worth of
        #: unrelated code can still reach concurrently (startup, and
        #: :meth:`_reclaim_after_reseed`'s ``VACUUM``) — a single
        #: ``sqlite3.Connection`` may only be touched by one thread at a time.
        self._db_lock = asyncio.Lock()
        self._presence_index = 0
        self._scheduler: AsyncIOScheduler | None = None

    async def setup_hook(self) -> None:
        """Open the database, load states, sync commands, and start the tick.

        Commands are synced globally, and *only* globally — never permanently to
        any individual guild. A guild-specific registration and the global one
        are two distinct entries to Discord even when they share a name, so a
        guild that keeps a permanent guild-specific copy shows every command
        twice as soon as global propagation (which can take Discord up to an
        hour) reaches it too. If ``EPIPHYTE_GUILD_ID`` is set, this also clears
        any guild-specific commands still registered there from an older deploy
        that synced to it directly, for exactly that reason —
        ``clear_commands(guild=...)`` only drops that guild's own copy from the
        local tree and never touches the global one, so the ``sync()`` below is
        unaffected. Every other guild that picked up a permanent copy from a
        past deploy is swept once, on the first ready, by
        :meth:`_clear_guild_command_duplicates`. The metabolic tick's first beat
        is one interval away, by when the bot is ready.
        """
        self._storage_path = storage.DEFAULT_DB_PATH
        self._storage = storage.Storage(self._storage_path)
        self._states = self._storage.load_all()
        self._author_presence = self._storage.load_all_author_presence()
        self._daily_activity = self._storage.load_all_daily_activity()
        self._reactor_presence = self._storage.load_all_reactor_presence()
        self._thread_activity = self._storage.load_all_thread_activity()
        self._voice_presence = self._storage.load_all_voice_presence()
        self._yearly = self._storage.load_all_yearly_rings()

        guild_id = os.getenv(GUILD_ENV)
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
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
        """Shut down cleanly: stop the presence loop, the scheduler, and every
        database connection — the shared one and each guild's own."""
        if self._rotate_presence.is_running():
            self._rotate_presence.cancel()
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._storage is not None:
            self._storage.close()
        for guild_storage in self._guild_storages.values():
            guild_storage.close()
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

    def _rebirth_lock(self, guild_id: int) -> asyncio.Lock:
        """Return the guild's death-to-rebirth lock, creating it on first use.

        Serializes the successor-germination sequence in :meth:`advance_life`
        (store the new generation, then wipe the old one's presence tables)
        against :meth:`_water_author_presence`, :meth:`_water_reactor_presence`
        and :meth:`_water_voice_presence` — the three writers of exactly the
        tables that sequence clears. Without this, a presence event for the
        same guild can land in the gap between the successor becoming the
        guild's current state and its predecessor's tables actually being
        wiped: the write and the clear both touch a table keyed only by
        ``guild_id``, so whichever runs last silently erases the other's
        effect, either losing a genuine contribution to the new generation or
        leaving a stale row the clear meant to remove. Held for the sequence's
        whole duration rather than per storage call, mirroring
        :meth:`_message_lock`, so nothing in between can observe a
        half-transitioned guild.
        """
        lock = self._rebirth_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._rebirth_locks[guild_id] = lock
        return lock

    def _guild_storage(self, guild_id: int) -> storage.Storage | None:
        """Return the guild's own database connection, opening it on first use.

        Every guild-scoped write and load used to go through the single
        connection in :attr:`_storage`, serialized end to end by one
        process-wide lock (:attr:`_db_lock`): a guild flooding the bot with
        messages queued sustained write pressure that every *other* guild's
        waterings, ticks and command handlers had to wait behind, even though
        they touch entirely different rows. Giving each guild its own
        ``sqlite3.Connection`` to the same on-disk file removes that
        cross-guild queueing: SQLite's own WAL-mode locking then serializes
        concurrent writers at the file level — held only for the few
        milliseconds an individual commit takes — instead of a Python lock
        held across whichever guild happens to be flooding.

        Returns ``None`` before :meth:`setup_hook` has opened the database,
        mirroring :attr:`_storage`'s own guard — callers already check that the
        same way (``if self._storage is not None:``). Safe to call unlocked:
        the get-or-create body below has no ``await`` in it, so — exactly like
        :meth:`_message_lock` and :meth:`_rebirth_lock` — asyncio can never
        switch to another task in the middle of it, and two callers racing for
        the same never-before-seen guild can never each open and cache their
        own separate connection.

        Deliberately not dispatched through :func:`asyncio.to_thread`, even
        though opening a connection is blocking I/O: doing so would reopen
        exactly the race the paragraph above closes (two callers could then
        both pass the cache-miss check before either finishes opening one).
        The cost this trades away is small and one-time — an existing guild's
        connection, to an already-WAL-mode file, opens in low single-digit
        milliseconds — paid at most once per guild for the life of the
        process, not on every call.
        """
        if self._storage_path is None:
            return None
        existing = self._guild_storages.get(guild_id)
        if existing is not None:
            return existing
        opened = storage.Storage(self._storage_path)
        self._guild_storages[guild_id] = opened
        return opened

    def _guild_db_lock(self, guild_id: int) -> asyncio.Lock:
        """Return the guild's own database lock, creating it on first use.

        Guards :meth:`_guild_storage`'s connection the same way :attr:`_db_lock`
        used to guard the single shared one: a ``sqlite3.Connection`` may only
        be touched by one thread at a time, and every guild-scoped call is
        dispatched through :func:`asyncio.to_thread`, which can land on a
        different worker thread each time. Being keyed per guild, not global,
        is the entire point — see :meth:`_guild_storage`.
        """
        lock = self._db_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._db_locks[guild_id] = lock
        return lock

    async def _store(self, state: storage.GuildState) -> None:
        """Update the in-memory cache and persist the state immediately.

        The in-memory cache is updated synchronously, before any ``await``, so
        every reader of :attr:`_states` sees it immediately; only the disk write
        (matching the Pillow render's off-loop pattern) trails behind, serialized
        through the guild's own :meth:`_guild_db_lock` against its own
        :meth:`_guild_storage` connection.
        """
        self._states[state.guild_id] = state
        guild_storage = self._guild_storage(state.guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(state.guild_id):
                await asyncio.to_thread(guild_storage.save, state)

    async def _store_watering(self, state: storage.GuildState) -> None:
        """Persist a watering, which moves the moisture but never the body.

        Kept apart from :meth:`_store` because this runs on every message, while an
        old plant's body is large enough that writing it out each time would cost
        real work in the one place the bot must stay cheap.
        """
        self._states[state.guild_id] = state
        guild_storage = self._guild_storage(state.guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(state.guild_id):
                await asyncio.to_thread(guild_storage.save_moisture, state)

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

        Holds the guild's :meth:`_message_lock`, the same one
        :meth:`refresh_channel_message` and :meth:`reanchor_channel_message` hold
        for their whole body: without it, a rebind racing an in-flight metabolic
        tick could complete while that tick is still awaiting Discord's response
        to a post in the *old* channel, so its own later write — which only
        patches in the freshly posted message id — would land on top of this
        method's already-stored new ``channel_id``, pairing a new channel with a
        message that was actually posted in the old one. The lock instead makes
        the two run one after the other, however they interleave: no in-flight
        post ever gets attributed to a channel it wasn't sent to.
        """
        async with self._message_lock(guild_id):
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

        Held under :meth:`_rebirth_lock` for its whole body, memory write and
        disk write alike, so this can never land in the gap :meth:`advance_life`
        opens between germinating a successor and wiping this very table — see
        that lock's docstring for the failure this closes.
        """
        async with self._rebirth_lock(guild_id):
            guild_presence = self._author_presence.setdefault(guild_id, {})
            weight, last_seen = guild_presence.get(author_id, (0.0, now))
            decayed = moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
            updated = moisture.water(decayed, amount)
            guild_presence[author_id] = (updated, now)
            guild_storage = self._guild_storage(guild_id)
            if guild_storage is not None:
                async with self._guild_db_lock(guild_id):
                    await asyncio.to_thread(
                        guild_storage.upsert_author_presence, guild_id, author_id, updated, now
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
        guild_storage = self._guild_storage(guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.increment_daily_activity, guild_id, bucket)

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

        Held under :meth:`_rebirth_lock` exactly like :meth:`_water_author_presence`,
        for the same reason: this writes ``reactor_presence``, one of the
        tables :meth:`advance_life`'s rebirth sequence clears.
        """
        async with self._rebirth_lock(guild_id):
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
            guild_storage = self._guild_storage(guild_id)
            if guild_storage is not None:
                async with self._guild_db_lock(guild_id):
                    await asyncio.to_thread(
                        guild_storage.upsert_reactor_presence, guild_id, reactor_id, updated, now
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
        guild_storage = self._guild_storage(guild_id)
        if stale and guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.delete_reactor_presence, guild_id, stale)
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
        guild_storage = self._guild_storage(guild_id)
        if stale and guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.delete_author_presence, guild_id, stale)
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
        guild_storage = self._guild_storage(guild_id)
        if stale and guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.prune_daily_activity, guild_id, window_start)
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

        A guild already holding :data:`MAX_TRACKED_THREADS_PER_GUILD` distinct
        threads silently drops activity for any *new* thread id — a thread
        already being tracked keeps updating normally, only the admission of a
        never-before-seen thread is refused. Minting fresh thread ids costs a
        flooder nothing, unlike every other cache this class keeps, so this is
        the one place that needs an explicit ceiling rather than relying on
        staleness pruning alone.
        """
        guild_threads = self._thread_activity.setdefault(guild_id, {})
        if thread_id not in guild_threads and len(guild_threads) >= MAX_TRACKED_THREADS_PER_GUILD:
            return
        thread_rows = guild_threads.setdefault(thread_id, {})
        count, first_seen, _ = thread_rows.get(author_id, (0, now, now))
        thread_rows[author_id] = (count + (1 if increment else 0), first_seen, now)
        guild_storage = self._guild_storage(guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(
                    guild_storage.upsert_thread_activity, guild_id, thread_id, author_id, now, increment
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
        guild_storage = self._guild_storage(guild_id)
        if stale_threads and guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.prune_thread_activity, guild_id, cutoff)

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

    # --- voice channels: the room nobody scrolling ever sees --------------------

    async def _water_voice_presence(self, guild_id: int, user_id: int, now: float) -> None:
        """Add one earned voice credit's anti-farmed amount to a person's presence weight.

        Mirrors :meth:`_water_reactor_presence` exactly, over its own window and
        its own table. The credit that gets us here already required company —
        :func:`structure.shared_voice_seconds` gives a lone occupant nothing —
        and this then applies the same per-person diminishing returns on top, so
        an afternoon spent in a call is worth a capped fraction of one person's
        daily share and real voice presence still costs several distinct real
        days, exactly as posting does.

        Held under :meth:`_rebirth_lock` exactly like :meth:`_water_author_presence`,
        for the same reason: this writes ``voice_presence``, one of the tables
        :meth:`advance_life`'s rebirth sequence clears.
        """
        async with self._rebirth_lock(guild_id):
            window = self._voice_windows.get((guild_id, user_id))
            start = window.window_start if window is not None else None
            count = window.count if window is not None else 0
            amount, new_start, new_count = moisture.next_watering(start, count, now)
            self._voice_windows[(guild_id, user_id)] = WateringWindow(new_start, new_count)

            guild_voices = self._voice_presence.setdefault(guild_id, {})
            weight, last_seen = guild_voices.get(user_id, (0.0, now))
            decayed = moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
            updated = moisture.water(decayed, amount)
            guild_voices[user_id] = (updated, now)
            guild_storage = self._guild_storage(guild_id)
            if guild_storage is not None:
                async with self._guild_db_lock(guild_id):
                    await asyncio.to_thread(
                        guild_storage.upsert_voice_presence, guild_id, user_id, updated, now
                    )

    async def _credit_voice_seconds(
        self, guild_id: int, user_id: int, seconds: float, now: float
    ) -> None:
        """Bank shared voice seconds for one person, spending whole credits as they land.

        The sub-credit remainder is carried forward (see
        :func:`structure.voice_credits`), so an evening of short calls is worth
        the same as one unbroken one of the same total length.
        """
        key = (guild_id, user_id)
        credits, leftover = structure.voice_credits(self._voice_seconds.get(key, 0.0) + seconds)
        self._voice_seconds[key] = leftover
        for _ in range(credits):
            await self._water_voice_presence(guild_id, user_id, now)

    async def _settle_voice_channel(self, guild_id: int, channel_id: int, now: float) -> None:
        """Credit everyone audible in one voice channel for the stretch since it last changed.

        The session's ``since`` is always the last moment its audible set changed
        or was settled, so that stretch had a constant headcount — which is what
        lets :func:`structure.shared_voice_seconds` judge the whole of it at
        once, rather than the caller having to integrate over a changing room.
        Always called *before* a membership change is applied, so the interval is
        judged by the headcount that actually held during it.
        """
        session = self._voice_sessions.get(guild_id, {}).get(channel_id)
        if session is None:
            return
        credited = structure.shared_voice_seconds(len(session.audible), now - session.since)
        session.since = now
        if credited <= 0.0:
            return
        for user_id in sorted(session.audible):
            await self._credit_voice_seconds(guild_id, user_id, credited, now)

    async def _settle_open_voice_sessions(self, now: float) -> None:
        """Settle every guild's open voice sessions, so a long unbroken call still counts.

        Voice state events only fire on *changes*, so a call nobody joins, leaves
        or mutes in for three hours would otherwise bank nothing until it ended.
        Running this once per metabolic tick bounds that lag to one heartbeat.
        """
        for guild_id, channels in list(self._voice_sessions.items()):
            for channel_id in list(channels):
                await self._settle_voice_channel(guild_id, channel_id, now)

    def _voice_activity(self, guild_id: int, now: float) -> float:
        """Return a guild's current voice-activity reading (a pure read, no writes).

        Deliberately reuses :func:`structure.author_breadth`, for the same reason
        :meth:`_guild_reaction_warmth` does: "how many distinct people cleared
        the presence floor, saturating at a modest count" is exactly the
        anti-clique property this needs, and there is nothing to gain from
        calibrating a third copy of it. All the voice-specific shaping lives in
        :func:`structure.root_spread` instead.

        Unlike :meth:`_guild_author_breadth` this neither prunes nor persists
        anything — the living message and ``/plant`` both read it on demand to
        render with, not only once per tick, so it must be safe to call at any
        time. Pruning is :meth:`_prune_voice_presence`'s job, once per tick.
        """
        guild_voices = self._voice_presence.get(guild_id, {})
        weights = [
            moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
            for weight, last_seen in guild_voices.values()
        ]
        return structure.author_breadth(weights)

    async def _prune_voice_presence(self, guild_id: int, now: float) -> None:
        """Drop voice-presence rows whose weight has decayed to nothing.

        The sweep :meth:`_guild_author_breadth` performs inline, kept separate
        here because the reading itself must stay side-effect free (see
        :meth:`_voice_activity`). Run once per metabolic tick, so the table stays
        bounded to people genuinely still around in voice.
        """
        guild_voices = self._voice_presence.get(guild_id, {})
        stale: list[int] = []
        for user_id, (weight, last_seen) in list(guild_voices.items()):
            decayed = moisture.decay(weight, now - last_seen, structure.AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
            if decayed < AUTHOR_PRESENCE_PRUNE_FLOOR:
                stale.append(user_id)
                del guild_voices[user_id]
        guild_storage = self._guild_storage(guild_id)
        if stale and guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.delete_voice_presence, guild_id, stale)

    async def _clear_voice_presence(self, guild_id: int) -> None:
        """Wipe a guild's voice presence, and any call in progress, on rebirth.

        Mirrors :meth:`_clear_author_presence` and :meth:`_clear_reactor_presence`:
        all three record *people currently around a particular plant*, which is
        this life's own to earn — unlike the daily-activity and thread tables,
        which record events a community produces and therefore outlive it. Roots
        make the distinction the most literal of the three: a successor cannot
        inherit its predecessor's root system, and as a single sprout it has no
        trunk to flare in any case.
        """
        self._voice_presence.pop(guild_id, None)
        self._voice_sessions.pop(guild_id, None)
        for key in [key for key in self._voice_seconds if key[0] == guild_id]:
            del self._voice_seconds[key]
        for key in [key for key in self._voice_windows if key[0] == guild_id]:
            del self._voice_windows[key]
        guild_storage = self._guild_storage(guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.clear_voice_presence, guild_id)

    # --- the record of finished years (the cross-section) ----------------------

    async def _record_year(
        self, guild_id: int, now: float, moisture_value: float, wood_lost: int
    ) -> None:
        """Fold this tick into its calendar year's running record.

        The one write in this class that is kept for years rather than weeks, and
        the reason is that nothing else is: the presence tables decay, the daily
        and thread tables are pruned to their own windows, and the plant's
        moisture is a single current value. A tree ring needs a whole finished
        year, so a year is accumulated a tick at a time while it happens — there
        is no way to reconstruct one afterwards from records nobody kept, and
        this deliberately never tries.

        ``moisture_value`` is the vitality the growth step actually ran at and
        ``wood_lost`` how many nodes that same step's dieback killed, so the
        record is a byproduct of the tick rather than a second measurement of it.
        The accumulation itself is one atomic upsert (see
        :meth:`storage.Storage.record_year_tick`): a restart or a crash on either
        side of a year boundary can lose at most the tick in flight, and can
        neither double-count a tick nor invent one.
        """
        year = structure.calendar_year(now)
        guild_years = self._yearly.setdefault(guild_id, {})
        record = guild_years.get(year)
        guild_years[year] = structure.YearRecord(
            year=year,
            ticks=(record.ticks if record else 0) + 1,
            moisture_sum=(record.moisture_sum if record else 0.0) + moisture_value,
            wood_lost=(record.wood_lost if record else 0) + wood_lost,
        )
        guild_storage = self._guild_storage(guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(
                    guild_storage.record_year_tick, guild_id, year, moisture_value, wood_lost
                )

    async def _clear_yearly_rings(self, guild_id: int) -> None:
        """Wipe a guild's year records when its successor germinates.

        Rings side with the three presence tables rather than with the
        daily-activity and thread counters, and the reason is more literal here
        than anywhere else: a cross-section is wood *this* trunk laid down, and no
        trunk can contain a year in which it did not exist. A successor begins
        with no rings and earns its first at the end of its first real year, the
        same way it begins with no crowd and no root system.
        """
        self._yearly.pop(guild_id, None)
        guild_storage = self._guild_storage(guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.clear_yearly_rings, guild_id)

    def _cross_section(self, guild_id: int, now: float) -> tuple[structure.Ring, ...]:
        """Return the rings to show right now, or empty for the rest of the year.

        The whole trigger, and it stores nothing to be one. The current year's
        ``ticks`` counts how many ticks of that year the bot has observed, so
        while it is still at or below :data:`RING_DISPLAY_TICKS` the year has
        only just turned — that is the window, it opens exactly once per calendar
        year, and it closes on its own. A plant with no finished year on record
        (a young one, or one whose germination year began too late to be
        measurable) yields an empty tuple and simply shows itself as usual: there
        is no partial, half-invented first ring, because a ring nobody could have
        measured would claim more history than the plant has.

        A pure read like :meth:`_voice_activity`, and for the same reason — the
        living message and ``/plant`` both call it outside the tick, so it must
        never write.
        """
        year = structure.calendar_year(now)
        records = self._yearly.get(guild_id, {})
        current = records.get(year)
        if current is None or current.ticks > RING_DISPLAY_TICKS:
            return ()
        return structure.rings(records.values(), year)

    # --- the weather (nothing is kept, nothing is measured) --------------------

    def _wind(self, guild_id: int, now: float) -> bool:
        """Whether the air around this guild's plant is currently moving.

        The judgement itself is :func:`structure.wind_is_stirring`'s; this only
        supplies the elapsed time from the one float :meth:`on_typing` keeps.
        A pure read, like :meth:`_voice_activity` and :meth:`_cross_section`, and
        this one has nothing it *could* write: there is no table, no decay and no
        window behind it. A guild nobody has typed in since the last restart has
        no entry at all, which reads as still air.
        """
        last = self._typing.get(guild_id)
        return structure.wind_is_stirring(None if last is None else now - last)

    async def _clear_author_presence(self, guild_id: int) -> None:
        """Wipe a guild's recorded voices when its successor germinates.

        Breadth is this life's own accumulated crowd, not the lineage's — like
        :class:`structure.LifeStats`, a new generation starts unheard and must
        earn its own again.
        """
        self._author_presence.pop(guild_id, None)
        guild_storage = self._guild_storage(guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.clear_author_presence, guild_id)

    async def _clear_reactor_presence(self, guild_id: int) -> None:
        """Wipe a guild's recorded reactors when its successor germinates.

        Mirrors :meth:`_clear_author_presence`: reaction warmth is this life's
        own accumulated crowd, not the lineage's.
        """
        self._reactor_presence.pop(guild_id, None)
        guild_storage = self._guild_storage(guild_id)
        if guild_storage is not None:
            async with self._guild_db_lock(guild_id):
                await asyncio.to_thread(guild_storage.clear_reactor_presence, guild_id)

    def _prune_watering_windows(self, now: float) -> None:
        """Drop watering windows whose window has fully elapsed.

        Without this, every (guild, user) pair that has ever watered would stay in
        memory for the bot's entire uptime — tracking everyone who ever has,
        instead of just who currently does. Run once per metabolic tick, since it
        already sweeps on a steady real-time interval.

        Purely a memory sweep, never a behaviour change: an elapsed window is one
        :func:`moisture.next_watering` would reset on its next use anyway, so
        dropping it here cannot hand anybody back a fresh full-strength watering
        they had not already earned by waiting. The voice and reaction windows
        are swept alongside the message ones for the same reason, together with
        any sub-credit voice fragment left over from a call that ended long ago.
        """
        for windows in (self._windows, self._voice_windows, self._reaction_windows):
            expired = [
                key
                for key, window in windows.items()
                if now - window.window_start >= moisture.WATERING_WINDOW_SECONDS
            ]
            for key in expired:
                del windows[key]
        for key in [
            key
            for key, seconds in self._voice_seconds.items()
            if seconds <= 0.0 and key not in self._voice_windows
        ]:
            del self._voice_seconds[key]

    async def _reclaim_after_reseed(self) -> None:
        """Run VACUUM after a generational reseed, off the event loop.

        A death-to-rebirth reseed is a naturally rare event (unlike per-message or
        per-tick writes), and exactly when a large gone structure blob's freed
        pages become worth returning to the OS. Runs on :attr:`_storage`, the one
        connection reserved for whole-file operations — unlike every guild-scoped
        write, ``VACUUM`` cannot be narrowed to one guild's own connection, since
        it rewrites the entire on-disk file.

        That makes this the one write in the whole class that can now
        legitimately collide with another guild's: any other guild's own
        connection (see :meth:`_guild_storage`) may be mid-write on the same
        file while this runs, where before every write funnelled through this
        same single connection and could never overlap with it. SQLite's own
        ``busy_timeout`` (:func:`sqlite3.connect`'s ``timeout`` argument,
        5 seconds by default and left at that default here) already retries
        for a few seconds before giving up, but a contended VACUUM losing
        that race raises ``sqlite3.OperationalError``
        rather than corrupting anything — caught and logged here rather than
        propagated, since reclaiming disk space is an optimization, not a
        correctness requirement: the next reseed gets another chance at it,
        and a plant's own state was already durably stored before this ever
        runs.
        """
        if self._storage is not None:
            async with self._db_lock:
                try:
                    await asyncio.to_thread(self._storage.vacuum)
                except sqlite3.OperationalError:
                    _log.exception("VACUUM skipped after reseed; will retry on the next one.")

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

        The store-then-wipe sequence below runs under :meth:`_rebirth_lock`, the
        same lock :meth:`_water_author_presence`, :meth:`_water_reactor_presence`
        and :meth:`_water_voice_presence` hold for their own whole bodies — see
        that lock's docstring for the race this closes between a presence event
        landing mid-sequence and the wipe meant to clear the generation it just
        wrote into.
        """
        state = self._states[guild_id]
        current = moisture.decay(state.moisture, now - state.last_update)

        if structure.is_dead(state.structure):
            dead_ticks = state.dead_ticks + 1
            if dead_ticks >= DEAD_PHASE_TICKS:
                successor = structure.germinate_successor(state.structure)
                async with self._rebirth_lock(guild_id):
                    await self._store(
                        replace(state, structure=successor, moisture=current,
                                last_update=now, dead_ticks=0)
                    )
                    await self._clear_author_presence(guild_id)
                    await self._clear_reactor_presence(guild_id)
                    await self._clear_voice_presence(guild_id)
                    await self._clear_yearly_rings(guild_id)
                    await self._reclaim_after_reseed()
            else:
                await self._store(replace(state, moisture=current, last_update=now, dead_ticks=dead_ticks))
            return

        genome = structure.genome_from_seed(state.structure.seed)
        breadth = await self._guild_author_breadth(guild_id, now)
        rhythm = await self._guild_rhythm(guild_id, now)
        reaction_warmth = await self._guild_reaction_warmth(guild_id, now)
        thread_depth = await self._guild_thread_depth(guild_id, now)
        # Voice activity is deliberately absent from this call: it drives the
        # root system in render.py and nothing in the growth model, which is what
        # makes it independent of the four values above by construction. Its
        # table is still swept here, where every other per-tick sweep happens.
        await self._prune_voice_presence(guild_id, now)
        grown = structure.grow(
            state.structure, genome, current, 1, breadth, rhythm, reaction_warmth, thread_depth
        )
        # Fold this step into its calendar year's record — the wood a ring will
        # eventually be drawn from. `wood_lost` is the dieback this very step
        # performed, read off the two bodies rather than re-derived from a second
        # drought threshold of its own, so a scar ring and the grey branch it
        # corresponds to are one event: see structure.rings(). Nothing read back
        # from this ever reaches growth.
        await self._record_year(
            guild_id,
            now,
            current,
            structure.dead_node_count(grown) - structure.dead_node_count(state.structure),
        )
        # Re-read rather than reuse the `state` snapshot from the top of this
        # method: the lookups, the prune and the year record above each await real
        # I/O, and a message's watering (water_plant, atomic in its own right — see
        # _store's docstring) can land in that window. Storing `current` — the
        # decay computed from the pre-watering snapshot — on top of that would
        # silently discard the watering. Decaying the *latest* moisture to
        # `now` instead folds it in when one landed, and is identical to
        # `current` when none did. The structure this tick grew still stands:
        # growth's pace was correctly decided by the moisture this tick began
        # with, not one a race happened to advance mid-computation.
        latest = self._states[guild_id]
        fresh_moisture = moisture.decay(latest.moisture, now - latest.last_update)
        await self._store(
            replace(latest, structure=grown, moisture=fresh_moisture, last_update=now, dead_ticks=0)
        )

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

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Track who is audibly in which voice channel, feeding the root system.

        Voice state updates are a standard, non-privileged gateway event, and
        ``discord.Intents.default()`` already enables ``voice_states`` — like
        every phase before it, this one adds no intent (see the class docstring).
        The event carries its own member payload, so none of this needs the
        privileged member cache either.

        This fires for joins, leaves, moves *and* mute/deafen toggles, which is
        exactly the set of changes that can make someone stop or start counting
        (see :func:`structure.voice_is_audible`). Both the channel someone left
        and the one they arrived in are settled *before* the change is applied,
        so each stretch of time is credited at the headcount that actually held
        during it. Someone who mutes themselves without moving therefore leaves
        the session exactly as if they had disconnected, and rejoins it when they
        unmute — it is the remaining audible headcount, not the number of people
        connected, that decides whether the next stretch counts at all.
        """
        if member.bot:
            return
        state = self.state(member.guild.id)
        if state is None or state.channel_id is None:
            return

        afk_channel_id = member.guild.afk_channel.id if member.guild.afk_channel else None
        was = _audible_channel_id(before, afk_channel_id)
        now_in = _audible_channel_id(after, afk_channel_id)
        if was == now_in:
            return  # nothing that bears on this signal changed

        now = time.time()
        channels = self._voice_sessions.setdefault(member.guild.id, {})
        if was is not None:
            await self._settle_voice_channel(member.guild.id, was, now)
            session = channels.get(was)
            if session is not None:
                session.audible.discard(member.id)
                if not session.audible:
                    del channels[was]
        if now_in is not None:
            await self._settle_voice_channel(member.guild.id, now_in, now)
            channels.setdefault(now_in, VoiceSession(audible=set(), since=now)).audible.add(member.id)

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

    async def on_typing(
        self,
        channel: discord.abc.Messageable,
        user: discord.User | discord.Member,
        when: datetime.datetime,
    ) -> None:
        """Note that somebody is typing in this guild, so the air moves for a moment.

        Typing is a standard, non-privileged gateway event — like every event
        above it, ``discord.Intents.default()`` already covers it, so this phase
        adds no intent either. It is also the highest-frequency event in the
        whole bot, which is why the handler is a single dictionary write of one
        float per guild: nothing accumulates, nothing is persisted, nothing is
        pruned, and somebody typing all afternoon costs exactly the same memory
        as somebody typing once. Deliberately: this is weather, and weather has
        no ledger.

        Guild-wide, like every other event here — ``CLAUDE.md``'s scope rule
        holds for this too, plant-wide rather than channel-wide. The bound
        channel is where the plant is shown, never a filter on what reaches it.

        ``when`` is Discord's own timestamp for the event; a local clock read is
        used instead, so this cannot disagree with the clock every render is
        judged against by however far the two have drifted. The distinction is
        seconds at most, but the whole effect is only ninety seconds long.
        """
        if user.bot:
            return
        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        state = self.state(guild.id)
        if state is None or state.channel_id is None:
            return
        self._typing[guild.id] = time.time()

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
        await self._settle_open_voice_sessions(now)
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

    async def _clear_guild_command_duplicates(self) -> None:
        """Once ever, strip every already-connected guild's permanent command copy.

        A past deploy gave every guild it saw — through a since-removed
        ``on_guild_join`` handler and a since-removed startup backfill — a
        permanent guild-specific copy of every command via ``copy_global_to`` +
        ``sync(guild=...)``. Those copies never expire on their own, and once
        this bot's ordinary global sync (``setup_hook``) also reaches a guild,
        Discord shows both: the same command listed twice. This clears the
        guild-specific copy the same way ``setup_hook`` already does for
        ``EPIPHYTE_GUILD_ID`` — ``clear_commands(guild=guild)`` only empties
        that guild's entry in the local tree, never the global one, so the
        follow-up ``sync(guild=guild)`` deletes Discord's guild-specific copy
        and leaves the single global registration standing. Run once, for every
        guild connected right now, and never again: :meth:`storage.Storage.
        guild_command_cleanup_done` makes this a true one-time migration,
        persisted in the database rather than in memory, so a container restart
        mid-sweep resumes as "already done" instead of repeating one Discord API
        call per guild forever. A guild that joins fresh after this has run
        never picked up a guild-specific copy in the first place, so it needs no
        sweep of its own.
        """
        if self._storage is None or self._storage.guild_command_cleanup_done():
            return
        for guild in self.guilds:
            self.tree.clear_commands(guild=guild)
            try:
                await self.tree.sync(guild=guild)
            except discord.HTTPException:
                _log.exception("Could not clear duplicate commands for guild %s.", guild.id)
        self._storage.mark_guild_command_cleanup_done()
        _log.info(
            "Cleared duplicate guild-specific commands for %d already-connected guild(s).",
            len(self.guilds),
        )

    async def on_ready(self) -> None:
        """Start the presence rotation and, once ever, sweep duplicate guild commands.

        ``on_ready`` can fire again on every reconnect, unlike ``setup_hook``, so
        the presence loop is only started if it is not already running; the
        sweep guards itself the same way, but durably (see
        :meth:`_clear_guild_command_duplicates`).
        """
        if not self._rotate_presence.is_running():
            self._rotate_presence.start()
        await self._clear_guild_command_duplicates()

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

    async def _render_bytes(
        self,
        plant: structure.Structure,
        moisture_value: float,
        voice_activity: float = 0.0,
        rings: tuple[structure.Ring, ...] = (),
        wind: bool = False,
    ) -> bytes:
        """Render the image the message currently calls for, off the event loop.

        Normally that is the plant: ``moisture_value`` is the vitality that
        modulates its look and ``voice_activity`` the guild's current voice
        reading, which modulates its root system the same way; the genome is
        recomputed from the seed so the render matches this individual. ``wind``
        is whether somebody is typing at this moment (see :meth:`_wind`) — the
        one argument that is not a reading of the server's life but of its
        weather, and the only one that will be different a minute from now.

        For the one day a year ``rings`` is non-empty (see
        :meth:`_cross_section`) it is the trunk's cross-section instead — a
        different picture from different inputs, not a variation on the plant.
        The two are alternatives rather than layers, which is why this chooses
        between two render functions rather than passing rings into one. Wind
        does not reach the cross-section, and could not mean anything there:
        wind moves a standing plant, and a cross-section is not one.
        """
        if rings:
            buffer = await asyncio.to_thread(render.render_rings, rings, plant.seed)
        else:
            genome = structure.genome_from_seed(plant.seed)
            buffer = await asyncio.to_thread(
                render.render, plant, moisture_value, genome, voice_activity, wind
            )
        return buffer.getvalue()

    def _embed_for(
        self, state: storage.GuildState, rings: tuple[structure.Ring, ...] = ()
    ) -> discord.Embed:
        """Build the living message's embed from a guild's current stored state."""
        return build_plant_embed(state.moisture, state.structure, rings)

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
            now = time.time()
            rings = self._cross_section(guild_id, now)
            png = await self._render_bytes(
                state.structure,
                state.moisture,
                self._voice_activity(guild_id, now),
                rings,
                self._wind(guild_id, now),
            )
            embed = self._embed_for(state, rings)

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
            now = time.time()
            rings = self._cross_section(guild_id, now)
            png = await self._render_bytes(
                state.structure,
                state.moisture,
                self._voice_activity(guild_id, now),
                rings,
                self._wind(guild_id, now),
            )
            try:
                message = await channel.send(
                    embed=self._embed_for(state, rings),
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
@app_commands.checks.cooldown(1, PLANT_COMMAND_COOLDOWN_SECONDS)
async def plant(interaction: discord.Interaction) -> None:
    """Render an immediate personal snapshot and re-anchor the living message.

    Growth is the metabolic tick's job now, so this never grows the plant. It
    renders the current state (moisture decayed to this moment, for display) as an
    ephemeral snapshot for the caller, opening on the same face the living channel
    message wears — the full-size plant and its own words — with a button that
    turns it over to every reading behind it (see :class:`PlantSnapshotView`).
    This is the only surface in the project where those readings appear at all:
    the living message is the plant, and somebody who wants the numbers has to
    ask. If the living channel message has
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
    # Deliberately the same cross-section reading the living message uses: on the
    # one day a year the record is on show, a snapshot that quietly showed the
    # plant instead would have the two surfaces disagreeing about what the server
    # is currently being shown.
    rings = client._cross_section(guild_id, now)
    png = await client._render_bytes(
        state.structure,
        display_moisture,
        client._voice_activity(guild_id, now),
        rings,
        client._wind(guild_id, now),
    )
    buffer = io.BytesIO(png)
    # Both faces from this one reading of the state, so the readings behind the
    # button describe exactly the moment the attached picture was rendered for.
    view = PlantSnapshotView(
        build_plant_embed(display_moisture, state.structure, rings),
        build_instrument_embed(display_moisture, state.structure, rings),
        author_id=interaction.user.id,
    )
    content = None
    if state.channel_unreachable_since is not None:
        content = await client._channel_trouble_message(state.channel_id)
    try:
        await interaction.response.send_message(
            content=content,
            embed=view.embed,
            file=discord.File(buffer, filename=PLANT_IMAGE_FILENAME),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()
    except (discord.Forbidden, discord.HTTPException):
        _log.exception("Failed to send the /plant snapshot for guild %s.", guild_id)
        return

    if client.living_message_needs_reanchor(state):
        await client.reanchor_channel_message(guild_id)


@plant.error
async def on_plant_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    """Answer a cooldown hit with a plain wait time instead of a silent failure.

    Without a local handler here, the cooldown check's ``CommandOnCooldown``
    would reach the command tree's default error handler, which only logs it —
    leaving the interaction unanswered and Discord showing the invoker a bare
    "This interaction failed" with no explanation. Registering this handler
    also takes the tree's own default handler out of the loop entirely (it
    defers to a command's own handler when one exists), so any other error
    still needs its own explicit log here to avoid going silently missing.

    The wait rounds up, not to the nearest second: someone caught right at the
    tail of the window (e.g. 0.3s left) still has to wait a moment, and a
    message reading "in 0s" would say try again *now* while still blocking it.
    """
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Slow down — try `/plant` again in {math.ceil(error.retry_after)}s.",
            ephemeral=True,
        )
        return
    _log.exception("Unhandled error in /plant.", exc_info=error)


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
