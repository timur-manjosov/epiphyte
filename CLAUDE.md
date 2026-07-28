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

## Geltungsbereich: serverweit, nicht kanalweit

**Die Pflanze ist ein serverweiter Organismus; der gebundene Kanal ist ihr
Schaufenster, nie ein Scope-Filter.** Das war seit Phase 3 (Feuchtigkeit) immer
schon wahr und ist inzwischen für alle fünf Vitalitätssignale gleichermaßen
wahr — bislang nur nie als Prinzip benannt, sondern nur durch konsequent
gleiche Umsetzung entstanden. Diese Sektion macht es verbindlich, statt es bei
zufälliger Konsistenz zu belassen.

Konkret: `channel_id` in `plant_state` ist die **einzige** kanalgebundene
Spalte im ganzen Schema, und sie bedeutet ausschließlich „hier wird die
lebende Nachricht angezeigt". Jedes Signal wässert, zählt oder gewichtet
serverweit — `on_message`, `on_raw_reaction_add` und `on_voice_state_update`
prüfen nur, *dass* der Server überhaupt eine Pflanze hat, nie, in welchem
Kanal etwas passiert ist. `thread_id` in `thread_activity` ist davon zu
unterscheiden: das ist die Identität des einzelnen Threads (welche Zeilen zu
welchem Thread gehören), kein Scope-Filter auf einen Kanal.

**Für jedes künftige Signal oder jeden künftigen Mechanismus gilt dieselbe
Vorgabe per Default:** serverweit erfassen, nie auf den gebundenen Kanal oder
einen anderen einzelnen Kanal einschränken. Eine kanalgebundene Ausnahme
bräuchte eine ausdrückliche Begründung, die über „so ist es zufällig
implementiert" hinausgeht — z. B. ein Signal, dessen Bedeutung sich ohne
Kanalbezug gar nicht sinnvoll definieren lässt (denkbar für die in der
Signaltabelle unten als „entworfen, noch nicht gebaut" geführte Kanalbreite,
die *per Definition* mehrere Kanäle vergleicht statt sie zu einem Server-Wert
zusammenzufassen — dort wäre der Kanalbezug die Substanz des Signals selbst,
keine zufällige Abweichung von dieser Regel).

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
- **Phase 11 — Autorenbreite (Kronenverzweigung) ✓:** `author_breadth` in
  `structure.py` misst, aus wie vielen verschiedenen, über echte Zeit
  gehaltenen Stimmen sich die jüngste Aktivität eines Kanals speist, und
  skaliert darüber ausschließlich `branch_probability` in `grow()` — ein
  vielstimmiger Kanal wächst eine breitere, buschigere Krone als ein sonst
  gleich gesunder, aber einstimmiger. Die Präsenzgewichte pro Autor liegen in
  `storage.py`s neuer `author_presence`-Tabelle, gefüttert über `bot.py`s
  `on_message`, und werden mit demselben bereits anti-farming-gedeckelten
  Betrag aufgefüllt, den `moisture.next_watering` ohnehin pro Nachricht
  berechnet — ein einzelnes Konto kann sich also nur über mehrere echte Tage
  hinweg echte Präsenz erarbeiten, nie durch einen einzelnen Nachrichtenschub.
  Bei Tod/Wiedergeburt wird die Autorenliste geleert, genau wie `LifeStats` —
  eine neue Generation muss sich ihre eigene Zuhörerschaft neu erarbeiten.
- **Phase 12 — Zeitlicher Rhythmus (Wuchsform/Symmetrie) ✓:** `temporal_rhythm`
  in `structure.py` misst, wie gleichmäßig die tägliche Aktivität eines Servers
  über ein rollierendes 56-Tage-Fenster verteilt ist (Gini-Koeffizient der
  Tageszählungen, invertiert), unabhängig davon, wie viele Stimmen daran
  beteiligt sind — das bleibt allein `author_breadth`s Aufgabe. Skaliert
  ausschließlich die organische Winkel-Streuung neuer Internodien in `grow()`
  (`_jitter_multiplier`); ein gleichmäßig aktiver Server wächst einen ruhigeren,
  symmetrischeren Körper, ein Server mit stoßweiser Aktivität (z. B. nur an
  Wochenenden) einen unregelmäßigeren, knorrigeren — bei gleicher Größe und
  gleicher Kronenverzweigung, da ein anderer Hebel als Phase 11 bewegt wird.
  Die Tageszählungen liegen in `storage.py`s neuer `daily_activity`-Tabelle,
  gefüttert über `bot.py`s `on_message`; da Gini skaleninvariant ist, kauft kein
  Nachrichtenvolumen Gleichmäßigkeit — nur echte Streuung über echte Tage.
  Unter `RHYTHM_MIN_ACTIVE_DAYS` aktiven Tagen im Fenster (zu junger oder zu
  stiller Server) liefert die Funktion den neutralen Standardwert statt eines
  durch Rauschen erzeugten Extrems. Anders als die Autorenliste wird
  `daily_activity` bei Tod/Wiedergeburt **nicht** geleert: Rhythmus beschreibt
  den Charakter der Community, nicht die Biografie der einzelnen Pflanze.
