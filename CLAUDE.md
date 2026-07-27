# CLAUDE.md — Epiphyte

Dauerhafter Projektvertrag für Claude Code. Diese Datei beschreibt, *wie in
diesem Repo grundsätzlich gearbeitet wird* — Architektur, Invarianten,
Konventionen. Die konkreten Aufgaben einer Phase kommen über den jeweiligen
Prompt, nicht über diese Datei. Im Konflikt gewinnt CLAUDE.md.

---

## Was das ist

> Epiphyte shows how alive a Discord server is, as a plant. One server, one
> plant, one continuously accumulating measure of vitality — everything else
> is derived from that single mechanism, not a second feature bolted on.

Das ist die These wörtlich — jede künftige Phase (neue Vitalitätsdimensionen,
Artenwahl, Umwelt-Tönung, was auch immer) muss sich als **weitere Ableitung
aus diesem einen Mechanismus** lesen lassen, nie als zweites, unabhängiges
Feature. Details dazu unter „Zweite Entscheidungsregel: Emergenz".

Epiphyte ist ein Discord-Bot, der pro Server **eine einzige Pflanze**
darstellt, angezeigt in einem gewählten Kanal. Jede Nachricht wässert sie,
Stille lässt sie über Zeit verdorren. Kein Utility-Bot, sondern ein
Kunstprojekt mit einem ehrlichen Nebeneffekt: Die Pflanze zeigt ungeschönt,
wie lebendig ein Server wirklich ist. **Jeder Server bekommt seinen eigenen,
isolierten Pflanzenzustand** — keine geteilte, serverübergreifende Welt.

Die Pflanze ist **keine Funktion ihrer momentanen Feuchtigkeit, sondern das
akkumulierte Ergebnis ihres ganzen Lebens.** Gleiche Feuchtigkeit bedeutet
nicht gleiche Form: Was einmal gewachsen ist, bleibt Teil des Körpers. Es gibt
**keine Endform und keinen Endzustand** — die Pflanze wächst, kann sterben,
und ihre Abstammung geht weiter. Das ist längst keine Vision mehr: Struktur,
Genom, Wachstum, Dürre-Narben, Tod und Abstammung sowie Blüte/Samen/Epiphyte
(Phasen 5–9) sind gebaut, commitet und aktueller Stand des Codes (siehe
Phasenplan unten).

## Oberste Entscheidungsregel: das Rasiermesser

Bei **jeder** Unklarheit in der Umsetzung gilt: die einfachste Struktur bauen,
die die *aktuell* zu lösende Idee korrekt ausdrückt. Keine Abstraktion, keine
Konfigurierbarkeit, keine Bibliothek „für später", solange der Bedarf noch nicht
real eingetreten ist. Im Zweifel immer die simplere Lösung — das ist der
Tie-Breaker, kein Grund zu blockieren.

## Zweite Entscheidungsregel: Emergenz

Tiefe entsteht durch **Regeln und Zeit**, nicht durch Commands und Optionen.
Das ist die künstlerische These des Projekts — und sie hat zwei Hälften, die
nie miteinander verwechselt werden dürfen. Eine frühere Fassung dieser Datei
hat genau das getan (Minimalismus als Oberflächen-Regel mit Minimalismus als
Substanz-Regel verwechselt); das hier ist die Korrektur, und sie gilt
dauerhaft:

1. **Oberflächen-Minimalismus (fix, nicht verhandelbar):** eine kleine, feste
   Zahl an Commands über die gesamte Lebenszeit der Pflanze (aktuell drei:
   `/plant`, `/epiphyte-channel`, `/help` — siehe `bot.py`), keine
   Konfigurierbarkeit, kein Settings-Menü, keine Bestenliste, keine
   privilegierten Gateway-Intents. Das regelt **wie der Mensch mit einem
   lebendigen Ding interagiert** — nicht, wie reichhaltig dieses Ding selbst
   sein darf.
