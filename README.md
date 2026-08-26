# Nexpt-Video

Keynote-Film für **NEXPT Work** — Konzept, Drehbuch und lauffähige Render-Pipeline.

| | |
|---|---|
| [**KEYNOTE-FILM-KONZEPT.md**](./KEYNOTE-FILM-KONZEPT.md) | Frame-für-Frame-Analyse des Referenzfilms (Apple, *„Every product carbon neutral by 2030"*), 13 Stil-Regeln, Story, vollständiges Drehbuch, Design-Spezifikation, Produktionsplan. |
| [**render/**](./render/) | Pipeline: `timing.json` → ProRes-Clips → FCPXML. Siehe [render/README.md](./render/README.md). |
| **out/NEXPT-Keynote-ANIMATIC.mp4** | Der komplette Film als Animatic, 1:14, 1920×1080/30p. |
| **out/NEXPT-Keynote.fcpxml** | Timeline für Final Cut Pro, 27 Clips mit Markern. |
| **out/stills/** | Ein Standbild je Szene. |
| `out/scenes/*.mov` | ProRes 422 HQ, ein Clip je Szene. Nicht im Repo (267 MB) — lokal mit `python3 render/render.py` erzeugen. |

## Schnellstart

```bash
pip install playwright && python3 -m playwright install chromium
python3 render/render.py        # ProRes-Clips
python3 render/fcpxml.py        # FCP-Timeline
```

Produktgrundlage: [Chregu12/Nexpt-2.0](https://github.com/Chregu12/Nexpt-2.0) — `apps/nexpt-work`.
