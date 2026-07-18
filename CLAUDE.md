# CLAUDE.md — Epiphyte

Dauerhafter Projektvertrag für Claude Code. Diese Datei beschreibt, *wie in
diesem Repo grundsätzlich gearbeitet wird* — Architektur, Invarianten,
Konventionen. Die konkreten Aufgaben einer Phase kommen über den jeweiligen
Prompt, nicht über diese Datei. Im Konflikt gewinnt CLAUDE.md.

---

## Was das ist

Epiphyte ist ein Discord-Bot, der in einem gewählten Kanal **eine einzige
Pflanze** darstellt. Jede Nachricht wässert sie, Stille lässt sie über Zeit
verdorren. Kein Utility-Bot, sondern ein Kunstprojekt mit einem ehrlichen
Nebeneffekt: Die Pflanze zeigt ungeschönt, wie lebendig ein Kanal wirklich ist.
**Jeder Server bekommt seinen eigenen, isolierten Pflanzenzustand** — keine
geteilte, serverübergreifende Welt.

## Oberste Entscheidungsregel: das Rasiermesser

Bei **jeder** Unklarheit in der Umsetzung gilt: die einfachste Struktur bauen,
die die *aktuell* zu lösende Idee korrekt ausdrückt. Keine Abstraktion, keine
Konfigurierbarkeit, keine Bibliothek „für später", solange der Bedarf noch nicht
real eingetreten ist. Im Zweifel immer die simplere Lösung — das ist der
Tie-Breaker, kein Grund zu blockieren.

## Goldene Regeln (nicht verhandelbar)

1. **Secrets ausschließlich über Umgebungsvariablen**, niemals im Code oder
   Repository. Namen: `EPIPHYTE_TOKEN` (Pflicht), `EPIPHYTE_GUILD_ID` (optional,
   Test-Guild).
2. **Keine privilegierten Gateway-Intents.** Der Bot muss nur wissen, *dass* eine
   Nachricht kam, nie *was* drinsteht. `discord.Intents.default()` genügt dafür
   dauerhaft.
3. **Reine Logik strikt von I/O trennen** (eigener Abschnitt weiter unten). Der
   interessante Teil muss ohne discord.py testbar sein.
4. **Phasendisziplin:** immer nur die aktuelle Phase umsetzen, nie vorgreifen.
5. **Nur Slash-Commands.** Das Gießen ist immer passiv, nie ein Befehl.
6. **Keine Abhängigkeit hinzufügen, bevor die aktuelle Phase sie wirklich
   braucht.**

## Architektur (entschieden — nicht neu diskutieren)

- **Sprache: ausschließlich Python.** Kein Rust. Die Rechenlast pro Tick (kleines
  L-System, etwas Turtle-Grafik) ist real trivial, auch bei vielen parallelen
  Servern, weil jede Pflanze unabhängig und selten rechnet.
- **discord.py** als Framework. **`discord.Client` mit eigenem
  `app_commands.CommandTree`, nicht `commands.Bot`** — es werden ausschließlich
  Slash-Commands genutzt.
- **Pillow** rendert das L-System-Ergebnis als PNG fürs Embed.
- **APScheduler** taktet die Feuchtigkeits-Zerfallsschritte.
- **SQLite** (Python-Standardbibliothek) hält den Zustand pro Server — keine
  zusätzliche DB-Abhängigkeit.
- **Command-Sync im `setup_hook`:** ist `EPIPHYTE_GUILD_ID` gesetzt, die Commands
  per `copy_global_to` in diese Guild kopieren und dort synchronisieren (sofort
  sichtbar); sonst globaler Sync (Sichtbarkeit kann bis zu 1 h dauern).

## Phasenplan — eine Phase komplett abschließen, bevor die nächste beginnt

- **Phase 0 — Herzschlag:** Grundgerüst, ein Command, feste Testantwort. Kein
  Zustand, keine Simulation. *Fertig, wenn* der Bot 24 h stabil läuft und
  zuverlässig reagiert.
- **Phase 1 — Feuchtigkeit ohne Bild:** Feuchtigkeits-Zähler pro Server im
  Speicher, `on_message`-Listener, exponentieller Zerfall über Zeit, reiner Text
  im Embed. Noch kein L-System, keine Persistenz (ein Neustart darf den Stand
  verlieren). *Fertig, wenn* aktive und stille Phasen sichtbar unterschiedliche
  Werte erzeugen.
- **Phase 2 — Ein Gesicht:** L-System (rekursive Ersetzungsregeln),
  Turtle-Interpreter, Pillow-Rendering als PNG, Versand über `discord.File` +
  `attachment://`. Nur eine Pflanzenart. *Fertig, wenn* verschiedene
  Wachstumsstufen sichtbar verschiedene Formen erzeugen.
- **Phase 3 — Fairness & Dauerhaftigkeit:** SQLite-Persistenz, abnehmende
  Grenzerträge beim Gießen pro Person und Zeitfenster (Mechanism Design gegen
  Spam-Farming), Feintuning der Zerfallsrate. *Fertig, wenn* ein Neustart den
  Zustand nicht verändert und Nachrichtenfluten die Pflanze nicht mehr künstlich
  am Leben halten.
- **Phase 4 — Politur & Release:** README, Lizenz, CONTRIBUTING.md,
  Screenshots/GIFs. *Fertig, wenn* eine fremde Person das Repo in 5 min versteht
  und den Bot in unter 10 min zum Laufen bringt.

## Zielstruktur (wächst mit den Phasen — nichts davon vorab anlegen)