2. **Verhaltensreichtum (bewusst offen, soll über Jahre wachsen):** die Zahl
   und Vielfalt echter, nicht-privilegierter Discord-Signale
   (Nachrichtenautorschaft, Reaktionen, Sprachaktivität, Threads, zeitlicher
   Rhythmus, Kanalbreite und weitere, noch nicht identifizierte), die je eine
   eigene botanische Dimension **derselben einen Pflanze** antreiben dürfen.
   **Mehr Signale sind keine Verletzung der These — eine zweite, unabhängige
   Funktion oder ein zweiter Mechanismus wäre es.**

Der Reichtum wohnt im **Verhalten des Systems über die Zeit**, nicht an der
Oberfläche — und „Verhalten" heißt hier ausdrücklich: je mehr ehrliche
Signale einfließen, desto reicher darf die eine Pflanze werden. **„Wenige
Signale" ist niemals treuer zur These als „viele Signale"**; die These
handelt von der Oberfläche (Commands, Konfiguration), nicht von der Substanz
(was die Pflanze aus dem Leben des Servers macht). Ein Vorschlag, der
Reichtum kürzt, um „minimalistisch" zu bleiben, hat die These falsch
verstanden — genauso falsch wie ein Vorschlag, der einen zweiten Command
oder ein Einstellungsmenü einführt, um Reichtum zu „ermöglichen". Wo eine
Idee entweder als neue Option/neuer Command oder als Regel im bestehenden
Mechanismus ausgedrückt werden kann, gewinnt **immer** die Regel im
Mechanismus — nie die Option, und auch nicht „eine weitere Dimension" als
Vorwand für eine zweite Oberfläche.

### Der Zulassungstest für ein neues Vitalitätssignal

Das ist die eigentliche Leitplanke gegen als Reichtum getarnten
Feature-Creep — nicht die Signalzahl. Bevor irgendein Discord-Signal jenseits
des schon gebauten (Nachrichten → Feuchtigkeit) eine botanische Dimension
antreiben darf, muss es **alle drei** Kriterien erfüllen:

1. **Keine privilegierten Intents:** nur nicht-privilegierte
   Gateway-Ereignisse (Reaktions-, Voice-State-, Thread-Events zählen dazu;
   das Lesen von Nachrichteninhalt nicht).
2. **Akkumuliert über echte Zeit, statt auf ein einzelnes Ereignis zu
   reagieren:** ein einzelner Spot-Event darf höchstens einen winzigen,
   wieder zerfallenden Beitrag leisten, nie direkt einen dauerhaften
   Strukturzustand auslösen — spiegelbildlich zu Feuchtigkeit, die zerfällt,
   und Wachstum, das in diskreten Schritten voranschreitet.
3. **Für eine einzelne Person allein nicht farmbar:** dasselbe
   abnehmende-Grenzerträge-Prinzip wie beim Gießen (Phase 3,
   `effective_water_amount` in `moisture.py`) muss greifen oder sinngemäß
   übertragbar sein.

Konkret an einem noch nicht gebauten Signal durchgespielt, damit der Test
kein Lippenbekenntnis bleibt: **Reaktionen** bestehen den Test, wenn sie —
wie das Gießen selbst — nur mit Fenster und Falloff pro reagierender Person
gezählt werden, sodass das Signal echte Breite über mehrere Leute misst.
Ein naiver Entwurf wie „Anzahl der Reaktionen, die eine einzelne Person
heute vergeben hat" **besteht den Test nicht**: eine Person kann allein auf
beliebig viele eigene oder fremde Nachrichten reagieren und das Signal ohne
jede zweite Person füllen. Ein solcher Entwurf ist entweder zu verwerfen oder
um genau dasselbe Person-Fenster-Falloff-Muster zu ergänzen, bevor er
überhaupt zugelassen wird — dieselbe Regel, die schon das Gießen ehrlich
macht.

### Die Aura-Parallele

