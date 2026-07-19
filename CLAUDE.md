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

Ab Phase 5 wandelt sich Epiphyte von einer Zustandsanzeige zu einem **emergenten
Organismus**. Die Pflanze ist dann **keine Funktion ihrer momentanen Feuchtigkeit
mehr, sondern das akkumulierte Ergebnis ihres ganzen Lebens.** Gleiche
Feuchtigkeit bedeutet nicht mehr gleiche Form: Was einmal gewachsen ist, bleibt
Teil des Körpers. Es gibt **keine Endform und keinen Endzustand** — die Pflanze
wächst, kann sterben, und ihre Abstammung geht weiter.

## Oberste Entscheidungsregel: das Rasiermesser

Bei **jeder** Unklarheit in der Umsetzung gilt: die einfachste Struktur bauen,
die die *aktuell* zu lösende Idee korrekt ausdrückt. Keine Abstraktion, keine
Konfigurierbarkeit, keine Bibliothek „für später", solange der Bedarf noch nicht
real eingetreten ist. Im Zweifel immer die simplere Lösung — das ist der
Tie-Breaker, kein Grund zu blockieren.

## Zweite Entscheidungsregel: Emergenz

Tiefe entsteht durch **Regeln und Zeit**, nicht durch Commands und Optionen. Das
ist die künstlerische These des Projekts: wenige Commands, keine
Konfigurierbarkeit, keine Bestenlisten. Der Reichtum wohnt im **Verhalten des
Systems über die Zeit**, nicht an der Oberfläche. Wo eine Idee entweder als neue
Option oder als Regel im System ausgedrückt werden kann, gewinnt die Regel. Diese
Regel steht neben dem Rasiermesser, nicht im Widerspruch dazu: beide halten die
Oberfläche schmal und die Substanz im System.

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

- **Sprache: ausschließlich Python.** Kein Rust. Die Rechenlast pro Tick (ein
  Wachstumsschritt auf der Struktur, etwas Rendering) ist real trivial, auch bei
  vielen parallelen Servern, weil jede Pflanze unabhängig und selten rechnet.
- **discord.py** als Framework. **`discord.Client` mit eigenem
  `app_commands.CommandTree`, nicht `commands.Bot`** — es werden ausschließlich
  Slash-Commands genutzt.
- **Pillow** rendert die akkumulierte Pflanzenstruktur als PNG fürs Embed.
- **APScheduler** taktet ab Phase 6 die **autonome Aktualisierung** der Pflanze im
  Kanal: Wachstumsschritte (durch die Feuchtigkeit gegated) und das Neu-Rendern.
  Bewusst bis dahin zurückgehalten — die lebende Anzeige ist der reale Bedarf, der
  die Abhängigkeit rechtfertigt (Goldene Regel 6).
- **SQLite** (Python-Standardbibliothek) hält den Zustand pro Server — keine
  zusätzliche DB-Abhängigkeit.
- **Command-Sync im `setup_hook`:** ist `EPIPHYTE_GUILD_ID` gesetzt, die Commands
  per `copy_global_to` in diese Guild kopieren und dort synchronisieren (sofort
  sichtbar); sonst globaler Sync (Sichtbarkeit kann bis zu 1 h dauern).

## Zeitmodell (zwei Uhren)

- **Feuchtigkeit zerfällt lazy** über den gespeicherten Zeitstempel — exakt aus
  der verstrichenen Realzeit berechnet, erst wenn sie gebraucht wird. Das
  übersteht Ausfallzeiten des Bots ohne Fehler: verstreicht Zeit im
  Offline-Zustand, ist sie beim nächsten Blick korrekt eingerechnet.
- **Wachstum schreitet in diskreten Schritten** voran, ausgelöst durch einen
  Scheduler-Tick, und ist durch die Feuchtigkeit **gegated** — es passiert nur,
  während der Bot läuft, und nur, solange die Pflanze gesund genug ist. Ein
  Wachstumsschritt entspricht einer **konstanten realen Zeiteinheit**; ein großer
  Baum ist das Ergebnis von **Wochen** anhaltender Gesundheit, nicht eines
  einzelnen aktiven Abends.
