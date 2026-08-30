# NEXPT Audio Rework

Dieser Audiopfad veraendert weder Bild noch Text noch Szenenlaengen. Musik und
Soundeffekte sind getrennte, austauschbare Stems.

## Erzeugen

```bash
python3 render/cuesheet.py
python3 render/music_original.py
python3 render/sfx_original.py
sh render/audio_preview.sh
```

Erforderlich sind Python 3, NumPy, SciPy und ffmpeg. Fuer die samplebasierte
Musik laedt `render/vcsl.py` einmalig eine Sparse-Auswahl echter Aufnahmen aus
der Versilian Community Sample Library (CC0 1.0). Modellgewichte werden nicht
benoetigt.

## Eine Referenz analysieren und in eigene Musik uebersetzen

Der allgemeine Referenzpfad funktioniert mit WAV, AIFF, MP3, M4A und auch mit
Videodateien, sofern ffmpeg sie lesen kann:

```bash
python3 render/reference_pipeline.py "/pfad/zur/referenz.m4a" \
  --bpm 118 --downbeat 0 --sound-source samples \
  --download-drums --preview
```

Ist das Tempo nicht bekannt, koennen `--bpm` und `--downbeat` entfallen. Eine
bekannte Eins sollte trotzdem angegeben werden: Aus einem Stereo-Mix laesst
sich das Sechzehntelraster verlaesslicher bestimmen als die musikalische Eins.

Der Lauf besteht aus fuenf voneinander pruefbaren Schritten:

1. `reference_analyzer.py` misst Tempo, Raster, Microtiming, Anschlaege,
   Klangfamilien, Frequenzbalance, Dynamik, Aufbau und Stereobreite. Aus den
   Ereignissen lernt er zusaetzlich Rollenwahrscheinlichkeiten und
   Vier-Takt-Phasen.
2. `reference_synth.py` baut daraus ein neues Kit mit vier Rollen. Die
   Schallquellen sind echte CC0-Aufnahmen; passende Velocity-Layer und Round
   Robins werden je Anschlag gewaehlt. Stimmung, Abklingzeit, Attack und breite
   Frequenzbalance folgen dem Profil, ohne Audio aus der Referenz zu kopieren.
3. `music_reference.py` schreibt eine neue 68-Takt-Komposition. Neu erzeugte
   Vier-Takt-Motive werden kontrolliert wiederholt und variiert. Die komplette
   Ereignisfolge der Referenz wird nicht kopiert.
4. `reference_compare.py` misst das Ergebnis wieder und bewertet, wie gut
   Klangbalance, Breite, Dynamik, Rollendichte, Schrittmuster,
   Vier-Takt-Wiederholung und Tempo das Profil treffen. Der Score ist eine
   Diagnose und kein Ersatz fuer den Hoertest.
5. `sfx_original.py` bleibt ein unabhaengiger Pfad aus dem Video-Cue-Sheet.

Lokale Ausgaben:

- `out/analysis/reference-profile.json`: maschinenlesbares Referenzprofil
- `out/reference-kit/`: bearbeitetes, samplebasiertes CC0-Percussion-Kit
- `out/music-reference-low.wav`: Sub- und tiefe Percussion
- `out/music-reference-body.wav`: Sticks, Rims und kurze Body-Transienten
- `out/music-reference-tonal.wav`: gestimmte Toms und Holz-Percussion
- `out/music-reference-detail.wav`: Clicks, Ticks und Luft
- `out/music-reference.wav`: vorgemasterte Summe
- `out/analysis/reference-match.json`: Messvergleich Referenz gegen Ergebnis
- `out/NEXPT-REFERENCE-AUDIO-PREVIEW.mp4`: Bild mit neuer Musik und separaten SFX

Die Referenzdatei wird nicht kopiert. Die Generatoren koennen sie auch nicht
oeffnen: Sie erhalten ausschliesslich das JSON-Profil. Original-Samples, MIDI,
Plugin-Einstellungen und ueberlagerte Einzelspuren koennen aus einem fertigen
Stereo-Mix nicht exakt rekonstruiert werden. Das Ziel ist deshalb eine eigene
Klangsprache mit vergleichbaren Eigenschaften, keine Audio- oder Pattern-Kopie.

`--sound-source auto` ist der Standard: Ist `out/_vcsl/katalog.json`
vorhanden, werden echte Drums verwendet, andernfalls die prozedurale
Rueckfall-Engine. `--sound-source samples` verlangt die Drum-Bibliothek und
bricht mit einer klaren Ladeanweisung ab, falls sie fehlt.

## Musik

`out/music-original.wav` ist eine durchgehende, originale 68-Takt-Partitur bei
118 BPM. Sie besitzt eigene Abschnitte, Fill-ins, Pausen und Phrase-Level-
Microtiming. Sie wiederholt keinen importierten 16-Takt-Loop.

Die Datei `out/analysis/music-original.json` dokumentiert Aufbau, Eventzahl,
Seed und technische Messwerte.

`music-reference.wav` ist die alternative profilgesteuerte Fassung. Ihre vier
Rollen-Stems sind Pre-Master-Spuren; die nichtlineare Bus-Saettigung liegt nur
auf dem Master. Dadurch bleiben die Einzelspuren in Final Cut oder Logic frei
mischbar, summieren sich ohne denselben Master-Bus aber nicht bitgleich zum
Master.

## Soundeffekte

Die Effekte werden aus dem Cue Sheet ausgewählt und vollständig unabhängig von
der Musik synthetisiert:

- `out/sfx-impacts.wav`: Kapitelwechsel und starke Schnitte
- `out/sfx-motion.wav`: Marker, Linien, Karten und Bewegungen
- `out/sfx-ui.wav`: Raster, Kritzel und UI-Ticks
- `out/sfx-original.wav`: Summe der drei Substems

`out/analysis/sfx-original.json` enthält jede verwendete Cue-Entscheidung. Die
im Cue Sheet markierten Haltemomente bleiben auch bei auslaufenden Effekten
still.

## Vorschau

`render/audio_preview.sh` erzeugt einen reinen Audiomix sowie eine MP4-Vorschau
mit unverändert kopiertem Videostream. Das Ducking und Loudness-Normalizing
betreffen nur die Vorschau, nicht die gelieferten Einzelstems.

Die Musik verwendet deterministisch ausgewaehlte und bearbeitete
CC0-Percussion-Aufnahmen; die Soundeffekte bleiben prozedural und separat.
Audio aus den Referenzfilmen oder dem bisherigen Musikloop wird nicht
verwendet.
