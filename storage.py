"""SQLite persistence for Epiphyte (I/O).

One row per guild holds the plant's moisture, the wall-clock timestamp that
moisture was sampled at, and the channel the plant is watered from. All database
access is isolated here; the pure logic never touches it. SQLite ships with the
Python standard library, so this adds no dependency.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

#: Default on-disk database file (git-ignored). Overridable for tests.
DEFAULT_DB_PATH = "epiphyte.db"


@dataclass
class GuildState:
    """Persistent per-guild plant state.

    ``moisture`` is the value sampled at ``last_update`` (a Unix timestamp, so it
    stays comparable across restarts); ``channel_id`` is the watering channel, or
    ``None`` until one is chosen with ``/epiphyte-channel``.
    """

    guild_id: int
    moisture: float
    last_update: float
    channel_id: int | None


class Storage:
    """Thin wrapper around a SQLite connection holding the guild states."""

    def __init__(self, path: str = DEFAULT_DB_PATH) -> None:
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        """Create the guild_state table if it does not exist yet."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_state (
                guild_id      INTEGER PRIMARY KEY,
                moisture      REAL    NOT NULL,
                last_update   REAL    NOT NULL,
                channel_id    INTEGER
            )
            """
        )
        self._connection.commit()

    def load_all(self) -> dict[int, GuildState]:
        """Load every guild's state into a dict keyed by guild id."""
        rows = self._connection.execute(
            "SELECT guild_id, moisture, last_update, channel_id FROM guild_state"
        ).fetchall()
        return {
            row["guild_id"]: GuildState(
                guild_id=row["guild_id"],
                moisture=row["moisture"],
                last_update=row["last_update"],
                channel_id=row["channel_id"],
            )
            for row in rows
        }

    def save(self, state: GuildState) -> None:
        """Insert or update one guild's state and commit immediately."""
        self._connection.execute(
            """
            INSERT INTO guild_state (guild_id, moisture, last_update, channel_id)
            VALUES (:guild_id, :moisture, :last_update, :channel_id)
            ON CONFLICT(guild_id) DO UPDATE SET
                moisture    = excluded.moisture,
                last_update = excluded.last_update,
                channel_id  = excluded.channel_id
            """,
            {
                "guild_id": state.guild_id,
                "moisture": state.moisture,
                "last_update": state.last_update,
                "channel_id": state.channel_id,
            },
        )
        self._connection.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._connection.close()