- **Ehrliches Signal:** Wachstum ist durch die Feuchtigkeit gedeckelt und
  unterliegt den abnehmenden Grenzerträgen aus Phase 3. Baumgröße misst damit
  anhaltende echte Aktivität und ist **nicht durch Spam farmbar** — genau wie die
  Feuchtigkeit selbst.

## Phasenplan — eine Phase komplett abschließen, bevor die nächste beginnt

**Phase 0–4 sind abgeschlossen und als `v1.0.0` veröffentlicht** — die Pflanze als
lebende Zustandsanzeige. Ab Phase 5 beginnt die Wandlung zum emergenten
Organismus. Die neuen Stufen sind bewusst als **offene, endlose Entwicklung**
angelegt.

**Abgeschlossen (v1.0.0):**

- **Phase 0 — Herzschlag ✓:** Grundgerüst, ein Command, feste Testantwort.
- **Phase 1 — Feuchtigkeit ohne Bild ✓:** Feuchtigkeits-Zähler pro Server,
  `on_message`-Listener, exponentieller Zerfall, reiner Text im Embed.
- **Phase 2 — Ein Gesicht ✓:** L-System, Turtle-Interpreter, Pillow-Rendering als
  PNG, Versand über `discord.File` + `attachment://`.
- **Phase 3 — Fairness & Dauerhaftigkeit ✓:** SQLite-Persistenz, abnehmende
  Grenzerträge beim Gießen pro Person und Zeitfenster, kalibrierte Zerfallsrate.
- **Phase 4 — Politur & Release ✓:** README, Lizenz, CONTRIBUTING.md,
  Screenshots/GIFs.

**Offen — der Organismus (endlose Entwicklung):**

- **Phase 5 — Der Körper:** akkumulierende, individuelle Struktur. `structure.py`
  mit Datenmodell (Knoten mit Eltern-Verweisen), Genom (deterministisch aus einem
  Seed) und `grow()` als reine, seeded-deterministische Wachstumsfunktion; die
  Struktur wird persistiert. *Fertig, wenn* zwei Pflanzen bei gleicher
  Feuchtigkeit sichtbar verschiedene, aus ihrer eigenen Geschichte gewachsene
  Formen zeigen.
- **Phase 6 — Das Eigenleben:** autonome Aktualisierung im Kanal. APScheduler
  taktet die feuchtigkeits-gegateten Wachstumsschritte und rendert die Pflanze
  selbstständig neu. *Fertig, wenn* die Pflanze ohne jeden Command sichtbar über
  Tage wächst und verdorrt.
- **Phase 7 — Die Biografie:** Vitalität vs. Körper. Die Feuchtigkeit hinterlässt
  Spuren im Körper — Narben, Blattfall —, statt nur die momentane Form zu setzen.
  *Fertig, wenn* eine durchlittene Dürre auch nach der Erholung noch am Körper
  ablesbar bleibt.
- **Phase 8 — Der Lebenszyklus:** Tod, Same, Abstammung. Eine Pflanze kann
  sterben, einen Samen hinterlassen und so ihre Linie fortsetzen. *Fertig, wenn*
  aus einer toten Pflanze eine neue Generation mit verwandtem Genom hervorgeht.
- **Phase 9 — Emergente Meilensteine:** Blüte und die namensgebende Epiphyte, die
  auf einem hinreichend alten Baum siedelt. *Fertig, wenn* seltene, nicht
  erzwingbare Ereignisse allein aus anhaltender Gesundheit entstehen.
- **Phase 10 (optional) — Die Umwelt:** Tages- und Jahreszeit-Tönung des
  gerenderten Bildes.

**Es gibt keinen definierten letzten Schritt.** Der Phasenplan bleibt bewusst
offen; weitere Stufen dürfen entstehen, solange sie der Emergenz-These treu
bleiben.

