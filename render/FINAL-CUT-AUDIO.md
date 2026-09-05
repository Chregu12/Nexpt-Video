# Getrennte Musik und Soundeffekte in Final Cut Pro

`fcpxml.py` kann die Bild-Timeline zusammen mit sieben **einzeln editierbaren**
Audiospuren ausgeben. Musik und Soundeffekte bleiben dabei getrennt. Die
vorgemasterten Summen werden absichtlich nicht zusätzlich eingefügt, weil sie
sonst parallel zu den Stems laufen und den Ton verdoppeln würden.

## Export

Zuerst nur prüfen. Dabei wird keine vorhandene XML ersetzt:

```bash
python3 render/fcpxml.py \
  --audio-config render/final-cut-audio.json \
  --check
```

Danach die portable Timeline und ihr Prüfmanifest schreiben:

```bash
python3 render/fcpxml.py \
  --audio-config render/final-cut-audio.json
```

Die Dateien `NEXPT-Keynote.fcpxml`,
`NEXPT-Keynote.fcpxml.manifest.json`, `scenes/` und alle konfigurierten WAVs
müssen gemeinsam im Ordner `out/` bleiben. Medienpfade werden relativ und für
Leerzeichen URL-kodiert geschrieben.

| Final-Cut-Rolle | Quelldatei | Zweck |
|---|---|---|
| `music.nexpt-low` | `music-reference-low.wav` | Sub und tiefe Percussion |
| `music.nexpt-body` | `music-reference-body.wav` | Sticks, Rims und Body |
| `music.nexpt-tonal` | `music-reference-tonal.wav` | gestimmte Toms und Holz |
| `music.nexpt-detail` | `music-reference-detail.wav` | Clicks, Ticks und Luft |
| `effects.nexpt-impacts` | `sfx-impacts.wav` | Kapitelwechsel und Schnitte |
| `effects.nexpt-motion` | `sfx-motion.wav` | Linien, Karten und Bewegung |
| `effects.nexpt-clicks-foley` | `sfx-ui.wav` | UI, Clicks und kleines Foley |

Jede Rolle liegt auf einer eigenen negativen Lane und beginnt bei `0s`. Die
individuellen Sample-Längen bleiben erhalten; falls eine Spur länger als das
Bild ist, ergänzt der Generator eine primäre `Audio tail`-Lücke und verlängert
die Sequenz auf das nächste Videoframe.

## Sicherheits- und Qualitätsprüfungen

Vor dem Schreiben gelten für jede Quelle dieselben Regeln:

- echte, nicht über einen Symlink eingebundene WAV-Datei innerhalb von `out/`;
- unkomprimiertes PCM, Stereo und 48 kHz;
- 16, 24 oder 32 Bit und mindestens ein Sample;
- vollständige Audiodaten entsprechend dem WAV-Header;
- eindeutige Track-IDs, Quelldateien und Rollen;
- mindestens eine `music.*`- und eine `effects.*`-Rolle.

SHA-256-Prüfsummen vor und unmittelbar vor dem Ersetzen verhindern, dass eine
während des Exports veränderte Quelle unbemerkt in der Timeline landet. Bei
einem Fehler bleiben eine bestehende FCPXML und ihr Manifest unangetastet.

Die Ausgabe folgt FCPXML 1.10 und nutzt `asset`, `asset-clip`, `audioRole`,
`srcEnable` und rationale Sekunden entsprechend Apples
[FCPXML-Dokumenttypdefinition](https://developer.apple.com/documentation/professional-video-applications/document-type-definition).
Das Manifest bestätigt XML-Wohlgeformtheit und unveränderte Quellen. Es setzt
`final_cut_import_verified` bewusst auf `false`: Einen echten Import kann nur
Final Cut Pro auf dem Mac bestätigen.

## Fehler beheben

`ist abgeschnitten` bedeutet, dass der WAV-Header mehr Audiodaten ankündigt,
als tatsächlich in der Datei vorhanden sind. Die Spur nicht reparieren, indem
der Header verkürzt wird; dadurch gingen Timing und Ausklang verloren. Musik-
Stems stattdessen aus dem vorhandenen Referenzprofil neu rendern:

```bash
python3 render/music_reference.py \
  --profile out/analysis/reference-profile.json \
  --output out/music-reference.wav
```

Anschließend zuerst erneut mit `--check` prüfen. SFX-Stems werden unabhängig
davon mit `python3 render/sfx_original.py` neu erzeugt.
