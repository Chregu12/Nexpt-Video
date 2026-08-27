# Nexpt-Video

Keynote-Film für **NEXPT Work** — Konzept, Drehbuch und lauffähige Render-Pipeline.

| | |
|---|---|
| [**KEYNOTE-FILM-KONZEPT.md**](./KEYNOTE-FILM-KONZEPT.md) | Frame-für-Frame-Analyse des Referenzfilms (Apple, *„Every product carbon neutral by 2030"*), 13 Stil-Regeln, Story, vollständiges Drehbuch, Design-Spezifikation, Produktionsplan. |
| [**render/**](./render/) | Pipeline: `timing.json` → ProRes-Clips → FCPXML. Siehe [render/README.md](./render/README.md). |
| **out/NEXPT-Keynote-ANIMATIC.mp4** | Der komplette Film als Animatic, 2:18, 1920×1080/30p. |
| **out/NEXPT-Keynote.fcpxml** | Timeline für Final Cut Pro, 27 Clips mit Markern. |
| **out/NEXPT-Keynote-ANIMATIC-SCRATCH.mp4** | Dasselbe mit Roboter-Scratchstimme — macht die Textlänge sofort hörbar. |
| **out/NEXPT-Keynote-ANIMATIC-OHNE-STIMME.mp4** | Bild plus Percussion, keine Sprache. Die Standloop-Fassung — und der ehrlichere Blick auf den Rhythmus. |
| **out/scratch-vo.wav** | Die Scratch-Tonspur einzeln. |
| **out/analysis/cue_sheet.json** | Jeder Hit Point des Films: Zeit, Takt.Zählzeit, Szene, Art, Stärke, Stereoposition. Die Vorlage zum Komponieren. |
| `out/_musik/` | Der lizenzierte Musiktrack. **Nicht im Repo** — die Lizenz hängt am Lizenznehmer, nicht am Repository. Eigene Kopie dort ablegen, dann `python3 render/musik.py`. |
| **out/stills/** | Ein Standbild je Szene. |
| `out/scenes/*.mov` | ProRes 422 HQ, ein Clip je Szene. Nicht im Repo (267 MB) — lokal mit `python3 render/render.py` erzeugen. |

## Schnellstart

```bash
pip install playwright && python3 -m playwright install chromium
python3 render/render.py        # ProRes-Clips
python3 render/fcpxml.py        # FCP-Timeline
python3 render/sync.py <vo.wav|Projekt.fcpxml>   # Timing auf die echte Stimme ziehen
```

Ton und Zusammenbau, mit der Stimme als Schalter:

```bash
python3 render/cuesheet.py                        # Hit Points -> out/analysis/cue_sheet.json
python3 render/sfx.py                             # Whooshes, Clicks, Impacts, Riser
python3 render/musik.py                           # Musik auf den Film legen
sh render/mischen.sh                              # Mischung mit Stimme
sh render/mischen.sh --ohne-stimme                # Mischung ohne Stimme
sh render/mischen.sh --drums                      # zusätzlich eigene Percussion (aus)
sh render/mischen.sh --ohne-effekte               # zum Vergleich, ohne Sounddesign
python3 render/bauen.py                           # Film mit Stimme
python3 render/bauen.py --ohne-stimme             # Film ohne Stimme
```

Produktgrundlage: [Chregu12/Nexpt-2.0](https://github.com/Chregu12/Nexpt-2.0) — `apps/nexpt-work`.
