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
2. Darunter liegen rekonstruierte Drums und erkannte Instrumente als separate
   MIDI-Spuren, beispielsweise Piano, Violine, Cello, Gitarre oder Floete.
   Jede Spur erhaelt ihre erkannten Noten, ein passendes General-MIDI-Programm
   und einen konkreten GarageBand-Library-Patch. Alles bleibt im Piano Roll
   editierbar.

Damit ist immer sichtbar, was wirklich 1:1 ist und was die editierbare
Transkription ist.

## 1. Analyse-Engines pruefen

```bash
python3 garageband/transcribe.py --doctor
```

Der lokale DSP-Fallback benoetigt nur die normalen Projektabhaengigkeiten. Fuer
komplexe Musik ist der Hochpraezisionsmodus vorgesehen:

- [Demucs](https://github.com/adefossez/demucs) trennt mit `htdemucs_6s`
  Drums, Bass, Piano, Gitarre und den uebrigen Mix vor der Transkription.
- [Basic Pitch](https://github.com/spotify/basic-pitch) erkennt polyphone Noten
  in jedem tonalen Stem.
- [CLAP](https://huggingface.co/docs/transformers/model_doc/clap) vergleicht
  verbleibende Audiofenster mit Instrumentbeschreibungen und liefert
  Wahrscheinlichkeiten fuer die Spurauswahl.

Basic Pitch unterstuetzt aktuell Python bis 3.11; fuer Apple Silicon nennt das
Projekt Python 3.10. Diese Version ist zugleich mit Demucs kompatibel. Auf dem
Mac:

```bash
python3.10 -m venv .venv-transcribe
source .venv-transcribe/bin/activate
python -m pip install -r garageband/requirements-transcription.txt
python garageband/transcribe.py --doctor
```

Beim ersten Hochpraezisionslauf wird standardmaessig das CLAP-Modell
`laion/clap-htsat-unfused` geladen und danach aus dem lokalen Modellcache
verwendet.

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

`--quality high` bedeutet konkret:

| Stufe | Engine | Aufgabe |
|---|---|---|
| Stem | Demucs `htdemucs_6s` | Drums/Bass/Piano/Gitarre/Other trennen |
| Noten | Basic Pitch | Start, Ende, Tonhoehe und Anschlag erkennen |
| Instrumentfamilie | CLAP | Piano/Gitarre/Bass/Strings/Brass/etc. bestimmen |
| Instrumentdetail | CLAP + Tonumfang | konkrete Variante innerhalb der Familie bestimmen |
| Routing | NEXPT | Rolle, Tonumfang und Confidence pruefen |
| GarageBand | Session Bridge | richtigen Library-Patch pro MIDI-Spur waehlen |

Die Taxonomie enthaelt jetzt alle 128 General-MIDI-Programme und zusaetzliche
GarageBand-Klassen. Insgesamt stehen 145 kanonische Ziele in 20 Familien zur
Verfuegung. Dazu gehoeren unter anderem:

```bash
python3 garageband/transcribe.py --list-instruments
```

- acht Piano-/Keyboard-Typen, Mallets, Glocken und Orgelvarianten;
- Nylon-/Steel-Gitarre sowie Jazz-, Clean-, Muted-, Overdrive- und
  Distortion-E-Gitarre;
- Acoustic, Finger, Pick, Fretless, Slap, Synth, Upright und Sub Bass;
- Violine, Viola, Cello, Kontrabass, Tremolo/Pizzicato und Ensembles;
- Trompete, Posaune, Tuba, Waldhorn und Brass/Synth-Brass;
- alle Saxofone, Oboe, Englischhorn, Fagott, Klarinette und Flötenfamilien;
- Synth Leads, Pads, Arpeggiator, Plucks, Bells und Textures;
- Sitar, Banjo, Shamisen, Koto, Kalimba, Erhu, Pipa, Guzheng, Dizi, Oud,
  Qanun, Yangqin, Santoor, Ukulele und Mandoline;
- Timpani, Steel Drums, Taiko, Melodic Toms und Orchester-Percussion.

Die Klassifikation erfolgt hierarchisch: CLAP bewertet zuerst die breite
Familie und danach die Detailinstrumente. Damit konkurriert beispielsweise
eine Violine nicht mehr gleichgewichtet mit 144 voellig fremden Patches.
Nichtmusikalische GM-Effekte bleiben im Katalog fuer manuelle Zuordnung, sind
aber aus der automatischen Musikklassifikation ausgeschlossen. Drums werden
weiter in Low Drums, Body Drums, Toms und Cymbals getrennt.

### Tatsaechlich installierte GarageBand-Instrumente inventarisieren

GarageBand-Version, Sprache und heruntergeladene Sound Packs bestimmen, welche
konkreten Patchnamen auf einem Mac existieren. Apple bietet deshalb auch den
Menuepunkt
[`GarageBand > Sound Library > Download All Available Sounds`](https://support.apple.com/en-us/101959)
an.
Eine globale, fuer jeden Mac identische Patchliste gibt es nicht.

Oeffne auf dem Mac ein GarageBand-Projekt mit mindestens einer
Software-Instrument-Spur und starte:

```bash
python3 garageband/session.py inventory \
  --track-index 1 \
  --output garageband/catalogs/installed-patches.json
```

Der Befehl liest zuerst die ungefilterte Library und durchsucht danach jede
Instrumentfamilie in der sichtbaren GarageBand Library. Er vereinigt die
Ergebnisse und ordnet die real installierten Namen der kanonischen Taxonomie
zu. Danach die Transkription mit diesem Inventar starten:

```bash
python garageband/transcribe.py "/Pfad/zu/Instrumental.m4a" \
  --quality high \
  --garageband-inventory garageband/catalogs/installed-patches.json
```

Der erzeugte Preset-Plan verwendet zuerst einen exakt inventarisierten Patch,
danach einen installierten Patch derselben Familie und erst zuletzt den
eingebauten Standardnamen. `patch_source` dokumentiert diese Entscheidung pro
Spur.

Apple Loops, Session Drummer, Audio-Gitarrenverstaerker und Voice-Presets sind
keine austauschbaren, tonhoehenbasierten Software-Instrument-Patches. Sie
werden daher nicht faelschlich als MIDI-Ziel behandelt. Die Drum-Erkennung und
die getrennte SFX-Pipeline bleiben dafuer die richtigen Pfade.

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

### Unsichere Instrumente manuell korrigieren

Bei zwei gleichzeitig spielenden Instrumenten im selben `other`-Stem kann
keine Stereoanalyse garantieren, welches Instrument welche Note gespielt hat.
Der Report markiert deshalb Instrumente und Noten mit Confidence und nennt die
Entscheidungsquelle (`demucs-stem`, `clap`, `role-fallback` oder Override).

Eine kleine JSON-Datei kann Fehlzuordnungen vor dem GarageBand-Import gezielt
korrigieren:

```json
{
  "stems": {
    "guitar": "electric_guitar"
  },
  "roles": {
    "harmony": "piano",
    "melody": "violin"
  }
}
```

```bash
cp garageband/instrument-map.example.json garageband/instrument-map.json
# instrument-map.json an den tatsaechlichen Mix anpassen, dann:
python garageband/transcribe.py "/Pfad/zu/Instrumental.m4a" \
  --quality high \
  --instrument-map garageband/instrument-map.json
```

Deutsche Werte wie `Klavier`, `Violine`, `Floete`, `Klarinette`, `Trompete`
und `Akustikgitarre` werden ebenfalls akzeptiert. Ein Stem-Override ist
spezifischer als ein Rollen-Override. Mit `--instrument-engine stem` kann die
CLAP-Klassifikation uebersprungen werden; Piano/Gitarre/Bass aus Demucs und die
Rollen-Fallbacks bleiben dann erhalten.

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

Der Befehl validiert den Score, oeffnet die instrumentbezogenen MIDI-Spuren in
GarageBand, sucht pro Spur den erzeugten Patchplan ab und waehlt beispielsweise
einen Piano-, Violin- oder Gitarren-Patch. Danach zeigt er die Originaldatei im
Finder. Apple sieht den
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
- Instrumente: Demucs-Stems und CLAP erkennen die wahrscheinlichste
  Instrumentklasse. Der Report zeigt Confidence; ein Override kann sie
  korrigieren. GarageBand-Patches approximieren die Klangrolle und sind nicht
  die unbekannten Originalplugins.
- Exakter Klang: nur die Original-Referenzspur ist 1:1.
- Editierbarkeit: die rekonstruierten MIDI-Spuren sind frei aenderbar.

Fuer eine Veroeffentlichung oder kommerzielle Nutzung muessen die erforderlichen
Rechte an der Referenz und an der daraus abgeleiteten Transkription vorhanden
sein.
