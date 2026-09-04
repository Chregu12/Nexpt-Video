# Reference Decomposition: Musik, Dialog und SFX

`video_music.py decompose` startet lokale Cinematic-Demixing-Inferenz, sobald
ein kompatibler CDX23-Checkout samt Modellgewichten konfiguriert ist. Es ist
kein Frequenzfilter und keine VAD-basierte Zeitaufteilung. Modelle sind nicht
mitgeliefert. NEXPT startet keine Downloads und laedt keine Referenzen hoch.

## Unterschiedliche Aufgaben

| Einstieg | Aufgabe | Ergebnis / Grenze |
|---|---|---|
| `extract --mode soundtrack` | Audio dekodieren | Vollstaendiger Mix inklusive Sprache und SFX |
| `extract --mode music` | Vocals entfernen (Demucs / RoFormer) | No-vocals-Schaetzung; SFX koennen bleiben |
| `decompose` | Filmton nach Musik / Dialog / Effekten trennen | Drei geschaetzte Stems; Hoerpruefung bleibt noetig |
| `garageband/workflow.py` | Instrumente und Noten rekonstruieren | Editierbares MIDI und Patch-Zuordnung; keine identischen Studio-Sounds |

Ein `no_vocals`-Stem heisst nicht `sfx`. Ein Summenrest wird ebenfalls nicht
als `sfx.wav` ausgegeben. Nur der explizite Effekt-Ausgang des CDX-Modells wird
dieser Datei zugeordnet. Gesang kann im Musik-Stem enthalten bleiben.

## Lokales Modell vorbereiten

Die konkrete Integration verwendet den veroeffentlichten CLI-Vertrag von
[MVSEP-CDX23](https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing)
am dokumentierten Commit `aaa75640d8fd68418948fe4cd2c2d263d042cbb9`.

1. Den Upstream in einen eigenen lokalen Ordner klonen und diesen Commit
   auschecken. NEXPT veraendert den Checkout nicht.
2. Eine separate, mit dem Upstream kompatible Python-Umgebung einrichten.
   Dessen `requirements.txt` benoetigt unter anderem PyTorch, Demucs, librosa
   und soundfile. Die echte Modellinferenz muss auf dem Zielrechner getestet
   werden; NEXPTs automatisierte Tests ersetzen diesen Runtime-Test nicht.
3. Gewichte aus den [Upstream-Releases](https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing/releases/tag/v.1.0.0)
   bewusst herunterladen und unter `<checkout>/models/` ablegen:

   - Standard: `97d170e1-dbb4db15.th`
   - Zusaetzlich fuer `high`: `97d170e1-a778de4a.th` und `97d170e1-e41a5468.th`

4. Herkunft und Nutzungsbedingungen der Checkpoints pruefen. Eine Code-Lizenz
   bestaetigt nicht automatisch Rechte an Gewichten oder Audio. Historische
   PyTorch-Checkpoints koennen Pickle-Code enthalten: nur vertrauenswuerdige
   Dateien verwenden, keine globalen Sicherheitsvorgaben abschalten, wenn eine
   inkompatible Runtime das Laden ablehnt.
5. Die bewusst bereitgestellten lokalen Dateien registrieren:

```bash
python3 render/cinematic_separation.py \
  --repository /absoluter/pfad/cdx23 \
  --python /absoluter/pfad/cdx-venv/bin/python \
  --checkpoint-license "GEPRUEFTE-LIZENZ-DER-GEWICHTE" \
  --output /absoluter/pfad/cdx-config.json

export NEXPT_CDX_CONFIG=/absoluter/pfad/cdx-config.json
python3 render/video_music.py doctor
```

Die Registrierung ueberschreibt keine Konfiguration. Sie zeichnet Git-Revision
und SHA-256-Werte der lokalen Dateien auf: eine Integritaetsbasis, keine
unabhaengige Bestaetigung der Herausgeberidentitaet. `doctor` zeigt
`configured`, aber ausdruecklich nicht `runtime_verified`.
Vor und nach der Inferenz prueft NEXPT Checkout und alle benoetigten Gewichte.
Fehlende Gewichte brechen den Lauf ab, bevor der Upstream seinen eingebauten
Download versuchen koennte. Andere bewusst registrierte Commits sind moeglich,
werden aber als Abweichung gemeldet.

## Zerlegen und an GarageBand uebergeben

```bash
python3 render/video_music.py decompose /pfad/film.mp4 \
  --output-dir out/video-music/film-v1 \
  --quality high --device cpu --strict

python3 garageband/workflow.py out/video-music/film-v1/music.wav \
  --quality high --separate demucs --prepare-dry-run
```

