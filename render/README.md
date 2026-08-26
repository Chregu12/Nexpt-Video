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
