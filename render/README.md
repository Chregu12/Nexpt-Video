# Render-Pipeline

Erzeugt aus `timing.json` ProRes-Clips und ein FCPXML für Final Cut Pro.

## Voraussetzungen

```bash
pip install playwright piper-tts faster-whisper
python3 -m playwright install chromium     # oder vorhandenes Chromium via CHROME= setzen
sh render/voices/get-voices.sh             # deutsche Stimmmodelle (~200 MB)
# ffmpeg mit prores_ks (jedes aktuelle ffmpeg; auf macOS: brew install ffmpeg)
```

## Benutzung

```bash
python3 render/render.py                 # alle 27 Szenen → out/scenes/*.mov  (ProRes 422 HQ)
python3 render/render.py 15 22           # nur diese Szenen (Nummer oder id-Fragment)
python3 render/render.py --stills        # nur je ein Standbild pro Szene (Sekunden statt Minuten)
python3 render/render.py --alpha         # ProRes 4444 mit Alpha statt 422 HQ
python3 render/fcpxml.py                 # → out/NEXPT-Keynote.fcpxml
python3 render/scratchvo.py              # → out/scratch-vo.wav (Wegwerf-Stimme zum Timing-Check)
python3 render/sync.py <datei>           # Timing auf die echte Stimme ziehen — siehe unten
python3 render/pruefen.py                # Tempo und leere Frames prüfen  (--fix repariert)
python3 render/bauen.py                  # prüfen und zusammenbauen (--check nur prüfen)
python3 render/drehbuch.py               # Abschnitt 4 des Konzepts aus timing.json erzeugen
python3 render/sounddesign.py            # Musikbett + Effekte aus timing.json
sh render/mischen.sh                     # Stimme, Musik, Effekte → out/ton-final.wav
```

## Ton aus denselben Daten wie das Bild

`sounddesign.py` erzeugt Bett und Akzente aus `timing.json`. Die Gestaltung folgt der
**Messung des Referenzfilms**, nicht der Vermutung:

| gemessen an `apple.wav` (75.8 s) | Ergebnis |
|---|---|
| Energie an 15 Bildschnitten | Median **0.80× / 0.50× / 0.52×** — sie *fällt*. Kein Sounddesign auf Bildereignissen. |
| Periodizität, perkussiv (HPSS) | **119.7 BPM, Stärke 0.104** — vorhanden, aber sehr frei gespielt |
| leiseste Fenster (−41 dB) | Dauerton **156–160 Hz (Es3)** → getragene Fläche |
| Spektrale Neigung | Sub 57, Bass 59, Tiefmitten 55, Mitten 47, Höhen 39, Luft 30 dB |
| Schluss | bei 68.0 s **absolute digitale Stille** |

**Der Track ist identifiziert:** „Rhythm Mischief" von Cold Storage Percussion Unit,
~118 BPM — Drumline-Snare, Toms, Rim Clicks, kurze gedämpfte Schläge, mit Free-Jazz-Freiheit.

**Zwei Fehlschlüsse meinerseits, beide dokumentiert:** Mein erster Test suchte nach
Perkussion mit einem Regelmässigkeits-Kriterium (>0.6) — daran wäre auch ein echter
Schlagzeuger gescheitert; frei gespielte Drumline-Percussion ist absichtlich unregelmässig.
Mein zweiter Test suchte nach einem Melodieinstrument und fand einen Bass, wo Percussion war.

Daraus gebaut: eine sehr leise Fläche mit sparsamer Melodiefigur, darüber eine
**Drumline-Percussion** auf 118 BPM. Der Groove läuft, die **Akzente sitzen auf den
Bildereignissen** aus `timing.json` — Snare auf jeden Hintergrundwechsel, Rim Click auf
jeden Marker, gedämpfter Schlag auf jede der fünf Stufen, Tom auf den Etikettwechsel,
Wirbel in den Strich durchs Raster hinein.

**Viel Leerraum:** 18 Muster, davon die Hälfte leer oder fast leer, dazu eingestreute
Aussetzer von ein bis zwei Takten. Anschlagstärke und Versatz schwanken je Schlag, sonst
klingt es wie ein Drumcomputer. Gemessene Regelmässigkeit: **0.283** — von 0.665 in der
ersten Fassung heruntergearbeitet; das Original liegt bei 0.104.

