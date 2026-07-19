"""SQLite persistence for Epiphyte (I/O).

One row per guild holds the plant's whole persistent state: its seed, its
serialised body, how many growth steps it has taken, its moisture with the
timestamp that moisture was sampled at, the timestamp growth last advanced, and
the channel it is watered from. All database access is isolated here; the pure
logic never touches it. SQLite ships with the Python standard library, so this
adds no dependency.

The body is stored as JSON produced by :func:`structure.serialize`. The ``seed``
and ``step_count`` columns mirror values inside that blob for easy inspection;
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

    ``structure`` is the accumulated body (which itself carries the seed and step
    count). ``moisture`` is the value sampled at ``last_update``; ``last_growth``
    is when growth steps were last applied. Both timestamps are Unix time, so they
    stay comparable across restarts. ``channel_id`` is the watering channel, or
    ``None`` until one is chosen with ``/epiphyte-channel``.
    """

    guild_id: int
    structure: structure.Structure
    moisture: float
    last_update: float
    last_growth: float
    channel_id: int | None


class Storage:
    """Thin wrapper around a SQLite connection holding the guild states."""

    def __init__(self, path: str = DEFAULT_DB_PATH) -> None:
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        """Create the plant_state table if it does not exist yet."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plant_state (
                guild_id      INTEGER PRIMARY KEY,
                seed          INTEGER NOT NULL,
                structure     TEXT    NOT NULL,
                step_count    INTEGER NOT NULL,
                moisture      REAL    NOT NULL,
                last_update   REAL    NOT NULL,
                last_growth   REAL    NOT NULL,
                channel_id    INTEGER
            )
            """
        )
        self._connection.commit()

    def load_all(self) -> dict[int, GuildState]:
        """Load every guild's state into a dict keyed by guild id."""
        rows = self._connection.execute(
            "SELECT guild_id, structure, moisture, last_update, last_growth, "
            "channel_id FROM plant_state"
        ).fetchall()
        return {
            row["guild_id"]: GuildState(
                guild_id=row["guild_id"],
                structure=structure.deserialize(json.loads(row["structure"])),
                moisture=row["moisture"],
                last_update=row["last_update"],
                last_growth=row["last_growth"],
                channel_id=row["channel_id"],
            )
            for row in rows
        }

    def save(self, state: GuildState) -> None:
        """Insert or update one guild's state and commit immediately."""
        self._connection.execute(
            """
            INSERT INTO plant_state (
                guild_id, seed, structure, step_count,
                moisture, last_update, last_growth, channel_id
            )
            VALUES (
                :guild_id, :seed, :structure, :step_count,
                :moisture, :last_update, :last_growth, :channel_id
            )
            ON CONFLICT(guild_id) DO UPDATE SET
                seed        = excluded.seed,
                structure   = excluded.structure,
                step_count  = excluded.step_count,
                moisture    = excluded.moisture,
                last_update = excluded.last_update,
                last_growth = excluded.last_growth,
                channel_id  = excluded.channel_id
            """,
            {
                "guild_id": state.guild_id,
                "seed": state.structure.seed,
                "structure": json.dumps(structure.serialize(state.structure)),
                "step_count": state.structure.step_count,
                "moisture": state.moisture,
                "last_update": state.last_update,
                "last_growth": state.last_growth,
                "channel_id": state.channel_id,
            },
        )
        self._connection.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._connection.close()