- **Phase 13 — Die Stimme ✓:** `voice.py` gibt der Pflanze eine eigene Sprache in
  der ersten Person — `read_state()` liest einen groben, diskreten `VoiceState`
  aus Körper und Feuchtigkeit, und jede Zeile (Überschrift, Absatz, Meilenstein,
  Keimungsgruß, Presence) wird deterministisch aus `blake2b(seed | Kategorie |
  Zustand)` aus einem Pool gezogen. Dadurch bleibt der Text über beliebig viele
  Herzschläge und über Neustarts hinweg stabil und ändert sich nur bei echten
  Übergängen. Verbindlich dokumentiert unter „Die Stimme der Pflanze
  (Persona-Bibel)"; Betriebsmeldungen bleiben ausdrücklich sachlich. Diese Phase
  steht **quer** zur Signal-Roadmap: sie ändert keine Mechanik, kein Rendering
  und kein Vitalitätssignal, nur was gesagt wird.
- **Phase 14 — Die Präsentation ✓:** `presentation.py` gibt dem *Rahmen* um die
  Pflanze dieselbe Absicht, die das gerenderte Bild längst hat. `life_event()`
  verdichtet den Zustand zu genau einem `LifeEvent`, und jedes Event bekommt eine
  eigene Akzentfarbe, eine eigene Feldstruktur und eine eigene Bildplatzierung —
  keine Vorlage mit ausgetauschten Werten. Wie `voice.py` ist das Modul **reine
  Logik**: es liefert ein `Panel`, und `bot.py` gießt das in vier Zeilen in ein
  `discord.Embed`. Verbindlich dokumentiert unter „Präsentation"; diese Phase
  steht wie Phase 13 **quer** zur Signal-Roadmap und ändert weder Mechanik noch
  Rendering noch ein Vitalitätssignal — nur, wie das Gesagte dasteht.
- **Phase 15 — Reaktionen (Blütenintensität) ✓:** dritte Vitalitätsdimension,
  aber anders geformt als Autorenbreite und Rhythmus: `structure.
  _bloom_intensity` wird nicht laufend fortgeschrieben, sondern genau einmal
  gelesen — auf dem Schritt, an dem eine bereits durch Phase 9s Reserve-/
  Reifegrenze verdiente Blüte beginnt — und bleibt danach für die gesamte
  Blütendauer fest in `LifeStats.bloom_intensity`. Ob überhaupt geblüht wird,
  bleibt allein Phase 9s Sache; Reaktionen entscheiden nur, wie üppig und
  gesättigt diese eine Blüte ausfällt (`render.py`s `_draw_blossom`: Anteil
  blühender Triebspitzen und Blütengröße; `presentation.py`s `_bloom_accent`:
  Blassheit Richtung Schnee). Die zugrunde liegende Reaktionswärme wird über
  `structure.author_breadth` gelesen — bewusst wiederverwendet statt einer
  zweiten Kalibrierungsachse —, nur über `storage.py`s neuer
  `reactor_presence`-Tabelle statt über Autor:innen, mit derselben
  Person-Fenster-Falloff-Anti-Farming-Kurve wie beim Gießen. Eine
  Selbstreaktion (Autor:in reagiert auf die eigene Nachricht) zählt über
  `bot.py`s `on_raw_reaction_add` nichts, nicht einmal abgeschwächt; eine
  kleine Gruppe, die sich gegenseitig Reaktionen zuschiebt, zählt nie mehr als
  ihre eigene, kleine Kopfzahl an unterscheidbaren Stimmen — dieselbe
  Anti-Clique-Eigenschaft, die `author_breadth` gegen Nachrichtenflut schon
  hat. Eine gesunde, aber sozial stille Pflanze wird dadurch nie um eine
  verdiente Blüte gebracht, blüht nur bescheiden (`BLOOM_INTENSITY_FLOOR`).
  `voice.py` bekommt dafür zwei getrennte Pools (`_BLOOM_VIVID`,
  `_BLOOM_MODEST`) statt eines geteilten mit eingesetzten Werten. Reagieren
  während einer bereits offenen Blüte ändert deren Intensität nicht mehr — es
  gibt absichtlich keinen laufenden, taktweise beobachtbaren Wert.
