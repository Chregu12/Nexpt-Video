# GarageBand-Weg

Partitur bei uns, Klang aus echten Drum Kits.

## Warum

Dreimal wurde in diesem Projekt Perkussion selbst erzeugt, dreimal klang sie nach
Roboter — Sinus plus gefiltertes Rauschen *ist* ein Roboter, egal wie gut die Noten
sitzen. Die Grenze lag nie bei der Komposition, sondern beim Klangerzeuger.

GarageBand hat echte, aufgenommene Drum Kits. [`garageband-llm-bridge`][bridge] kann
GarageBand fernsteuern. Damit verschiebt sich die Aufgabe dorthin, wo wir tatsächlich
etwas können: **was** gespielt wird, mit welcher Anschlagstärke, und wie weit neben
dem Raster.

[bridge]: https://github.com/extao15/garageband-llm-bridge

## Die Kette — und wo sie läuft

```
render/timing.json  ·  render/bogen.py  ·  out/analysis/groove.json
        │
        │  garageband/compose.py                          überall
        ▼
garageband/scores/nexpt-work-68.json      Score Spec v1
        │
        │  tools/garageband-llm-bridge     score-spec-to-midi    überall
        ▼
garageband/scores/nexpt-work-68.mid
        │
        │  tools/garageband-llm-bridge     make-from-score-spec   NUR macOS
        ▼
GarageBand  →  echtes Drum Kit  →  WAV
```

**Die Trennlinie ist echt, nicht theoretisch.** Die Bridge steuert die installierte
GarageBand-App über AppleScript und die macOS-Bedienungshilfen. Unter Linux gibt es
nichts, was sie fernsteuern könnte — die letzten drei Schritte laufen nur auf einem
Mac mit GarageBand. Alles davor ist reines Python und läuft überall; geprüft.

## Benutzen

```bash
python3 garageband/compose.py --bericht         # Takttabelle ansehen
python3 garageband/compose.py --midi            # Partitur + MIDI schreiben
```

Die Bridge liegt kopiert unter `tools/garageband-llm-bridge/` — nichts zu holen, nichts
zu initialisieren.

Auf dem Mac dann:

```bash
python3 tools/garageband-llm-bridge/garageband_cli.py --pretty \
  make-from-score-spec \
  --file garageband/scores/nexpt-work-68.json \
  --output-dir garageband/arrangements/keynote-68 \
  --export-output garageband/arrangements/keynote-68/drums.wav \
  --export-format WAVE --export-overwrite
```

Das Ergebnis kommt als `out/drumline.wav` zurück ins Projekt und wird mit
`sh render/mischen.sh --drumline` gemischt.

## Woraus die Partitur entsteht

Alles gemessen, nichts geraten:

| Quelle | was daraus kommt |
|---|---|
| `render/timing.json` | 68 Takte bei 118.00 BPM, die Szenengrenzen |
| `render/bogen.py` → `BOGEN` | 25 Abschnitte mit Energie 0…1, jede Grenze an einer Szene abgelesen |
| `out/analysis/groove.json` | Groove MIDI Dataset (Magenta, CC BY 4.0): 220 Aufnahmen, 3408 Takte echter Schlagzeuger — je Instrument und Sechzehntel der mediane Versatz zum Raster, seine Streuung, die mediane Anschlagstärke und wie oft die Position überhaupt gespielt wird |

Der **Versatz** ist die Stelle, an der sich eine Maschine verrät. Gemessen spielt ein
Mensch die Hi-Hat auf der Eins 15.9 ms *vor* dem Raster und auf der Drei 22.2 ms davor
— systematisch vorne, nicht zufällig verwackelt. Genau diese Tabelle wird angewandt,
statt Rauschen auf die Zeiten zu addieren.

Aktueller Stand: 1216 Anschläge, Versatz zum Sechzehntel im Median 12.5 ms.

| Instrument | Anzahl | min | Median | max |
|---|---:|---:|---:|---:|
| closed_hat | 808 | 26 | 45 | 58 |
| kick | 207 | 36 | 93 | 117 |
| snare | 118 | 75 | 99 | 113 |
| rim | 52 | 45 | 49 | 56 |
| Toms | 24 | 74 | 86 | 101 |
| crash | 7 | 70 | 74 | 78 |

Der Pegel je Gruppe steht in `compose.py` (`grund`), die Abstufung *innerhalb* einer
Gruppe kommt aus der Messung. Andersherum — die gemessene Stärke absolut übernehmen —
setzt jede Gruppe ihren eigenen Pegel, und die Bassdrum landet 43 Punkte unter der
Snare, obwohl sie in der Vorlage 78 % der Energie trägt. Das war der erste Versuch.

## Die Bridge liegt kopiert im Repo

`tools/garageband-llm-bridge/` ist eine wortgetreue Kopie von
[`extao15/garageband-llm-bridge`][bridge], Stand `f3d12e8`, MIT-Lizenz. Beim Kopieren
wurde jede Datei per SHA-256 gegen den Upstream-Klon geprüft: 103 Dateien, keine fehlt,
keine weicht ab. Die 129 mitgelieferten Tests laufen hier durch.

Zuerst hing der Ordner als Git-Submodul am Upstream. Das wäre der sauberere Weg,
setzt aber einen eigenen Fork voraus — und der liess sich aus der Arbeitsumgebung
nicht anlegen. Ein Submodul auf ein fremdes Repository zeigen zu lassen ist die
schlechtere von beiden Varianten; jetzt liegen die Dateien direkt hier, und niemand
kann vergessen, sie zu initialisieren.

Herkunft, Lizenzpflichten und der Weg zu einem neueren Stand stehen in
[`tools/garageband-llm-bridge/HERKUNFT.md`](../tools/garageband-llm-bridge/HERKUNFT.md).

**In diesem Ordner wird nichts geändert.** Wer an der Bridge etwas anpasst, kann sie
nicht mehr aktualisieren, ohne die Änderung von Hand nachzuziehen. NEXPT-spezifischer
Code gehört hierher, nach `garageband/`.

## Was hier hineingehört

| | |
|---|---|
| `compose.py` | unsere Partitur — Groove, Humanisierung, Arrangement |
| `scores/` | erzeugte Partituren und MIDI |
| `arrangements/` | GarageBand-Projekte und Exporte (nicht im Repo) |
| `presets/` | Kit- und Kanaleinstellungen, sobald welche stehen |

Die Bridge selbst bleibt unverändert. Alles, was NEXPT-spezifisch ist, gehört
hierher — nicht in die kopierte Bridge.
