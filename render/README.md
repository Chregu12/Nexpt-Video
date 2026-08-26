# Render-Pipeline

Erzeugt aus `timing.json` ProRes-Clips und ein FCPXML für Final Cut Pro.

## Voraussetzungen

```bash
pip install playwright
python3 -m playwright install chromium     # oder vorhandenes Chromium via CHROME= setzen
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
```

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

Findet die Sprechpausen und legt jede Szene auf ihren ersten Satz. Das Werkzeug weiss, wie
viele Sätze es erwartet (44), sucht die passende Pausenschwelle selbst und **weigert sich zu
raten**, wenn die Zahl nicht aufgeht — dann sagt es das und dehnt ersatzweise global
(`--fit`). Passt es, prüft es zusätzlich jede Szene auf Plausibilität und meldet alles, was
stark vom Plan abweicht. Optionen: `--gap 0.4` (Schwelle vorgeben), `--dry` (nur zeigen).

**Weg B ist der schnelle erste Wurf, Weg A die Wahrheit.** Ein Sprecher pausiert an
Satzenden, nicht an Szenengrenzen — deshalb kann eine verschluckte Pause die Zuordnung
verschieben. Darum meldet das Werkzeug lieber einen Zweifel, als still etwas Falsches
zu liefern.

### Scratch-Stimme

`scratchvo.py` erzeugt aus den `vo`-Feldern eine Roboterstimme auf den geplanten Zeiten.
Nicht für den Film — aber sie macht in zwei Minuten hörbar, wo der Text zu lang ist. Genau
dafür sprechen Regie und Copywriter sonst selbst eine Scratch-Spur ein.

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
