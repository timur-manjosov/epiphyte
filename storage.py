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
    """

    guild_id: int
    structure: structure.Structure
    moisture: float
    last_update: float
    channel_id: int | None
    message_id: int | None
    dead_ticks: int = 0


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
                dead_ticks    INTEGER NOT NULL DEFAULT 0
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
        self._connection.commit()

    def load_all(self) -> dict[int, GuildState]:
        """Load every guild's state into a dict keyed by guild id."""
        rows = self._connection.execute(
            "SELECT guild_id, structure, moisture, last_update, channel_id, "
            "message_id, dead_ticks FROM plant_state"
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
            )
            for row in rows
        }

    def save(self, state: GuildState) -> None:
        """Insert or update one guild's state and commit immediately."""
        self._connection.execute(
            """
            INSERT INTO plant_state (
                guild_id, seed, structure, step_count, generation,
                moisture, last_update, channel_id, message_id, dead_ticks
            )
            VALUES (
                :guild_id, :seed, :structure, :step_count, :generation,
                :moisture, :last_update, :channel_id, :message_id, :dead_ticks
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
                dead_ticks  = excluded.dead_ticks
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
