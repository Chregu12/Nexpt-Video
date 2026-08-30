# Instrumental-Audio zuerst kopieren, danach in GarageBand bearbeiten

Dieser Modus ist fuer einen anderen Zweck als `garageband/compose.py` gebaut:

| Modus | Ergebnis |
|---|---|
| `compose.py` | neue, nur an der Referenz orientierte Musik |
| `transcribe.py` | dieselbe Ereignisfolge und Dauer als bearbeitbare Rekonstruktion |

Eine fertige Stereo- oder M4A-Datei kann nicht gleichzeitig klanglich exakt
und in ihre urspruenglichen Instrumente zerlegt sein. Im Mix fehlen die
Informationen, welche Samples, Plugins, MIDI-Noten und Automation im
Originalprojekt verwendet wurden. Der neue Ablauf loest das mit zwei Ebenen im
selben GarageBand-Projekt:

1. `REFERENCE — Original 1:1` ist die unveraenderte Quelldatei. Sie ist der
   exakte Klang- und Timingvergleich und wird nach dem Import stummgeschaltet.
2. Darunter liegen rekonstruierte Drums, Bass, Harmonie und Melodie als
   separate MIDI-Spuren. Diese lassen sich im Piano Roll, mit anderen Patches,
   neuen Noten, anderem Arrangement und neuer Mischung bearbeiten.

Damit ist immer sichtbar, was wirklich 1:1 ist und was die editierbare
Transkription ist.

## 1. Analyse-Engines pruefen

```bash
python3 garageband/transcribe.py --doctor
```

Der lokale DSP-Fallback benoetigt nur die normalen Projektabhaengigkeiten. Fuer
komplexe Musik ist der Hochpraezisionsmodus vorgesehen:

- [Demucs](https://github.com/adefossez/demucs) trennt Drums, Bass und den
  uebrigen Mix vor der Transkription.
- [Basic Pitch](https://github.com/spotify/basic-pitch) erkennt polyphone Noten
  im Bass- und Other-Stem.

Basic Pitch unterstuetzt aktuell Python bis 3.11; fuer Apple Silicon nennt das
Projekt Python 3.10. Diese Version ist zugleich mit Demucs kompatibel. Auf dem
Mac:

```bash
python3.10 -m venv .venv-transcribe
source .venv-transcribe/bin/activate
python -m pip install -r garageband/requirements-transcription.txt
python garageband/transcribe.py --doctor
```

Demucs wird mit einem CPU-Job gestartet. Das vermeidet unkontrollierte
Speicherspitzen auf einem Rechner ohne CUDA. Mit Apple-Silicon-Unterstuetzung
kann spaeter gezielt `--device mps` getestet werden; `cpu` bleibt der sichere
Standard.

## 2. Instrumentaldatei transkribieren

Fuer die bestmoegliche Rekonstruktion:

```bash
python garageband/transcribe.py "/Pfad/zu/Instrumental.m4a" \
  --quality high
```

Bei bekanntem Tempo oder Downbeat koennen die Werte fest vorgegeben werden:

```bash
python garageband/transcribe.py "/Pfad/zu/Instrumental.m4a" \
  --quality high --bpm 118 --downbeat 0
```

Fuer reine Percussion oder einen schnellen Lauf ohne ML-Modelle:

```bash
python3 garageband/transcribe.py "/Pfad/zu/Percussion.mp3" \
  --quality fast --content percussion
```

Aus `Instrumental.m4a` entstehen standardmaessig:

| Datei | Inhalt |
|---|---|
| `garageband/scores/instrumental-transcription.json` | lesbarer Mehrspur-Score |
| `garageband/scores/instrumental-transcription.mid` | editierbare GarageBand-Spuren |
| `garageband/presets/instrumental-transcription.json` | Patch- und Mixplan |
| `out/analysis/instrumental-transcription-profile.json` | gemessene Onsets und Deskriptoren |
| `out/analysis/instrumental-transcription-report.json` | Engines, Sicherheit und Grenzen |

Die Startposition jeder rekonstruierten Note wird aus ihrer echten Quellzeit in
GarageBand-Beats umgerechnet. Es findet keine Zwangsquantisierung statt. Ein
stiller Timeline-Anker haelt auch einen unvollstaendigen letzten Takt auf der
exakten Quelldauer.

## 3. Editierbares GarageBand-Projekt vorbereiten

Auf dem Mac mit GarageBand:

```bash
python3 garageband/session.py prepare \
  --score garageband/scores/instrumental-transcription.json \
  --preset garageband/presets/instrumental-transcription.json \
  --reference-audio "/Pfad/zu/Instrumental.m4a"
```

Der Befehl validiert den Score, oeffnet die MIDI-Spuren in GarageBand, waehlt
passende Library-Patches und zeigt die Originaldatei im Finder. Apple sieht den
Audioimport in GarageBand fuer Mac per Drag-and-drop aus dem Finder vor. Ziehe
die Datei einmal unter die vorhandenen Tracks an den Projektanfang `1 1 1 1`
und druecke im Terminal Enter. Danach erkennt der Code die neue Spur, nennt sie
`REFERENCE — Original 1:1`, schaltet sie stumm und erstellt einen Screenshot.

Dieser eine Finder-Drag bleibt bewusst sichtbar: GarageBand stellt keine native
AppleScript-Schnittstelle fuer den Import einer beliebigen Audiodatei bereit.
Die restliche Track-Erkennung und Konfiguration geschieht wieder per Code.

Mit `--dry-run` wird der komplette Plan angezeigt, ohne GarageBand zu veraendern:

```bash
python3 garageband/session.py prepare \
  --score garageband/scores/instrumental-transcription.json \
  --preset garageband/presets/instrumental-transcription.json \
  --reference-audio "/Pfad/zu/Instrumental.m4a" \
  --dry-run
```

Danach das offene Projekt mit `Command-S` als `.band` speichern. Ab hier wird
direkt in GarageBand gearbeitet. Referenzspur kurz entmuten/solo schalten, mit
der Rekonstruktion vergleichen, dann wieder stummschalten.

## 4. Bearbeitete Fassung exportieren

Nach den manuellen GarageBand-Aenderungen darf `session.py render` nicht erneut
verwendet werden, weil dieser Befehl den JSON-Score frisch oeffnet. Stattdessen
wird das aktuell offene Projekt exportiert:

```bash
python3 garageband/session.py export-current \
  --output out/music-garageband-edited.wav
```

Die Musik bleibt weiterhin getrennt von `out/sfx-original.wav`.

## Was der Qualitaetsbericht ehrlich unterscheidet

- Arrangement/Timing: Quellreihenfolge und gemessene Startzeiten werden
  uebernommen.
- Tonhoehen: Basic Pitch oder der lokale DSP-Fallback rekonstruiert MIDI-Noten.
- Instrumente: GarageBand-Patches approximieren die Klangrolle; sie sind nicht
  die unbekannten Originalplugins.
- Exakter Klang: nur die Original-Referenzspur ist 1:1.
- Editierbarkeit: die rekonstruierten MIDI-Spuren sind frei aenderbar.

Fuer eine Veroeffentlichung oder kommerzielle Nutzung muessen die erforderlichen
Rechte an der Referenz und an der daraus abgeleiteten Transkription vorhanden
sein.
