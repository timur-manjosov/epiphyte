"""Epiphyte — ein Discord-Bot, der in einem Kanal eine einzige Pflanze darstellt.

Phase 0 (Herzschlag): Grundgerüst mit genau einem Slash-Command ``/pflanze``,
der eine feste, thematisch passende Platzhalter-Antwort sendet. Noch kein
Zustand, keine Simulation, keine reine Logik — das kommt ab Phase 1.

Dieses Modul ist der dünne discord-Adapter aus der Architektur: Client,
Command, Event-/Sync-Verdrahtung. Es enthält bewusst keine nennenswerte
Berechnung.
"""

from __future__ import annotations

import os

import discord
from discord import app_commands

#: Name der Pflicht-Umgebungsvariable mit dem Bot-Token.
TOKEN_ENV = "EPIPHYTE_TOKEN"
#: Name der optionalen Umgebungsvariable mit der Test-Guild-ID.
GUILD_ENV = "EPIPHYTE_GUILD_ID"

#: Feste Platzhalter-Antwort für Phase 0.
PFLANZE_ANTWORT = (
    "🌱 Hier keimt Epiphyte. Noch ist die Pflanze nur ein Versprechen — "
    "bald wird jede Nachricht sie wässern und Stille sie welken lassen."
)


class EpiphyteClient(discord.Client):
    """Discord-Client mit eigenem Command-Tree (nur Slash-Commands).

    Nutzt ausschließlich die Standard-Intents: Der Bot muss nur wissen, *dass*
    Nachrichten kommen, nie *was* darin steht.
    """

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        """Synchronisiert die Slash-Commands beim Start.

        Ist ``EPIPHYTE_GUILD_ID`` gesetzt, werden die Commands in diese
        Test-Guild kopiert und dort sofort synchronisiert (sofort sichtbar);
        andernfalls erfolgt ein globaler Sync, dessen Auslieferung durch Discord
        bis zu einer Stunde dauern kann.
        """
        guild_id = os.getenv(GUILD_ENV)
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


client = EpiphyteClient()


@client.tree.command(name="pflanze", description="Zeigt den Zustand der Pflanze.")
async def pflanze(interaction: discord.Interaction) -> None:
    """Antwortet mit der festen Platzhalter-Nachricht (Phase 0)."""
    await interaction.response.send_message(PFLANZE_ANTWORT)


def main() -> None:
    """Liest den Token aus der Umgebung und startet den Bot.

    Der Token wird erst hier gelesen, nicht beim Import — so lässt sich das
    Modul tokenfrei importieren (Smoke-Test).
    """
    token = os.getenv(TOKEN_ENV)
    if not token:
        raise SystemExit(
            f"Umgebungsvariable {TOKEN_ENV} ist nicht gesetzt. "
            "Ohne Token kann der Bot nicht starten."
        )
    client.run(token)


if __name__ == "__main__":
    main()