```
epiphyte/
├── bot.py          # dünner discord-Adapter: Client, Commands, Events, Scheduler-Verdrahtung
├── moisture.py     # REINE LOGIK: Feuchtigkeits-Zerfall (pure functions)        [ab Phase 1]
├── lsystem.py      # REINE LOGIK: L-System-Expansion + Turtle → Geometrie       [ab Phase 2]
├── render.py       # Geometrie → PNG via Pillow (gekapselte I/O)                 [ab Phase 2]
├── storage.py      # SQLite-Persistenz (I/O)                                     [ab Phase 3]
├── tests/          # pytest, ausschließlich für die reine Logik                  [ab Phase 1]
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
└── CLAUDE.md
```

Ein neues Modul entsteht erst, wenn die Phase seine Funktion wirklich braucht.
Bis dahin bleibt alles Existierende so klein wie möglich. In Phase 0 ist `bot.py`
die einzige Quelldatei — reine Logik existiert noch nicht, also gibt es auch noch
keine getrennten Module und keine Tests.

## Reine Logik ⟷ I/O (das Herz der Struktur)

- **Reine Funktionen** (`moisture.py`, `lsystem.py`): deterministisch, ohne
  Seiteneffekte, **ohne jeden `import discord`**. Feuchtigkeits-Zerfall und
  L-System-Generierung sind reine Berechnungen — gleiche Eingabe, gleiche
  Ausgabe.
- **`bot.py` ist eine dünne Adapterschicht** darüber: nimmt Events entgegen, ruft
  die reine Logik, schickt das Ergebnis an Discord. Enthält selbst keine
  nennenswerte Berechnung.
- **`render.py`** übersetzt die rein berechnete Geometrie in ein PNG. I/O-nah,
  aber isoliert.
- Konsequenz und Zweck: Die reine Logik ist mit pytest testbar, ohne Discord
  überhaupt zu starten.

## Code-Konventionen

- PEP 8, durchgängige Type Hints, Docstrings für Modul, Klasse und alle
  öffentlichen Funktionen.
- Funktionen klein und auf **eine** Verantwortung fokussiert.
- Tests mit pytest **nur für die reine Logik**, nicht für die
  Discord-Integration. pytest ist eine Dev-Abhängigkeit, getrennt von den
  Laufzeit-Requirements; kommt dazu, sobald die erste reine Logik existiert
  (Phase 1).
- Bestehenden, nicht betroffenen Code nicht umformatieren oder umschreiben.

## Performance-Prinzipien

- Kein Rust — die Last ist real trivial, das wurde bewusst geprüft, nicht nur
  angenommen.
- discord.py läuft asynchron: rechenintensivere **synchrone** Arbeit
  (Pillow-Rendering, falls es je spürbar wird) gehört in einen Executor, damit
  die Event-Loop nicht blockiert und der Bot nicht „hängt".
- Sollte Performance je zum Thema werden, **zuerst die reine Logik profilen**
  (L-System, Zerfallsberechnung) — der einzige lohnende Kandidat. Keine
  Optimierung ohne Messung.

## Ästhetik: Nord-Farbschema (konsistent verwenden)

| Element | Hex | RGB |
|---|---|---|
| Hintergrund | `#2E3440` | 46, 52, 64 |
| Erde | `#3B4252` | 59, 66, 82 |
| Stängel unten (verwurzelt) | `#5E4A3B` | 94, 74, 59 |
| Stängel oben (lebendig) | `#8FBCBB` | 143, 188, 187 |
| Blätter | `#A3BE8C` | 163, 190, 140 |
| Knospe / Akzent | `#88C0D0` | 136, 192, 208 |

## Kommandos

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start (benötigt EPIPHYTE_TOKEN, optional EPIPHYTE_GUILD_ID)
python bot.py

# Tests der reinen Logik (ab Phase 1)
pytest

# Smoke-Test ohne Token: prüft nur, dass das Modul fehlerfrei importiert
python -c "import bot"
```

## Git / GitHub

- Repo-Name `epiphyte`, öffentlich, Lizenz MIT.
- Commits im **Conventional-Commits**-Stil (`feat:`, `fix:`, `docs:`, `chore:`),
  sinnvoll aufgeteilt.
- **README wächst mit jeder abgeschlossenen Phase mit** — nicht erst am Ende, und
  nie Features dokumentieren, die noch nicht existieren.

## Arbeitsweise in diesem Repo

- **Volle Code-Bereitstellung erwünscht.** Dies ist ein Kunst-Hobbyprojekt, kein
  Sokratisches Lernprojekt: vollständige, lauffähige Codeblöcke liefern, keine
  Selbst-Tipp-Anleitung.
- **Phasenweise arbeiten,** nie über die aktuelle Phase hinaus implementieren.
- **Vor „fertig":** Smoke-Test bzw. die Tests der reinen Logik laufen lassen. Eine
  Phase gilt erst als abgeschlossen, wenn ihr „Fertig, wenn"-Kriterium erfüllt
  ist.
- **Bei echter Unklarheit** kurz nachfragen; bei bloßer Umsetzungs-Ambiguität das
  Rasiermesser anwenden statt zu blockieren.
- **Kommunikation auf Deutsch,** direkt und substantiell, technische Begriffe
  präzise.

## Anti-Patterns (nicht tun)

- `commands.Bot` verwenden — stattdessen `discord.Client` + `CommandTree`.
- Privilegierte Intents anfordern oder Nachrichteninhalte lesen.
- Abstraktionen, Config-Layer oder Bibliotheken „für später" einführen.
- Abhängigkeiten hinzufügen, bevor die Phase sie braucht (in Phase 0 nur
  discord.py).
- Über die aktuelle Phase hinaus vorbauen.
- Secrets in Code oder Repository schreiben.
- Berechnung in `bot.py` verstecken, statt sie in reine Logik auszulagern.
- Große Funktionen mit mehreren Verantwortlichkeiten.
