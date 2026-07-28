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