- **Phase 16 — Threads (Verzweigungstiefe) ✓:** vierte Vitalitätsdimension,
  und wieder ein anderer Hebel als alle drei davor: `structure.
  _depth_exponent` skaliert, wie stark die Verzweigungswahrscheinlichkeit mit
  der Verzweigungsordnung abklingt (`BRANCH_ORDER_DECAY ** (order *
  depth_exponent)` in `grow()`), statt wie `author_breadth` die Chance an
  jeder Ordnung gleichermaßen zu skalieren (Breite) oder wie `temporal_rhythm`
  das Winkelrauschen zu skalieren (Symmetrie). Bei `order == 0` (dem Stamm)
  hat Threads-Tiefe dadurch grundsätzlich keine Wirkung — ein Discord-Thread
  ist strukturell ein Gespräch, das vom Stamm abzweigt und eine Weile ein
  eigenes Leben führt, also genau das, was ein sich selbst weiter
  verzweigender Seitenast auch ist. `structure.thread_qualifies` lässt einen
  Thread nur zählen, wenn mindestens `THREAD_MIN_PARTICIPANTS` unterschiedliche
  Personen je mindestens `THREAD_MIN_MESSAGES_PER_PARTICIPANT` Nachrichten
  darin geschrieben haben und die Spanne zwischen erster und letzter
  Nachricht mindestens `THREAD_MIN_SPAN_SECONDS` beträgt — eine einzelne
  zusätzliche Nachricht eines sonst stillen Zweitaccounts genügt also nicht,
  und ein im selben Moment geposteter Schwall auch nicht. `structure.
  thread_depth` zählt, wie viele so qualifizierte Threads gerade noch
  innerhalb von `THREAD_RECENCY_SECONDS` aktiv waren, und sättigt bei
  `THREAD_DEPTH_SATURATION_THREADS` — bewusst weit unter
  `BREADTH_SATURATION_VOICES`, damit ein kleiner, aber wirklich
  Thread-lastiger Server nicht an einer für viel größere Server bemessenen
  Kopfzahl scheitert. Anders als Autorenbreite ist der neutrale Startwert
  (`NEUTRAL_THREAD_DEPTH`) keine Bestrafung, sondern der Normalfall: die
  allermeisten Server nutzen Threads nie, und das darf nie dauerhaft gegen
  sie ausgelegt werden — Tiefe bewegt sich daher ausschließlich von neutral
  nach oben, nie darunter (mathematisch erzwungen: `_depth_exponent` liefert
  bei `thread_depth <= NEUTRAL_THREAD_DEPTH` immer exakt `1.0`, also
  `BRANCH_ORDER_DECAY`s unverändertes Vor-Phase-16-Verhalten). Die
  zugrundeliegenden Rohdaten liegen in `storage.py`s neuer
  `thread_activity`-Tabelle (`guild_id, thread_id, author_id` →
  Nachrichtenzahl, erste und letzte Nachricht), gefüttert über `bot.py`s
  `on_message` (für jede tatsächliche Nachricht in einem Thread) und
  `on_thread_create` (verankert die Lebensspanne an der tatsächlichen
  Thread-Erstellung statt erst an der ersten verfolgten Nachricht) — beides
  Standard-Gateway-Events ohne jeden privilegierten Intent. Anders als
  `author_presence`/`reactor_presence` trägt die Tabelle kein zerfallendes
  Gewicht, sondern einfache Zähler und Zeitstempel: das kurze Leben eines
  Threads ist eine andere Datenform als andauernde Präsenz, kein Grund, die
  Zerfallsmaschinerie zweckzuentfremden. Bei Tod/Wiedergeburt wird
  `thread_activity` **nicht** geleert — wie Rhythmus beschreibt es eine
  Gewohnheit der Community, nicht die Biografie der einzelnen Pflanze; ein
  Nachfolger darf vom ersten Takt an so tief verzweigen wie sein Vorgänger.
  `voice.py` und `presentation.py` bleiben unverändert: wie Autorenbreite und
  Rhythmus ist Threads-Tiefe ein stiller Form-Modifikator ohne eigenen
  Zustand, den die Pflanze trägt oder ansagt — kein neuer Meilenstein wie
  Blüte, also auch kein neuer Text-Pool und kein neues Embed-Feld.