Epiphyte folgt demselben Muster wie Aura, das andere Projekt des
Maintainers: **ein Mechanismus, mehrere abgeleitete Funktionen bzw.
Dimensionen.** Aura leitet Abfrage, proaktive Entlastung, Onboarding und
Digest aus einem einzigen destillierten Faktenmodell ab. Epiphyte leitet
(heute) Struktur, feuchtigkeits-modulierte Erscheinung, Dürre-Vernarbung und
Lebenszyklus aus einem einzigen Vitalitätsmechanismus ab — mit Raum für viele
weitere botanische Dimensionen aus zusätzlichen ehrlichen Signalen, sofern sie
den Zulassungstest oben bestehen. Das ist keine Dekoration, sondern die
knappste Erinnerung dagegen, aus „wenige Commands" fälschlich „wenige
Signale" oder „wenig Substanz" abzuleiten.

Diese Regel steht neben dem Rasiermesser, nicht im Widerspruch dazu: das
Rasiermesser hält die *Umsetzung* der aktuell zugelassenen Idee einfach; diese
Regel hält die *Oberfläche* schmal, während die *Substanz* im System über
Jahre wachsen darf. Beide zusammen halten die Oberfläche schmal und die
Substanz im System — nicht die Substanz selbst schmal.

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
lebende Zustandsanzeige. **Phase 5–9 sind ebenfalls vollständig im Code gebaut
und commitet** — der emergente Organismus ist der aktuelle Stand von
`structure.py`, `render.py`, `storage.py` und `bot.py`, keine offene
Baustelle mehr; sie warten lediglich noch auf einen eigenen benannten
Release. Die Stufen danach sind bewusst als **offene, endlose Entwicklung**
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

**Abgeschlossen im Code (noch ohne eigenen Versions-Tag):**

- **Phase 5 — Der Körper ✓:** akkumulierende, individuelle Struktur in
  `structure.py` — Datenmodell (`Node` mit Eltern-Verweis), `Genome`
  (deterministisch aus einem Seed via `genome_from_seed`) und `grow()` als
  reine, seeded-deterministische Wachstumsfunktion; die Struktur wird über
  `storage.py` persistiert. `lsystem.py` ist bereits vollständig entfernt.
  Zwei Pflanzen bei gleicher Feuchtigkeit zeigen sichtbar verschiedene, aus
  ihrer eigenen Geschichte gewachsene Formen.
- **Phase 6 — Das Eigenleben ✓:** `bot.py` taktet über `AsyncIOScheduler`
  einen `metabolic_tick`, der die feuchtigkeits-gegateten Wachstumsschritte
  auslöst und die Pflanze selbstständig neu rendert — sichtbar über Tage,
  ganz ohne Command.
- **Phase 7 — Die Biografie ✓:** `DIEBACK_MOISTURE_THRESHOLD` und
  `_dieback_step` in `structure.py` lassen eine durchlittene Dürre als
  permanente Narbe zurück — tote Knoten (`NodeState.DEAD`) werden nie entfernt
  und nie wiederbelebt, bleiben also auch nach der Erholung sichtbar.
- **Phase 8 — Der Lebenszyklus ✓:** `is_dead`, `germinate_successor` und
  `mutate` in `structure.py`, zusammen mit `dead_ticks` in `storage.py`,
  lassen aus einer toten Pflanze eine neue Generation mit einfach mutiertem,
  verwandtem Genom hervorgehen.
- **Phase 9 — Emergente Meilensteine ✓:** `is_blooming`, `has_seeded` und
  `can_host_epiphyte` in `structure.py` lassen Blüte, Samen und die
  namensgebende Epiphyte allein aus angehäufter, nicht erzwingbarer Gesundheit
  entstehen (Reserve-Bank, Mindestgröße, Mindestalter).

**Offen:**

- **Phase 10 (optional) — Die Umwelt:** Tages- und Jahreszeit-Tönung des
  gerenderten Bildes. Noch nicht begonnen — in `render.py` gibt es aktuell
  keine Zeit- oder Jahreszeit-Tönung.