CDX unterstuetzt CPU oder CUDA. MPS wird nicht stillschweigend auf CPU
umgestellt. `--audio-stream 1` waehlt die zweite Audiospur des Containers.
`--cdx-config` ersetzt die Umgebungsvariable. `--vad silero` erstellt optional
eine Segmentkarte fuer den Musik-Stem; VAD trennt keine weiteren Quellen.

| Datei | Inhalt |
|---|---|
| `soundtrack.wav` | Vollstaendiger dekodierter Mix zum A/B-Vergleich |
| `music.wav` | Geschaetzte Musik; Eingang fuer GarageBand |
| `dialogue.wav` | Geschaetzter Dialog, separat aufbewahrt |
| `sfx.wav` | Geschaetzte Effekte, nicht in die Musiktranskription gemischt |
| `manifest.json` | Quell-/Ausgabe-Hashes, Modellherkunft, Summenpruefung und Folgekommandos |
| `music.segments.json` | Optional bei aktiviertem VAD |

Die Originaldatei bleibt unveraendert. CDX arbeitet bei 44.1 kHz; alle Ausgaben
werden gemeinsam auf die gewuenschte Samplerate (Standard 48 kHz) gebracht.
FLOAT-WAV bewahrt Pegel ohne separate Normalisierung/Clipping. Ein publiziertes
Paket ist unveraenderlich: fuer neue Versuche einen neuen Ordner verwenden.
Es gibt absichtlich kein rekursives `--overwrite` fuer vorhandene Ordner.

## Qualitaetsvertrag

- Dateien, endliche Samples, passende Laengen/Kanaele und Sampleraten werden
  vor der Veroeffentlichung geprueft.
- `mix_consistency` misst `RMS(mix - music - dialogue - sfx) / RMS(mix)`.
  Standardgrenzwert: `0.1`, konfigurierbar mit `--maximum-residual-ratio`.
  Dies ist ein technischer Diagnosewert, kein Nachweis sauberer Instrumente
  oder geringer gegenseitiger Uebersprechung.
- `--strict` veroeffentlicht bei Ueberschreitung dieses Grenzwerts nichts.
  Ohne `--strict` bleibt der Fehler im Manifest sichtbar.
- Auch bei perfekter Summe bleibt der Gesamtstatus `review_required`:
  Falsch verteilte Stems koennen sich exakt zum Mix addieren.
- Der Summenrest wird nicht auf Stems verteilt, um die Messung zu verbessern.
- `--quality high` waehlt das Drei-Checkpoint-Ensemble. Es garantiert keine
  originalgetreue oder fehlerfreie Rekonstruktion.
- Lange Dateien koennen viel RAM/VRAM und Laufzeit benoetigen. Streaming der
  Validierung und wiederaufnehmbare Teilverarbeitung sind noch nicht umgesetzt.

## Gemeinsame GarageBand-Separation

`garageband/transcribe.py` verwendet nun `render/music_separation.py`.
Demucs im Instrument-Modus liefert einzelne Rollen (bei `htdemucs_6s` auch
Piano/Gitarre); der Video-No-Vocals-Modus bleibt eine Zweispur-Aufgabe.
Fehlende Pflicht-Stems werden abgewiesen.

```bash
python3 garageband/workflow.py /pfad/musik.wav \
  --separate roformer --roformer-command /pfad/roformer-adapter \
  --quality auto --prepare-dry-run
```

RoFormer liefert nur einen geschaetzten Mix. Alle Analysen laufen auf diesem
Ergebnis, nicht versehentlich wieder auf der Originaldatei; `isolated_drums`
bleibt `false`. In `high` braucht RoFormer die bestehende maschinenlesbare
Provenienz. Ihre Angaben werden vom Adapter deklariert, nicht von NEXPT am
Checkpoint nachgemessen.

Nur `auto` mit Standardqualitaet darf nach Backendfehlern auf DSP zurueckfallen
und muss dies melden. Explizite Backends und `high` brechen ab. `--keep-work`
verwendet fuer jeden Lauf neue Stem-Verzeichnisse. Fuer `--resume` wird die
Adapter-Datei gehasht. Externe Gewichte/Imports eines RoFormer-Adapters sind
dadurch noch nicht vollstaendig als Cache-Identitaet abgedeckt.

## Verifikation

```bash
python3 -m unittest discover -s tests
```

Die Tests pruefen CLI, echte ffmpeg-Dekodierung, SHA-Verifikation,
defekte/fehlende/zu kurze Stems, Transaktionen, Wiederholungen und die Uebergabe
der Musikspur bis zum GarageBand-MIDI. Die CDX-/RoFormer-Modelle werden dabei
durch deterministische Testprogramme ersetzt. Daraus folgt keine Aussage zur
realen Demixing-Qualitaet. Echte Checkpoint-Inferenz, Hoervergleich und die
GarageBand-Oberflaeche bleiben separate Abnahmetests.