Effekte nur als seltene Akzente:

```bash
python3 render/sounddesign.py              # drei Akzente (NEIN., Raster, Etikettwechsel)
python3 render/sounddesign.py --sfx none   # ganz ohne — Apples Fassung
python3 render/sounddesign.py --sfx full   # die alte, dichte Fassung zum Vergleich
```

`mischen.sh` mischt auf **−17 LUFS**. Drei Filter nähern die Frequenzneigung an; bewusst
moderat, weil der Bassüberschuss von der Sprecherstimme kommt (Grundtöne 100–250 Hz) und
sich nicht wegfiltern lässt, ohne sie dünn zu machen. Ab den Mitten aufwärts liegt die
Abweichung bei 1.5–3.8 dB.

**Die Musik des Referenzfilms wird nicht kopiert** — sie ist eine geschützte Komposition.
Nachgebaut ist ihr Charakter, gemessen statt geraten.

## Zusammenbauen nur mit `bauen.py`

Drei Fehler sind mir beim Zusammenbau mehrfach passiert; `bauen.py` fängt alle drei ab und
verweigert im Zweifel den Bau:

1. **Zusammenbau gestartet, während der Render noch lief** — halb geschriebene Clips landeten
   im Film (einmal wurde daraus eine 41-Sekunden-Datei). Ursache war jedes Mal ein `&` oder
   `nohup … &` in einem ohnehin im Hintergrund laufenden Befehl, wodurch er sofort zurückkam
   und fälschlich „fertig" meldete.
2. **Clips gestrichener Szenen** lagen noch im Ordner und liefen mit.
3. **Clips waren vollständig, aber veraltet** — die Dauerprüfung greift dort nicht, wenn sich
   nur Farben oder Positionen geändert haben. Deshalb prüft `bauen.py` zusätzlich, ob jeder
   Clip **jünger als `timing.json` und `film.html`** ist.

## Vor jeder Abnahme: `pruefen.py`

Zwei Fehlerklassen sieht man im Standbild **nicht**, im Lauf aber sofort:

1. **Leere Frames.** Eine Zeile verschwindet, bevor die nächste kommt — ein sichtbarer
   Aussetzer von zwei, drei Frames. Beim ersten Durchgang waren es 62 Stück.
   `pruefen.py --fix` schliesst sie, indem es `out` bis zum nächsten Layer-Start zieht.
2. **Stillstand.** Löcher ohne jedes Ereignis. Fünf Beats *dürfen* still stehen — dort ist
   die Stille die Pointe (`Moment./Nein.`, beide geflüsterten Einwürfe, `NEIN.`,
   `(auch nicht im UI)`). Sie stehen in der Liste `HALT` und werden übersprungen.

Dazu die Tempokontrolle gegen den Referenzfilm. Wichtig: die Prüfung zählt auch die
**einzelnen Wörter** eines Wort-für-Wort-Aufbaus — wer nur Layer-Startzeiten zählt,
misst sich um den Faktor drei zu langsam.

## Dateien

| Datei | Zweck |
|---|---|
| `timing.json` | **Die einzige Datei, die nach der VO-Aufnahme angefasst wird.** Alle Zeiten, Texte, Layer. |
| `film.html` | Render-Engine. `window.renderAt(t)` ist deterministisch — gleiche `t` ergibt bitgleichen Frame. |
| `render.py` | Playwright → PNG-Frames → ffmpeg → ProRes, ein Clip je Szene. |
| `fcpxml.py` | Timeline mit Markern für Akt, Szene und Sprechertext. |
| `fonts/` | **Prototyp-Schriften** (Inter SemiBold, Permanent Marker). Für die Endfassung ersetzen — siehe unten. |

## In Final Cut Pro

1. `out/` als Ganzes auf den Mac kopieren. **`NEXPT-Keynote.fcpxml` muss neben dem Ordner
   `scenes/` liegen** — die Pfade im XML sind relativ.
2. Ablage → Importieren → XML … → `NEXPT-Keynote.fcpxml`.
3. Es entsteht ein Projekt mit 27 Clips auf der Spine, je Clip Marker mit Akt, Szenen-ID
   und Sprechertext.