- **Weitere, noch unbenannte Phasen:** zusätzliche Vitalitätssignale (siehe
  „Zulassungstest für ein neues Vitalitätssignal" oben) und die botanischen
  Dimensionen, die sie antreiben — z. B. Reaktionen, Sprachaktivität,
  Threads, zeitlicher Rhythmus, Kanalbreite.

**Es gibt keinen definierten letzten Schritt.** Der Phasenplan bleibt bewusst
offen; weitere Stufen dürfen entstehen, solange sie der Emergenz-These treu
bleiben — als weitere Ableitung aus dem einen Vitalitätsmechanismus, nie als
zweites Feature.

## Zielstruktur (wächst mit den Phasen — nichts davon vorab anlegen)

```
epiphyte/
├── bot.py               # dünner discord-Adapter: Client, Commands, Events,
│                        #   Scheduler-Verdrahtung (metabolic_tick)
├── moisture.py          # REINE LOGIK: Feuchtigkeit/Vitalität — Zerfall & Fairness      [Phase 1]
├── structure.py         # REINE LOGIK: akkumulierte Struktur, Genom (aus Seed), grow(),
│                        #   Dieback/Narben, Tod & Nachfolge, Blüte/Samen/Epiphyte  [Phase 5–9]
├── render.py            # Struktur → PNG via Pillow (gekapselte I/O)                    [Phase 2, erweitert 5–9]
├── storage.py           # SQLite: Struktur, Seed, Lebensstatistik, Lineage, Feuchtigkeit,
│                        #   Kanal/Nachricht, dead_ticks (I/O)                     [Phase 3, erweitert 5–9]
├── tests/               # pytest, ausschließlich für die reine Logik                    [ab Phase 1]
├── requirements.txt
├── requirements-dev.txt # pytest, reine Dev-Abhängigkeit, getrennt von der Laufzeit      [Phase 1]
├── README.md
├── CONTRIBUTING.md
├── LICENSE
├── .gitignore
└── CLAUDE.md
```

Ein neues Modul entsteht erst, wenn die Phase seine Funktion wirklich braucht.
Bis dahin bleibt alles Existierende so klein wie möglich.

`structure.py` hat die Rolle von `lsystem.py` bereits abgelöst und ist aus dem
Repo entfernt: Statt eine Form allein aus der momentanen Stufe zu erzeugen,
hält `structure.py` die über das ganze Leben **akkumulierte** Struktur —
inklusive Dieback, Lebenszyklus (Tod, Nachfolge) und Meilensteinen (Blüte,
Samen, Epiphyte). `moisture.py` bleibt unverändert die Vitalität; `storage.py`
persistiert Struktur, Seed, Lebensstatistik, Lineage und Kanal-/Nachrichtenstatus
statt nur eines einzelnen Floats. Die Orchestrierung — Uhr lesen, fällige
Schritte bestimmen, reine Funktionen aufrufen, Ergebnis persistieren — bleibt
vollständig im dünnen Adapter `bot.py`.

### Vitalitätssignale: gebaut vs. entworfen

Damit die Lücke zwischen These und Implementierung nicht in Prosa untergeht:

| Signal → Dimension | Status |
|---|---|
| Nachrichten (Autorschaft, Häufigkeit) → Feuchtigkeit, Wachstum | **live** (`moisture.py`, `on_message` in `bot.py`) |
| Feuchtigkeits-Zerfall über verstrichene Zeit → Verdorren | **live** (`moisture.decay`) |
| Abnehmende Grenzerträge pro Person/Fenster → Anti-Farming | **live** (`moisture.effective_water_amount`) |
| Reaktionen → eigene Dimension | entworfen, noch nicht gebaut |
| Sprachaktivität (Voice) → eigene Dimension | entworfen, noch nicht gebaut |
| Threads → eigene Dimension | entworfen, noch nicht gebaut |
| Zeitlicher Rhythmus (Tages-/Wochengang) → eigene Dimension | entworfen, noch nicht gebaut |
| Kanalbreite (wie viele verschiedene Kanäle aktiv sind) → eigene Dimension | entworfen, noch nicht gebaut |

Jedes „entworfen, noch nicht gebaut"-Signal muss vor der Implementierung den
Zulassungstest oben bestehen (keine privilegierten Intents, akkumuliert über
echte Zeit, für eine Einzelperson nicht farmbar).

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
