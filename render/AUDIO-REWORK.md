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

Erforderlich sind Python 3, NumPy, SciPy und ffmpeg. Es werden keine externen
Samples oder Modellgewichte geladen.

## Musik

`out/music-original.wav` ist eine durchgehende, originale 68-Takt-Partitur bei
118 BPM. Sie besitzt eigene Abschnitte, Fill-ins, Pausen und Phrase-Level-
Microtiming. Sie wiederholt keinen importierten 16-Takt-Loop.

Die Datei `out/analysis/music-original.json` dokumentiert Aufbau, Eventzahl,
Seed und technische Messwerte.

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

Alle neuen Audiosignale sind prozedural und deterministisch erzeugt. Audio aus
den Referenzfilmen oder dem bisherigen Musikloop wird nicht verwendet.
