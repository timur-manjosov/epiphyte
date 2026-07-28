"""SQLite persistence for Epiphyte (I/O).

One row per guild holds the plant's whole persistent state: its seed, its
serialised body, its age and generation, its moisture with the timestamp that
moisture was sampled at, how many ticks it has lain dead, the channel its
living message is displayed in, and the id of that message. All
database access is isolated here; the pure logic never touches it. SQLite ships
with the Python standard library, so this adds no dependency.

The body is stored as JSON produced by :func:`structure.serialize` (carrying the
lineage — generation and parent seed — inside it). The ``seed``, ``step_count``
and ``generation`` columns mirror values inside that blob for easy inspection;
the blob is authoritative on load.

A second table, ``author_presence``, holds one row per ``(guild_id, author_id)``
seen recently: a presence weight and the time it was last touched, on the same
lazy-decay pattern as the guild's own moisture. It feeds :func:`structure.
author_breadth` and is wiped for a guild when its plant dies and a successor
germinates, mirroring how :class:`structure.LifeStats` resets on rebirth — a new
generation earns its own crowd from scratch rather than inheriting its
predecessor's voices.

A third table, ``daily_activity``, holds one row per ``(guild_id, day_bucket)``
with the raw message count that calendar day. It feeds :func:`structure.
temporal_rhythm` and, unlike ``author_presence``, is *not* wiped when a
successor germinates: rhythm reads a community's own day-to-day cadence, not an
individual plant's biography, so it is never reset by a death it has nothing to
do with. It is only ever pruned back to the rolling window
:func:`structure.temporal_rhythm` reads (see ``prune_daily_activity``).

A fourth table, ``reactor_presence``, mirrors ``author_presence`` exactly —
weight and last-touched time per ``(guild_id, reactor_id)`` — but for people who
have reacted rather than posted. It feeds the reaction-warmth reading that only
ever surfaces once, sampled at the moment a bloom already earned by Phase 9's
own gate begins (see :func:`structure._bloom_intensity`), and is wiped on the
same rebirth as ``author_presence``: like breadth, a new generation's social
warmth is this life's own to earn, not its predecessor's.

A fifth table, ``thread_activity``, holds one row per ``(guild_id, thread_id,
author_id)`` with that author's message count in that thread and the Unix
timestamps of their first and most recent message there. Unlike
``author_presence``/``reactor_presence`` it carries no decayed weight — a
thread's whole short life is a handful of rows, not a value that needs to fade
continuously over weeks — and the caller (``bot.py``) aggregates a thread's
rows into the counts and span :func:`structure.thread_qualifies` reads. Like
``daily_activity`` and unlike the two presence tables, it is *not* wiped when a
successor germinates: which of a channel's conversations spin off into
sustained threads is a trait of the community's habits, not any one plant's
biography, so a successor's crown may nest as deeply from its very first tick
as its predecessor's did. It is only ever pruned back to threads still within
:data:`structure.THREAD_RECENCY_SECONDS` of now (see ``prune_thread_activity``).

A sixth table, ``voice_presence``, again mirrors ``author_presence`` exactly —
weight and last-touched time per ``(guild_id, user_id)`` — but for people who
have spent genuine shared time in a voice channel rather than posting or
reacting. It feeds the root system ``render.py`` draws (see
:func:`structure.root_spread`). It is wiped on the same rebirth as the other two
presence tables, and deliberately *not* treated like ``daily_activity`` or
``thread_activity``: those two are counters describing events a community
produces, while all three presence tables describe *people currently around a
particular plant*, which is this life's own to earn. Roots make that the most
literal of the three — a successor cannot inherit its predecessor's root system,
and having germinated as a single sprout it has no trunk to flare in any case.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

import structure

#: Default on-disk database file (git-ignored). Overridable for tests.
DEFAULT_DB_PATH = "epiphyte.db"


@dataclass
class GuildState:
    """Persistent per-guild plant state.

    ``structure`` is the accumulated body (which itself carries the seed, step
    count and lineage). ``moisture`` is the value sampled at ``last_update`` (a
    Unix time, so it stays comparable across restarts). ``dead_ticks`` counts how
    many ticks the plant has been fully dead, driving the brief dead phase before
    a successor germinates. ``channel_id`` is the display channel, or ``None``
    until one is chosen; ``message_id`` is the living plant message the bot edits
    in place each tick, or ``None`` until it has been posted.
    ``channel_unreachable_since`` is the Unix time the living message first
    became undeliverable, or ``None`` while delivery is working. It covers two
    distinct causes as one shared signal: the bound channel no longer resolves
    at all (deleted, or the bot lost access to it), and the channel resolves
    fine but the bot lacks permission to post there. Set and cleared by the
    living-message I/O in ``bot.py``, never by the pure logic; which of the two
    causes currently applies is not stored here but re-derived live for
    ``/plant``'s wording (see ``EpiphyteClient._channel_trouble_message``).
    """

    guild_id: int
    structure: structure.Structure
    moisture: float
    last_update: float
    channel_id: int | None
    message_id: int | None
    dead_ticks: int = 0
    channel_unreachable_since: float | None = None


class Storage:
    """Thin wrapper around a SQLite connection holding the guild states."""

    def __init__(self, path: str = DEFAULT_DB_PATH) -> None:
        # bot.py dispatches every write through asyncio.to_thread, off the event
        # loop's own thread, serialized by its own lock — check_same_thread=False
        # lets that worker thread touch the connection at all.
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        # WAL: readers and a writer no longer block each other, and an ordinary
        # commit appends to the log instead of always syncing the whole file —
        # the standard choice for a long-running process with frequent writes.
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        """Create the plant_state table, and add any columns older files lack."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plant_state (
                guild_id      INTEGER PRIMARY KEY,
                seed          INTEGER NOT NULL,
                structure     TEXT    NOT NULL,
                step_count    INTEGER NOT NULL,
                generation    INTEGER NOT NULL DEFAULT 1,
                moisture      REAL    NOT NULL,
                last_update   REAL    NOT NULL,
                channel_id    INTEGER,
                message_id    INTEGER,
                dead_ticks    INTEGER NOT NULL DEFAULT 0,
                channel_unreachable_since REAL
            )
            """
        )
        # Migrate databases that predate the Phase 8 lineage/lifecycle columns.
        present = {row["name"] for row in self._connection.execute("PRAGMA table_info(plant_state)")}
        if "generation" not in present:
            self._connection.execute(
                "ALTER TABLE plant_state ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"
            )
        if "dead_ticks" not in present:
            self._connection.execute(
                "ALTER TABLE plant_state ADD COLUMN dead_ticks INTEGER NOT NULL DEFAULT 0"
            )
        # Migrate databases that predate the unreachable-channel timestamp.
        if "channel_unreachable_since" not in present:
            self._connection.execute(
                "ALTER TABLE plant_state ADD COLUMN channel_unreachable_since REAL"
            )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS author_presence (
                guild_id   INTEGER NOT NULL,
                author_id  INTEGER NOT NULL,
                weight     REAL    NOT NULL,
                last_seen  REAL    NOT NULL,
                PRIMARY KEY (guild_id, author_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_activity (
                guild_id   INTEGER NOT NULL,
                day_bucket INTEGER NOT NULL,
                count      INTEGER NOT NULL,
                PRIMARY KEY (guild_id, day_bucket)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reactor_presence (
                guild_id   INTEGER NOT NULL,
                reactor_id INTEGER NOT NULL,
                weight     REAL    NOT NULL,
                last_seen  REAL    NOT NULL,
                PRIMARY KEY (guild_id, reactor_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_activity (
                guild_id      INTEGER NOT NULL,
                thread_id     INTEGER NOT NULL,
                author_id     INTEGER NOT NULL,
                message_count INTEGER NOT NULL,
                first_seen    REAL    NOT NULL,
                last_seen     REAL    NOT NULL,
                PRIMARY KEY (guild_id, thread_id, author_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_presence (
                guild_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                weight     REAL    NOT NULL,
                last_seen  REAL    NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        self._connection.commit()

    def load_all(self) -> dict[int, GuildState]:
        """Load every guild's state into a dict keyed by guild id."""
        rows = self._connection.execute(
            "SELECT guild_id, structure, moisture, last_update, channel_id, "
            "message_id, dead_ticks, channel_unreachable_since FROM plant_state"
        ).fetchall()
        return {
            row["guild_id"]: GuildState(
                guild_id=row["guild_id"],
                structure=structure.deserialize(json.loads(row["structure"])),
                moisture=row["moisture"],
                last_update=row["last_update"],
                channel_id=row["channel_id"],
                message_id=row["message_id"],
                dead_ticks=row["dead_ticks"],
                channel_unreachable_since=row["channel_unreachable_since"],
            )
            for row in rows
        }

    def save(self, state: GuildState) -> None:
        """Insert or update one guild's state and commit immediately."""
        self._connection.execute(
            """
            INSERT INTO plant_state (
                guild_id, seed, structure, step_count, generation,
                moisture, last_update, channel_id, message_id, dead_ticks,
                channel_unreachable_since
            )
            VALUES (
                :guild_id, :seed, :structure, :step_count, :generation,
                :moisture, :last_update, :channel_id, :message_id, :dead_ticks,
                :channel_unreachable_since
            )
            ON CONFLICT(guild_id) DO UPDATE SET
                seed        = excluded.seed,
                structure   = excluded.structure,
                step_count  = excluded.step_count,
                generation  = excluded.generation,
                moisture    = excluded.moisture,
                last_update = excluded.last_update,
                channel_id  = excluded.channel_id,
                message_id  = excluded.message_id,
                dead_ticks  = excluded.dead_ticks,
                channel_unreachable_since = excluded.channel_unreachable_since
            """,
            {
                "guild_id": state.guild_id,
                "seed": state.structure.seed,
                "structure": json.dumps(structure.serialize(state.structure)),
                "step_count": state.structure.step_count,
                "generation": state.structure.generation,
                "moisture": state.moisture,
                "last_update": state.last_update,
                "channel_id": state.channel_id,
                "message_id": state.message_id,
                "dead_ticks": state.dead_ticks,
                "channel_unreachable_since": state.channel_unreachable_since,
            },
        )
        self._connection.commit()

    def save_moisture(self, state: GuildState) -> None:
        """Update only the moisture and its timestamp, leaving the body untouched.

        Watering happens on every message, and a mature plant's serialised body runs
        to megabytes, so writing the whole row here would make the bot's hottest path
        its most expensive one. Growth still goes through :meth:`save`.
        """
        self._connection.execute(
            "UPDATE plant_state SET moisture = :moisture, last_update = :last_update "
            "WHERE guild_id = :guild_id",
            {
                "guild_id": state.guild_id,
                "moisture": state.moisture,
                "last_update": state.last_update,
            },
        )
        self._connection.commit()

    def load_all_author_presence(self) -> dict[int, dict[int, tuple[float, float]]]:
        """Load every guild's recorded author-presence weights, keyed by guild then author.

        Values are raw, undecayed ``(weight, last_seen)`` pairs — the caller
        (``bot.py``) decays each to the current moment on read, exactly like
        :attr:`GuildState.moisture` is decayed lazily rather than on write.
        """
        rows = self._connection.execute(
            "SELECT guild_id, author_id, weight, last_seen FROM author_presence"
        ).fetchall()
        result: dict[int, dict[int, tuple[float, float]]] = {}
        for row in rows:
            result.setdefault(row["guild_id"], {})[row["author_id"]] = (
                row["weight"],
                row["last_seen"],
            )
        return result

    def upsert_author_presence(
        self, guild_id: int, author_id: int, weight: float, last_seen: float
    ) -> None:
        """Insert or update one author's presence weight and commit immediately.

        Called on every watering (like :meth:`save_moisture`), so this touches
        exactly one row rather than the guild's whole state.
        """
        self._connection.execute(
            """
            INSERT INTO author_presence (guild_id, author_id, weight, last_seen)
            VALUES (:guild_id, :author_id, :weight, :last_seen)
            ON CONFLICT(guild_id, author_id) DO UPDATE SET
                weight    = excluded.weight,
                last_seen = excluded.last_seen
            """,
            {
                "guild_id": guild_id,
                "author_id": author_id,
                "weight": weight,
                "last_seen": last_seen,
            },
        )
        self._connection.commit()

    def delete_author_presence(self, guild_id: int, author_ids: list[int]) -> None:
        """Delete specific authors' presence rows — their weight has decayed to nothing.

        Run once per metabolic tick to keep the table bounded to genuinely
        still-relevant recent voices, rather than growing with every person who
        has ever posted once.
        """
        if not author_ids:
            return
        self._connection.executemany(
            "DELETE FROM author_presence WHERE guild_id = ? AND author_id = ?",
            [(guild_id, author_id) for author_id in author_ids],
        )
        self._connection.commit()

    def clear_author_presence(self, guild_id: int) -> None:
        """Delete every presence row for a guild — a fresh generation starts unheard.

        Called when a dead plant's successor germinates: like
        :class:`structure.LifeStats`, breadth is this life's own accumulated
        crowd, not the lineage's.
        """
        self._connection.execute("DELETE FROM author_presence WHERE guild_id = ?", (guild_id,))
        self._connection.commit()

    def load_all_reactor_presence(self) -> dict[int, dict[int, tuple[float, float]]]:
        """Load every guild's recorded reactor-presence weights, keyed by guild then reactor.

        Mirrors :meth:`load_all_author_presence` exactly, over reactors instead of
        message authors — see the module docstring.
        """
        rows = self._connection.execute(
            "SELECT guild_id, reactor_id, weight, last_seen FROM reactor_presence"
        ).fetchall()
        result: dict[int, dict[int, tuple[float, float]]] = {}
        for row in rows:
            result.setdefault(row["guild_id"], {})[row["reactor_id"]] = (
                row["weight"],
                row["last_seen"],
            )
        return result

    def upsert_reactor_presence(
        self, guild_id: int, reactor_id: int, weight: float, last_seen: float
    ) -> None:
        """Insert or update one reactor's presence weight and commit immediately.

        Called on every genuine (non-self) reaction, mirroring
        :meth:`upsert_author_presence`.
        """
        self._connection.execute(
            """
            INSERT INTO reactor_presence (guild_id, reactor_id, weight, last_seen)
            VALUES (:guild_id, :reactor_id, :weight, :last_seen)
            ON CONFLICT(guild_id, reactor_id) DO UPDATE SET
                weight    = excluded.weight,
                last_seen = excluded.last_seen
            """,
            {
                "guild_id": guild_id,
                "reactor_id": reactor_id,
                "weight": weight,
                "last_seen": last_seen,
            },
        )
        self._connection.commit()

    def delete_reactor_presence(self, guild_id: int, reactor_ids: list[int]) -> None:
        """Delete specific reactors' presence rows — their weight has decayed to nothing.

        Mirrors :meth:`delete_author_presence`, run once per metabolic tick.
        """
        if not reactor_ids:
            return
        self._connection.executemany(
            "DELETE FROM reactor_presence WHERE guild_id = ? AND reactor_id = ?",
            [(guild_id, reactor_id) for reactor_id in reactor_ids],
        )
        self._connection.commit()

    def clear_reactor_presence(self, guild_id: int) -> None:
        """Delete every reactor-presence row for a guild — a fresh generation starts unheard.

        Called alongside :meth:`clear_author_presence` when a dead plant's
        successor germinates — see the module docstring.
        """
        self._connection.execute("DELETE FROM reactor_presence WHERE guild_id = ?", (guild_id,))
        self._connection.commit()

    def load_all_voice_presence(self) -> dict[int, dict[int, tuple[float, float]]]:
        """Load every guild's recorded voice-presence weights, keyed by guild then user.

        Mirrors :meth:`load_all_author_presence` exactly, over people who have
        held genuine shared voice time instead of message authors — see the
        module docstring.
        """
        rows = self._connection.execute(
            "SELECT guild_id, user_id, weight, last_seen FROM voice_presence"
        ).fetchall()
        result: dict[int, dict[int, tuple[float, float]]] = {}
        for row in rows:
            result.setdefault(row["guild_id"], {})[row["user_id"]] = (
                row["weight"],
                row["last_seen"],
            )
        return result

    def upsert_voice_presence(
        self, guild_id: int, user_id: int, weight: float, last_seen: float
    ) -> None:
        """Insert or update one person's voice-presence weight and commit immediately.

        Called once per earned voice credit (see
        :data:`structure.VOICE_CREDIT_SECONDS`), which is a far rarer event than
        a message — this table's hot path is quiet by construction.
        """
        self._connection.execute(
            """
            INSERT INTO voice_presence (guild_id, user_id, weight, last_seen)
            VALUES (:guild_id, :user_id, :weight, :last_seen)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                weight    = excluded.weight,
                last_seen = excluded.last_seen
            """,
            {
                "guild_id": guild_id,
                "user_id": user_id,
                "weight": weight,
                "last_seen": last_seen,
            },
        )
        self._connection.commit()

    def delete_voice_presence(self, guild_id: int, user_ids: list[int]) -> None:
        """Delete specific people's voice-presence rows — their weight has decayed away.

        Mirrors :meth:`delete_author_presence`, run once per metabolic tick.
        """
        if not user_ids:
            return
        self._connection.executemany(
            "DELETE FROM voice_presence WHERE guild_id = ? AND user_id = ?",
            [(guild_id, user_id) for user_id in user_ids],
        )
        self._connection.commit()

    def clear_voice_presence(self, guild_id: int) -> None:
        """Delete every voice-presence row for a guild — a fresh generation is unrooted.

        Called alongside :meth:`clear_author_presence` and
        :meth:`clear_reactor_presence` when a dead plant's successor germinates —
        see the module docstring.
        """
        self._connection.execute("DELETE FROM voice_presence WHERE guild_id = ?", (guild_id,))
        self._connection.commit()

    def load_all_daily_activity(self) -> dict[int, dict[int, int]]:
        """Load every guild's recorded daily message counts, keyed by guild then day bucket.

        Feeds :func:`structure.temporal_rhythm`. Deliberately not cleared on a
        successor's germination (unlike :meth:`clear_author_presence`) — see the
        module docstring.
        """
        rows = self._connection.execute(
            "SELECT guild_id, day_bucket, count FROM daily_activity"
        ).fetchall()
        result: dict[int, dict[int, int]] = {}
        for row in rows:
            result.setdefault(row["guild_id"], {})[row["day_bucket"]] = row["count"]
        return result

    def increment_daily_activity(self, guild_id: int, day_bucket: int) -> None:
        """Count one more message toward a guild's calendar-day total and commit.

        Called on every watering (like :meth:`upsert_author_presence`), so this
        touches exactly one row rather than the guild's whole state.
        """
        self._connection.execute(
            """
            INSERT INTO daily_activity (guild_id, day_bucket, count)
            VALUES (:guild_id, :day_bucket, 1)
            ON CONFLICT(guild_id, day_bucket) DO UPDATE SET
                count = count + 1
            """,
            {"guild_id": guild_id, "day_bucket": day_bucket},
        )
        self._connection.commit()

    def prune_daily_activity(self, guild_id: int, oldest_kept_bucket: int) -> None:
        """Delete a guild's day buckets older than :func:`structure.temporal_rhythm`'s window.

        Run once per metabolic tick (mirroring :meth:`delete_author_presence`) so
        the table stays bounded to the rolling window rather than growing for as
        long as the guild has had a plant.
        """
        self._connection.execute(
            "DELETE FROM daily_activity WHERE guild_id = ? AND day_bucket < ?",
            (guild_id, oldest_kept_bucket),
        )
        self._connection.commit()

    def load_all_thread_activity(self) -> dict[int, dict[int, dict[int, tuple[int, float, float]]]]:
        """Load every guild's recorded thread activity, keyed by guild, then thread, then author.

        Values are ``(message_count, first_seen, last_seen)`` triples — see the
        module docstring. The caller (``bot.py``) aggregates a thread's rows
        into what :func:`structure.thread_qualifies` needs.
        """
        rows = self._connection.execute(
            "SELECT guild_id, thread_id, author_id, message_count, first_seen, last_seen "
            "FROM thread_activity"
        ).fetchall()
        result: dict[int, dict[int, dict[int, tuple[int, float, float]]]] = {}
        for row in rows:
            guild_threads = result.setdefault(row["guild_id"], {})
            guild_threads.setdefault(row["thread_id"], {})[row["author_id"]] = (
                row["message_count"],
                row["first_seen"],
                row["last_seen"],
            )
        return result

    def upsert_thread_activity(
        self, guild_id: int, thread_id: int, author_id: int, now: float, increment: bool
    ) -> None:
        """Record one author's activity in one thread and commit immediately.

        ``increment`` is ``True`` for an actual message (advances
        ``message_count`` by one, mirroring :meth:`increment_daily_activity`)
        and ``False`` for a thread's creation instant (see ``bot.py``'s
        ``on_thread_create``): the owner is registered with zero messages so
        far, anchoring ``first_seen`` at the thread's actual birth rather than
        its first tracked message, without yet counting toward
        :data:`structure.THREAD_MIN_MESSAGES_PER_PARTICIPANT` on its own.
        ``last_seen`` always advances to ``now``, and an existing row's
        ``first_seen`` is never overwritten — a row is only ever created once,
        at whichever of the two events reaches this author first.
        """
        self._connection.execute(
            """
            INSERT INTO thread_activity (
                guild_id, thread_id, author_id, message_count, first_seen, last_seen
            )
            VALUES (:guild_id, :thread_id, :author_id, :initial_count, :now, :now)
            ON CONFLICT(guild_id, thread_id, author_id) DO UPDATE SET
                message_count = message_count + :increment_amount,
                last_seen     = :now
            """,
            {
                "guild_id": guild_id,
                "thread_id": thread_id,
                "author_id": author_id,
                "initial_count": 1 if increment else 0,
                "increment_amount": 1 if increment else 0,
                "now": now,
            },
        )
        self._connection.commit()

    def prune_thread_activity(self, guild_id: int, oldest_kept: float) -> None:
        """Delete a guild's thread rows whose thread has had no message since ``oldest_kept``.

        A whole thread is dropped only once every one of its rows is stale —
        deleting one lagging participant's row while the thread is still live
        elsewhere would silently disqualify it. Run once per metabolic tick
        (mirroring :meth:`prune_daily_activity`) so the table stays bounded to
        genuinely still-relevant recent threads.
        """
        self._connection.execute(
            """
            DELETE FROM thread_activity
            WHERE guild_id = ? AND thread_id IN (
                SELECT thread_id FROM thread_activity
                WHERE guild_id = ?
                GROUP BY thread_id
                HAVING MAX(last_seen) < ?
            )
            """,
            (guild_id, guild_id, oldest_kept),
        )
        self._connection.commit()

    def vacuum(self) -> None:
        """Rebuild the database file, reclaiming space a dead generation freed.

        ``VACUUM`` rewrites the whole file, so the caller must only run this at a
        naturally infrequent point — a generational reseed, not a timer or every
        save — which is exactly when a large structure blob's freed pages become
        worth returning to the OS.
        """
        self._connection.execute("VACUUM")

    def close(self) -> None:
        """Close the underlying database connection."""
        self._connection.close()