## Zielstruktur (wächst mit den Phasen — nichts davon vorab anlegen)

```
epiphyte/
├── bot.py          # dünner discord-Adapter: Client, Commands, Events, Scheduler-Verdrahtung
├── moisture.py     # REINE LOGIK: Feuchtigkeit/Vitalität — Zerfall & Fairness    [ab Phase 1]
├── structure.py    # REINE LOGIK: Struktur, Genom (aus Seed), grow()            [ab Phase 5]
├── render.py       # Struktur → PNG via Pillow (gekapselte I/O)                  [ab Phase 2]
├── storage.py      # SQLite: Struktur, Seed, Lebensstatistik, Feuchtigkeit (I/O) [ab Phase 3]
├── tests/          # pytest, ausschließlich für die reine Logik                  [ab Phase 1]
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
└── CLAUDE.md
```

Ein neues Modul entsteht erst, wenn die Phase seine Funktion wirklich braucht.
Bis dahin bleibt alles Existierende so klein wie möglich.

`structure.py` löst ab Phase 5 die Rolle von `lsystem.py` ab: Statt eine Form
allein aus der momentanen Stufe zu erzeugen, hält es die über das ganze Leben
**akkumulierte** Struktur. `lsystem.py` gehört zum v1.0.0-Modell (Form aus Stufe)
und wird von `structure.py` abgelöst. `moisture.py` bleibt unverändert die
Vitalität; `storage.py` persistiert nun Struktur, Seed und Lebensstatistik statt
nur eines einzelnen Floats. Die Orchestrierung — Uhr lesen, fällige Schritte
bestimmen, reine Funktionen aufrufen, Ergebnis persistieren — bleibt vollständig
im dünnen Adapter `bot.py`.

## Reine Logik ⟷ I/O (das Herz der Struktur)

- **Reine Funktionen** (`moisture.py`, `structure.py`): deterministisch, ohne
  Seiteneffekte, **ohne jeden `import discord`** und ohne Uhr — Zeit und
  Zeitstempel werden hereingereicht. Feuchtigkeits-Zerfall und Wachstum sind reine
  Berechnungen. `grow()` ist **seeded-deterministisch**: gleiche Struktur,
  gleicher Seed und gleicher Schritt ergeben immer dieselbe Fortsetzung.
- **`bot.py` ist eine dünne Adapterschicht** darüber: nimmt Events und
  Scheduler-Ticks entgegen, liest die Uhr, bestimmt die fälligen Schritte, ruft
  die reine Logik und persistiert das Ergebnis. Enthält selbst keine nennenswerte
  Berechnung.
- **`render.py`** übersetzt die rein berechnete Struktur in ein PNG, **`storage.py`**
  kapselt die SQLite-Persistenz. Beide sind I/O-nah, aber isoliert.
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
  (Wachstum auf der Struktur, Zerfallsberechnung) — der einzige lohnende
  Kandidat. Keine Optimierung ohne Messung.

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

## Sprache: Code und Artefakte durchgängig auf Englisch

Das gesamte Projekt ist englischsprachig. In **Englisch** zu halten sind:

- **Bezeichner** — Variablen, Funktionen, Klassen, Module.
- **Kommentare und Docstrings.**
- **Log-Nachrichten.**
- **Alle nutzersichtbaren Bot-Texte** — Command-Namen, Command-Beschreibungen,
  Parameternamen, Antworten, Embeds, Fehlermeldungen. Der Herzschlag-Command
  heißt entsprechend `/plant`, nicht `/pflanze`.
- **README und jede weitere Repo-Dokumentation.**
- **Commit-Messages** (weiterhin Conventional Commits).
- **GitHub-Metadaten** — About-Text und Topics.

Einzige Ausnahme: Die laufende Kommunikation mit dem Maintainer in der
Claude-Code-Session bleibt auf Deutsch. Nur was ins Repository eingecheckt wird
oder Endnutzer erreicht, ist Englisch.
