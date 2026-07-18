# Epiphyte 🌱

Ein Discord-Bot, der in einem gewählten Kanal **eine einzige Pflanze**
darstellt. Jede Nachricht wässert sie, Stille lässt sie über die Zeit
verwelken. Kein Utility-Bot, sondern ein kleines Kunstprojekt mit einem
ehrlichen Nebeneffekt: Die Pflanze zeigt ungeschönt, wie lebendig ein Kanal
wirklich ist.

Jeder Server bekommt seinen eigenen, isolierten Pflanzenzustand — es gibt keine
geteilte, serverübergreifende Welt.

## Status: Phase 0 — Der Herzschlag

Das Grundgerüst steht: Der Bot verbindet sich, registriert genau einen
Slash-Command und antwortet zuverlässig. Es gibt **noch keinen Zustand und
keine Simulation** — das kommt in den späteren Phasen.

Aktuell verfügbar:

- **`/pflanze`** — sendet eine feste Platzhalter-Antwort.

## Setup

Voraussetzung: Python 3.11+ und ein
[Discord-Bot-Token](https://discord.com/developers/applications).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Start

Der Token wird ausschließlich über eine Umgebungsvariable gelesen, nie aus dem
Code oder Repository:

```bash
export EPIPHYTE_TOKEN="dein-bot-token"
# Optional: sofortige Sichtbarkeit der Commands in einer Test-Guild
export EPIPHYTE_GUILD_ID="deine-guild-id"

python bot.py
```

- Ist `EPIPHYTE_GUILD_ID` gesetzt, erscheinen die Slash-Commands sofort in
  dieser Guild.
- Ohne `EPIPHYTE_GUILD_ID` werden die Commands global registriert; ihre
  Auslieferung durch Discord kann bis zu einer Stunde dauern.

Der Bot benötigt **keine privilegierten Gateway-Intents** — er muss nur wissen,
*dass* eine Nachricht kam, nie *was* darin steht.

### Smoke-Test ohne Token

```bash
python -c "import bot"
```

Prüft, dass das Modul fehlerfrei importiert. Der Token wird erst beim echten
Start (`python bot.py`) gelesen.

## Roadmap

- **Phase 0 — Herzschlag** *(aktuell)*: Grundgerüst, ein Command, feste
  Antwort. Kein Zustand.
- **Phase 1 — Feuchtigkeit ohne Bild**: Feuchtigkeits-Zähler pro Server,
  exponentieller Zerfall über Zeit, reiner Text im Embed.
- **Phase 2 — Ein Gesicht**: L-System + Turtle-Interpreter, Rendering als PNG.
- **Phase 3 — Fairness & Dauerhaftigkeit**: SQLite-Persistenz, abnehmende
  Grenzerträge beim Gießen gegen Spam-Farming.
- **Phase 4 — Politur & Release**: Dokumentation, Screenshots, Feinschliff.

## Lizenz

[MIT](LICENSE) © 2026 Timur Manjosov