- **Phase 17 — Sprachaktivität (Wurzelwerk / Stammfuß) ✓:** fünfte
  Vitalitätsdimension, und die einzige, die `grow()` **überhaupt nicht**
  erreicht. Text, Reaktionen und Threads sind alle im Kanal sichtbar;
  gemeinsam verbrachte Zeit im Sprachkanal ist die parallele, ungesehene
  Hälfte des Serverlebens — also treibt sie das Wurzelwerk und die
  Verdickung des Stammfußes in `render.py` an (`structure.root_spread`,
  gereicht wie `moisture` als Erscheinungs-Modulation über einen
  unveränderten Körper), nichts am Verzweigungsmodell. Genau daraus folgt
  die Unabhängigkeit von Autorenbreite, Rhythmus und Threads-Tiefe
  **konstruktiv statt kalibriert**: die drei teilen sich `grow()`s
  Zweig- und Winkelterme und mussten gegeneinander in Vier-Ecken-Tests
  freigeprüft werden — Sprachaktivität hat mit keiner von ihnen einen Term
  gemeinsam, durch den sie überhaupt interferieren könnte.
  `structure.voice_is_audible` und `structure.shared_voice_seconds`
  definieren, was als echte Sprachaktivität zählt: Zeit läuft **nur**,
  solange mindestens `VOICE_MIN_AUDIBLE` (zwei) Personen gleichzeitig
  *hörbar* im selben Kanal sind — stumm, taub oder im AFK-Kanal der Guild
  zählt exakt wie „gar nicht verbunden", nicht als Abschlag. Damit ist die
  Anti-Farming-Eigenschaft hier schärfer als bei allen Textsignalen: dort
  ist sie eine *Deckelung* des Beitrags einer Person, hier ist
  Gleichzeitigkeit gefordert, die ein einzelnes Konto gar nicht herstellen
  kann — wer allein acht Stunden täglich im Kanal sitzt, erzeugt niemals
  auch nur ein Gramm Präsenzgewicht. Je `VOICE_CREDIT_SECONDS` (15 min)
  geteilter Zeit entsteht ein Credit, der durch dieselbe
  Person-Fenster-Falloff-Kurve wie das Gießen läuft
  (`moisture.next_watering`); der Rest wird übertragen
  (`structure.voice_credits`), damit ein Abend aus mehreren kurzen
  Gesprächen genauso viel wert ist wie ein einzelnes langes. Die
  Präsenzgewichte liegen in `storage.py`s neuer `voice_presence`-Tabelle,
  gefüttert über `bot.py`s `on_voice_state_update` — ein
  Standard-Gateway-Event: `discord.Intents.default()` **enthält
  `voice_states` bereits** (privilegiert sind nur `members`, `presences`,
  `message_content`, alle drei bleiben aus), diese Phase fordert also wie
  jede vorige keinen neuen Intent und stößt an keine Verifizierungsgrenze.
  Gelesen wird die Breite über `structure.author_breadth` — bewusst
  wiederverwendet statt einer dritten Kalibrierungsachse, exakt wie bei
  Phase 15; die gesamte spezifische Kalibrierung sitzt stattdessen in
  `root_spread`. Dessen Kurve *ist* der Entwurf dieser Phase: unterhalb von
  `VOICE_ROOT_THRESHOLD` (0.5, also unter drei getragenen Stimmen) exakt
  `0.0` — nicht wenig, keins; darüber mit `VOICE_ROOT_EXPONENT` (2)
  potenziert, sodass vier Stimmen etwa ein Zehntel, fünf etwa vier Zehntel
  und erst sechs die volle Wirkung ergeben. Gemessen: bei voller Sättigung
  bewegen sich **0,9 % der Bildfläche**, sämtlich unterhalb von 71 % der
  Bildhöhe (Vergleichsmaßstab: ein Feuchtigkeitswechsel bewegt 10,8 %); ein
  Duo, das täglich telefoniert, bewegt exakt **null Bytes**. Weil jedes
  Wurzel-Visual rein additiv auf `0.0` aufsetzt, ist „kein Voice" nicht auf
  das Vor-Phase-17-Bild *kalibriert*, sondern byteidentisch damit — dieselbe
  erzwungene Art von Nulleffekt, die `_depth_exponent` unterhalb seines
  Neutralpunkts liefert. Bei Tod/Wiedergeburt wird `voice_presence`
  **geleert**, zusammen mit `author_presence` und `reactor_presence` und
  anders als `daily_activity`/`thread_activity`: die drei Präsenztabellen
  beschreiben *Menschen um eine bestimmte Pflanze herum*, die beiden
  Zähler-Tabellen dagegen Ereignisse, die eine Community produziert. Bei
  Wurzeln ist das die wörtlichste Fassung dieser Unterscheidung — ein
  Nachfolger kann das Wurzelwerk seines Vorgängers nicht erben, und als
  einzelner Keimling hat er ohnehin keinen Stamm zum Verbreitern.
  `voice.py` und `presentation.py` bleiben unverändert — und das ist hier
  keine Sparsamkeit, sondern der Entwurf: eine Dimension, die absichtlich
  verborgen bleibt und den belohnen soll, der genau hinsieht, darf sich
  nicht selbst ansagen. Eine Textzeile dafür wäre außerdem entweder ein
  fünftes diskretes Band, das den ansonsten stabilen Text mitwandern ließe
  (siehe „Tick-Stabilität"), oder eine Zahl — beides verboten.

**Offen:**

- **Phase 10 (optional) — Die Umwelt:** Tages- und Jahreszeit-Tönung des
  gerenderten Bildes. Noch nicht begonnen — in `render.py` gibt es aktuell
  keine Zeit- oder Jahreszeit-Tönung.
- **Weitere, noch unbenannte Phasen:** zusätzliche Vitalitätssignale (siehe
  „Zulassungstest für ein neues Vitalitätssignal" oben) und die botanischen
  Dimensionen, die sie antreiben — z. B. Kanalbreite.

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
│                        #   Dieback/Narben, Tod & Nachfolge, Blüte/Samen/Epiphyte,
│                        #   Autorenbreite (author_breadth), zeitlicher Rhythmus
│                        #   (temporal_rhythm), Blütenintensität (_bloom_intensity),
│                        #   Threads-Verzweigungstiefe (thread_qualifies, thread_depth),
│                        #   Sprachaktivität (voice_is_audible, shared_voice_seconds,
│                        #   voice_credits, root_spread — treibt nur render.py, nie grow())
│                        #                            [Phase 5–9, 11, 12, 15, 16, 17]
├── voice.py             # REINE LOGIK: die Stimme der Pflanze — VoiceState, Text-Pools,
│                        #   deterministische Auswahl (siehe Persona-Bibel)  [Phase 13, 15]
├── presentation.py      # REINE LOGIK: der Rahmen um die Pflanze — LifeEvent, Akzentfarbe,
│                        #   Feldstruktur, Bildplatzierung, Footer (siehe „Präsentation");
│                        #   liefert ein Panel, kein Embed                  [Phase 14, 15]
├── render.py            # Struktur → PNG via Pillow (gekapselte I/O); Wurzelwerk und
│                        #   Stammfuß-Verbreiterung aus root_spread   [Phase 2, erweitert 5–9, 15, 17]
├── storage.py           # SQLite: Struktur, Seed, Lebensstatistik, Lineage, Feuchtigkeit,
│                        #   Kanal/Nachricht, dead_ticks, author_presence, daily_activity,
│                        #   reactor_presence, thread_activity, voice_presence
│                        #                        [Phase 3, erweitert 5–9, 11, 12, 15, 16, 17]
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
| Autorenbreite (Anzahl verschiedener Stimmen) → Verzweigungsgrad der Krone | **live** (`structure.author_breadth`, `grow()`, Phase 11) |
| Zeitlicher Rhythmus (Gleichmäßigkeit der Tagesaktivität) → Wuchsform/Symmetrie | **live** (`structure.temporal_rhythm`, `grow()`, Phase 12) |
| Reaktionen (Breite der reagierenden Stimmen) → Blütenintensität | **live** (`structure._bloom_intensity`, `grow()`, Phase 15) |
| Threads (qualifizierte, andauernde Nebengespräche) → Verzweigungstiefe | **live** (`structure.thread_depth`, `grow()`, Phase 16) |
| Sprachaktivität (geteilte, hörbare Zeit im Sprachkanal) → Wurzelwerk / Stammfuß | **live** (`structure.root_spread`, `render.py`, Phase 17) |
| Kanalbreite (wie viele verschiedene Kanäle aktiv sind) → eigene Dimension | entworfen, noch nicht gebaut |

Jedes „entworfen, noch nicht gebaut"-Signal muss vor der Implementierung den
Zulassungstest oben bestehen (keine privilegierten Intents, akkumuliert über
echte Zeit, für eine Einzelperson nicht farmbar).

## Reine Logik ⟷ I/O (das Herz der Struktur)

- **Reine Funktionen** (`moisture.py`, `structure.py`, `voice.py`,
  `presentation.py`): deterministisch, ohne
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
  (Phase 1). Eng begrenzte Ausnahme seit Phase 17: wo eine Zusage *über das
  gezeichnete Bild* geprüft werden muss und in reiner Logik gar nicht
  formulierbar ist — „ohne Signal byteidentisch mit vorher", „bewegt unter
  x % der Bildfläche" —, darf ein Test `render` importieren. Das verletzt den
  Zweck der Regel nicht (Testbarkeit ohne discord.py); Pillow ist kein
  Gateway. Solche Tests gehören in einen eigenen, als solchen beschrifteten
  Abschnitt am Ende der Datei, nie verstreut zwischen die reinen.
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

## Die Stimme der Pflanze (Persona-Bibel)

Die Sprache des Bots ist genauso Leinwand wie das gerenderte Bild. Dieser
Abschnitt ist für die Texte, was das Nord-Schema für die Grafik ist: die
verbindliche Referenz, die dafür sorgt, dass Dutzende einzelner Strings **eine**
Stimme bleiben statt ein Haufen unabhängig hübscher Sätze. Alle Pools liegen in
`voice.py`; kein nutzersichtbarer Pflanzentext gehört je wieder als Literal nach
`bot.py`.

### Wer spricht

Die Pflanze selbst, in der **ersten Person** — „I", niemals „the plant", „your
server's plant" oder „it". Sie beschreibt ihren eigenen Zustand als Erlebnis,
nicht als Statusmeldung: sie *hat Durst*, sie meldet keine Feuchtigkeit. Sie
weiß nichts über die Maschinerie, in der sie läuft, und redet entsprechend nie
darüber.

### Register

Nüchtern, körperlich, unsentimental. Kurze Aussagesätze, oft zwei pro Zeile, bei
denen der zweite den ersten hart qualifiziert („I am withered. I am not gone.
Those are different things."). Sinnlich verankert in Wasser, Licht, Holz, Blatt,
Boden und **Zeit** — die Pflanze denkt in Wochen und Jahreszeiten, nie in
Minuten. Sie ist ehrlich bis zur Unfreundlichkeit über sich selbst, inklusive
Sterben und Narben. Kein Ausrufezeichen, keine Niedlichkeit, kein Zwinkern zum
Publikum, keine Whimsy um ihrer selbst willen. Den Raum darf sie direkt
ansprechen („Come back.") — sparsam, das ist ihr stärkstes Mittel.

### Was sie nie tut

- **Nie** Discord-Mechanik benennen: keine channels, messages, servers, guilds,
  bots, commands, embeds, users. Metonyme dafür sind erlaubt und erwünscht —
  „this room", „voices", „the quiet", „being talked near".
- **Nie** aus der Rolle in technische Sprache fallen: keine Zahlen, Prozente,
  Schwellwerte, Ticks oder Modulnamen im gesprochenen Text.
- **Nie** über sich in der dritten Person reden.
- **Nie** denselben Satz sichtbar wiederholen: jede Kategorie hat einen Pool, und
  eine Überschrift wiederholt nie wörtlich eine Formulierung aus dem Absatz
  darunter (das liest sich als Stottern — `test_voice.py` bewacht beides).
- **Nie** etwas versprechen, das die Mechanik nicht hält („water me and I will
  bloom tomorrow").

### Gesprochen vs. sachlich (die Grenze)

Bewusst gezogen und nicht zu verwischen: **Zustände der Pflanze sprechen,
Betriebsmeldungen nicht.** Wer als Moderator ein Rechteproblem sucht, darf nie
Poesie entschlüsseln müssen, um zu verstehen, was kaputt ist.

| Fläche | Stimme |
|---|---|
| Überschrift und Text der lebenden Nachricht (Wachstum, Dürre, Tod, Wiedergeburt) | **gesprochen** |
| `/plant`-Momentaufnahme (dasselbe Embed) | **gesprochen** |
| Meilensteine — Blüte, Samen, Epiphyte | **gesprochen** |
| Erste Keimung nach der Bestätigung | **gesprochen** (eine Zeile) + ein sachlicher Satz daneben |
| Statuszeile des Bots (Presence) | **gesprochen**, aber rotierend (siehe unten) |
| Fehlende Rechte, unerreichbarer Kanal, Kanal binden/umziehen | sachlich |
| `/help`, Persistenz-Hinweis, DM-Absage, abgelaufene Dialoge | sachlich |
| Embed-Felder (Moisture, Stage, Age, Generation, Lived) | sachlich — Instrumente **neben** der Pflanze, nicht ihre Rede |

### Vielfalt ohne Zufall

Jede Kategorie ist ein Pool von mindestens acht gleichwertigen Formulierungen
(Stimmungen: zwölf). Welche gezogen wird, ergibt sich **deterministisch** aus
`blake2b(seed | Kategorie | Zustand)` — bewusst nicht aus `random` und nicht aus
`hash()`, dessen Salt sich pro Prozess ändert: die lebende Nachricht muss nach
einem Neustart dasselbe sagen wie davor, sonst sieht jeder Restart wie ein
Stimmungsumschwung aus. Dieselbe Pflanze im selben Zustand sagt also immer
dasselbe, zwei verschiedene Pflanzen im gleichen Zustand meist Verschiedenes.
Das ist dieselbe Seeded-Determinismus-Regel wie bei `grow()` — und der Grund,
warum die Stimme überhaupt testbar ist.

### Tick-Stabilität

Die lebende Nachricht wird bei **jedem** Herzschlag neu gerendert. Der Text darf
sich dabei nicht mitbewegen — sonst wirkt die Pflanze sprunghaft statt lebendig.
Deshalb liest `voice.read_state()` einen bewusst **groben, diskreten**
`VoiceState` (Stimmung, Größenklasse, Generation, getragene Meilensteine); jede
Zeile ist eine reine Funktion davon. Neuer Text entsteht **nur** bei einem echten
Übergang:

- Feuchtigkeitsband gewechselt (inkl. eigenes Band unterhalb der Dieback-Schwelle),
- eine Größenklasse weiter gewachsen,
- gestorben, oder als Nachfolger wieder gekeimt,
- Blüte, Samen oder Epiphyte gekommen bzw. gegangen.

Alles andere — ein gewöhnlicher Wachstumsschritt, ein paar Prozent Feuchtigkeit,
ein Neustart des Bots — lässt den Text unangetastet. Dafür muss **nichts**
zusätzlich persistiert werden: der Zustand *ist* der Schlüssel. Einzige Ausnahme
ist die Presence-Statuszeile, die die Pflanze nicht als Individuum spricht,
sondern der Bot als Ganzes trägt; sie rotiert auf ihrem eigenen Timer.

### Komponierbarkeit

Ein Absatz ist „Stimmungszeile + Körperzeile". Die Stimmungszeile gehört dem
Wasser und dem Empfinden, die Körperzeile dem Holz und der Größe — keine Hälfte
greift ins Thema der anderen. Nur so bleibt jede Paarung lesbar, und nur so
klingt eine Aussage über die Krone nicht absurd auf einem Keimling. Stimmungen
sprechen deshalb nie über Größe, Kapitel nie über Wasser.

### Offener Vorschlag: Idiolekt (nicht gebaut)

Jede Pflanze hat schon ein Genom aus ihrem Seed. Denkbar wäre, aus demselben
Seed auch einen sprachlichen Eigenton abzuleiten — etwa ein wiederkehrendes Bild
oder eine Vokabelneigung, die nur diese eine Pflanze bedient, sodass Server ihre
Pflanze nicht nur an der Form, sondern am Tonfall erkennen. **Kosten:** die Pools
müssten pro Idiolekt-Variante mehrfach existieren oder sich aus Bausteinen
zusammensetzen; beides vervielfacht den Schreibaufwand und macht genau die
Einheitlichkeit angreifbar, die dieser Abschnitt sichert. Bewusst nicht gebaut —
Entscheidung liegt beim Maintainer.

## Präsentation (verbindlich für jede künftige Phase)

Was das Nord-Schema für die Grafik ist und die Persona-Bibel für die Texte, ist
dieser Abschnitt für **den Rahmen um beides**: Akzentfarbe, Feldstruktur,
Bildplatzierung, Footer. Alles davon lebt in `presentation.py` und ist reine
Logik — das Modul liefert ein `Panel`, `bot.py` gießt es in ein `discord.Embed`.
Kein nutzersichtbarer Pflanzen-Rahmen gehört je wieder als ad-hoc
`discord.Embed(...)` nach `bot.py`.

### Die stehende Regel

**Jede künftige Phase, die eine neue Nachricht, ein neues Embed, ein neues Feld
oder einen neuen Meilenstein einführt, entwirft dessen Form und Farbe bewusst
nach dem Muster unten — statt auf ein nacktes Funktions-Embed zurückzufallen.**
Ein neuer Zustand ohne eigene Farbe und ohne eigene Feldstruktur ist genauso
unfertig wie ein neuer Zustand ohne eigenen Text-Pool in `voice.py`. Das ist die
Präsentations-Hälfte derselben Anforderung, die Phase 13 für die Sprache gestellt
hat, und sie gilt ab hier dauerhaft — auch für Phase 10 (Umwelt-Tönung) und jedes
später zugelassene Vitalitätssignal.

### Die vier Prinzipien

1. **Abgeleitet, nie konfiguriert.** Farbe und Form ergeben sich ausschließlich
   aus vorhandenem Zustand — genau wie das Aussehen der Pflanze selbst. Kein
   Theme, kein Style-Parameter, kein Vorschau-Command, keine neue
   Konfigurationsfläche. Der Oberflächen-Minimalismus aus der Emergenz-Regel gilt
   für den Rahmen unverändert. Eine Farbwahl für Nutzer wäre exakt derselbe
   Verstoß wie ein Settings-Menü für die Pflanze.
2. **Ein Lebensereignis, eine Form.** `life_event()` verdichtet den Zustand auf
   genau ein `LifeEvent`, und jedes bekommt eine *eigene* Feldstruktur — nicht
   dieselbe Zeile mit anderen Werten. Die Reihenfolge in `life_event()` ist die
   eigentliche Entwurfsentscheidung und liest sich in vier Stufen: **Ende oder
   Anfang** (Tod, Keimung, Wiedergeburt) schlägt **was gerade passiert** (Dieback,
   Blüte, Dürre, Durst) schlägt **was der Körper geworden ist** (Epiphyte) schlägt
   **den gewöhnlichen Tag** (üppig, stetig). Dauerhafte Zustände rangieren bewusst
   *unter* vorübergehenden: ein Baum, der zum Lebensraum geworden ist, zeigt
   trotzdem seinen Durst, wenn er durstig ist.
3. **Das Instrumenten-Feld öffnet und schließt sich mit der Pflanze.** Vier Felder
   bei Überfluss, drei im Normalfall, zwei bei Durst, eins in der Dürre, keins bei
   Keimung und Tod — an beiden Enden gibt es nichts zu messen, was die Pflanze
   nicht selbst besser gesagt hat. Felder bleiben sachlich (Persona-Bibel,
   „Gesprochen vs. sachlich"); der einzige Feldwert, der je gesprochen ist, ist ein
   über die volle Breite hochgezogener Meilenstein.
4. **Eine leise Konstante darunter.** Der Footer ist das einzige Element, dessen
   *Form* sich nie ändert: seed-abgeleitetes Sigil, Generation, Alter in Tagen,
   dann die dauerhaften Marken (Samen, Epiphyte). Weil Herkunft und Alter dort
   stehen, dürfen die Feldzeilen darüber so frei variieren. Das Sigil folgt
   derselben `blake2b`-Determinismus-Regel wie die Stimme — nie `hash()`, dessen
   Salt pro Prozess wechselt.

### Tick-Stabilität, wie bei der Stimme

Der Rahmen wird bei jedem Herzschlag neu gebaut und darf sich dabei nicht
mitbewegen. Weil Farbe und Form reine Funktionen desselben groben, diskreten
`VoiceState` sind, ändern sie sich nur bei echten Übergängen — dieselben, die auch
den Text neu ziehen. Einzige beabsichtigte Ausnahme ist der Tageszähler im Footer:
er ist ein Instrument, keine Rede.

### Die Grenze zum Bild (nicht verwischen)

`presentation.py` rahmt das gerenderte PNG, es fasst es nie an. Alles innerhalb
des Bildes — Körper, Palette, Laub, Blüten, Narben — gehört allein `render.py`.
Die Bildplatzierung (`ImagePlacement.FULL` vs. `THUMBNAIL`) ist ausdrücklich
erlaubt, weil sie nur den *Slot* in der Nachricht wählt: das PNG ist in beiden
Fällen byte-identisch. Ein getönter oder gerahmter Rand um das fertige Bild wäre
ein Compositing-Schritt *nach* `render.render()` und damit prinzipiell zulässig —
er ist aber **bewusst nicht gebaut** und braucht eine ausdrückliche Entscheidung
des Maintainers, bevor ihn jemand einführt. Solange die Akzentfarbe des Embeds
den Zustand trägt, ist der Rand redundant; er würde nur die Grenze zum Bild
unnötig nah an `render.py` schieben.

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