4. Off-Stimme als Audiospur darunter legen.
5. **Szenen einzeln auf die Stimme schieben.** Genau dafür liegt jede Szene als eigener Clip
   und nicht als eine durchgehende Datei.
6. Die neuen Ist-Zeiten zurück in `timing.json` schreiben und neu rendern — dann sitzt jede
   Animation frame-genau auf der echten Stimme.

## Die Stimme passend machen — ohne stundenlang zu schieben

`sync.py` schreibt die gemessenen Ist-Zeiten in `timing.json` zurück. Danach einmal
`render.py`, und **jede Animation sitzt frame-genau auf der echten Stimme.** Zwei Wege:

### Weg A — aus dem Schnitt zurücklesen *(massgeblich)*

Du hörst, der Code rechnet nach. Du schiebst in FCP nach Gefühl, bis es sitzt, exportierst
das Projekt als XML und lässt die Animation nachziehen:

```bash
# in FCP:  Ablage → Exportieren → XML …   → Projekt.fcpxml
python3 render/sync.py Projekt.fcpxml
python3 render/render.py
```

Der Umlauf ist verlustfrei geprüft: exportiert und zurückgelesen ergibt bit-identische Zeiten.
Das ist der Weg, dem man trauen kann — er rät nichts.

### Weg B — die Tonspur vermessen *(erster Wurf)*

```bash
python3 render/sync.py vo.wav
```

**Whisper hört die Aufnahme ab** und liefert Wort-Zeitstempel. Die erkannten Wörter werden
gegen das Drehbuch abgeglichen (`difflib`, verträgt Erkennungsfehler), und daraus steht fest,
wo jede Szene beginnt — unabhängig davon, wo der Sprecher Luft geholt hat. Am Scratch-Take
gemessen: 96 % der Drehbuchwörter zugeordnet.

Das Werkzeug meldet die Deckungsquote, prüft jede Szene auf Plausibilität und **weigert
sich zu raten**, wenn unter 55 % zugeordnet werden. Optionen: `--model medium` (genauer,
langsamer), `--silence` (ohne Whisper, nur Pausenmessung), `--dry` (nur zeigen).

**Weg B ist der schnelle erste Wurf, Weg A die Wahrheit.** Whisper kann sich verhören;
FCPXML kann es nicht.

### Stimme erzeugen — und was nicht geht

| Werkzeug | Status |
|---|---|
| **Piper** (`scratchvo.py`) | läuft, offline, CPU. Frei nutzbar. **Standard.** |
| **XTTS-v2** (`xttsvo.py`) | läuft, aber nur in einem eigenen venv — es ist mit der Whisper-Toolchain (transformers 5.x) nicht verträglich. **Coqui Public Model License: nicht kommerziell.** Nur als internes Timing-Muster. |
| **Qwen3-TTS** (`qwenvo.py`) | lokal **nicht** lauffähig — weder `transformers 5.16` noch git main kennen den Typ `qwen3_tts`. **Über den offiziellen HF-Space aber schon**, auf GPU. Braucht ein kostenloses `HF_TOKEN`; anonym reicht die Quote für rund einen Aufruf. Schickt den Text an einen öffentlichen Dienst. |
| **ElevenLabs** | echtes TTS, kommerziell nutzbar — braucht einen API-Schlüssel und schickt den Text an einen externen Dienst. |
| *Whisper-Modelle* | **erzeugen keine Stimme.** Sie erkennen Sprache — siehe Synchronisation oben. |

#### Qwen3-TTS über den Space

```bash
export HF_TOKEN=hf_...                    # huggingface.co/settings/tokens, Read genügt
python3 render/qwenvo.py                  # fester Sprecher, über alle Zeilen gleich
python3 render/qwenvo.py --speaker Dylan --size 0.6B
python3 render/qwenvo.py --design         # Stimme aus einer Beschreibung
```

Drei Endpunkte stehen zur Verfügung: `generate_custom_voice` (neun feste Sprecher plus
Regieanweisung), `generate_voice_design` (Stimme aus einer Beschreibung) und
`generate_voice_clone`.

**Für eine durchgehende Sprecherstimme den festen Sprecher nehmen.** `voice_design` erzeugt
die Stimme bei jedem Aufruf neu — über 31 Zeilen kann sie abweichen. Die Regieanweisung ist
dieselbe wie im Drehbuch: *trocken, wach, leicht amüsiert, kein Werbeton, kein Pathos.*

#### Eigene Stimme klonen

```bash
export HF_TOKEN=hf_...
python3 render/qwenvo.py --ref meine-stimme.wav      # nutzt out/referenztext.txt
python3 render/sync.py out/vo-klon.wav               # Animation darauf ziehen
python3 render/render.py
```

**Qwen3-TTS steht unter Apache 2.0** und darf kommerziell verwendet werden — deshalb der
Weg für den Messefilm. XTTS-v2 (`xttsvo.py --ref`) klont ebenfalls, ist aber nicht
kommerziell lizenziert.

Der Klon-Endpunkt braucht neben der Aufnahme den **exakten Wortlaut** der Referenz. Darum
ist `out/referenztext.txt` aus dem echten Drehbuch gebaut: der Wortlaut steht fest, und die
Stimme ist beim Einsprechen schon im richtigen Register.

**Aufnahme:** ruhiger Raum ohne Hall, 15–25 cm Abstand, leicht seitlich sprechen, ~80
Sekunden am Stück, Hochdeutsch (die Modelle können kein Schweizerdeutsch). Handy-Sprachmemo
genügt.

**Klonen nur mit Einwilligung der sprechenden Person.** Eine fremde Stimme aus einem fremden
Film zu klonen und als eigene Markenstimme einzusetzen, ist keine Option.

### Scratch-Stimme

```bash
python3 render/scratchvo.py                  # neuronale Stimme (Piper, de_DE-thorsten)
python3 render/scratchvo.py --voice kerstin  # oder eva_k
python3 render/scratchvo.py --rate 1.08      # langsamer (>1) / schneller (<1)
python3 render/scratchvo.py --autofit        # zu kurze Szenen automatisch verlängern
```

Nicht für den Film: der Sprecher muss ein Mensch sein — „Moment. Nein." lebt von trockenem
Timing, das keine Synthese trifft. Aber die Spur macht in zwei Minuten **messbar**, welche
Zeile zu lang ist. Der Bericht am Schluss stellt geplant gegen gesprochen:

```
Szene               geplant  gesprochen   Befund
16_pfeile             3.00s       4.26s   ⚠ +1.26s  zu lang
17_hundert            2.00s       3.91s   ⚠ +1.91s  zu lang
25_seht               4.00s       2.87s     -1.13s  viel Luft
```

`--autofit` verlängert die zu kurzen Szenen und schreibt `timing.json` neu — **nur
verlängern, nie kürzen**: „viel Luft" ist oft Absicht, dort läuft nach dem Satz noch eine
Animation (Unterstrich, Stufen, Vokabelflut). Zwei bis drei Durchläufe konvergieren.

## Warum pro Szene ein Clip

Kinetische Typografie muss auf die **aufgenommene** Stimme sitzen, nicht auf die geplante.
Kein Sprecher trifft geplante Timecodes. Ein durchgehender Film müsste nach der Aufnahme
komplett neu animiert werden; 27 einzelne Clips schiebt man in einer halben Stunde zurecht.

## Vor der Endfassung ersetzen

| Was | Warum |
|---|---|
| **Schriften** | Inter und Permanent Marker sind offen lizenziert und für den Prototyp gedacht. Für die Endfassung die NEXPT-Hausschrift eintragen (`@font-face` in `film.html`) und **echte, von Hand geschriebene** Marker-Elemente als SVG einsetzen — der Unterschied ist auf der Leinwand sofort sichtbar. |
| **Akzentfarbe** | `timing.json` → `palette.accent`. Steht aktuell auf Apples `#00D759` als Referenzwert. |
| **B-Roll** | Szene `08_broll` rendert Platzhalter. Die drei echten Makro-Einstellungen in FCP darüberlegen und die Wörter aus dem Clip stehen lassen. |
| **Marker-Striche** | Aktuell prozedural erzeugte, leicht zitternde Linien. Für die Endfassung echte Stiftstriche scannen und als SVG-Pfade einsetzen — besonders bei `22_raster` und `18_aendert`. |
