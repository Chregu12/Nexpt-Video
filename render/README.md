# Render-Pipeline

Erzeugt aus `timing.json` ProRes-Clips und ein FCPXML für Final Cut Pro.

## Voraussetzungen

```bash
pip install playwright piper-tts faster-whisper
python3 -m playwright install chromium     # oder vorhandenes Chromium via CHROME= setzen
sh render/voices/get-voices.sh             # deutsche Stimmmodelle (~200 MB)
# ffmpeg mit prores_ks (jedes aktuelle ffmpeg; auf macOS: brew install ffmpeg)
```

## Benutzung

```bash
# BILD
python3 render/render.py                 # alle 30 Szenen → out/scenes/*.mov  (ProRes 422 HQ)
python3 render/render.py 15 22           # nur diese Szenen (Nummer oder id-Fragment)
python3 render/render.py --stills        # nur je ein Standbild pro Szene (Sekunden statt Minuten)
python3 render/render.py --alpha         # ProRes 4444 mit Alpha statt 422 HQ

# TIMING
python3 render/takt.py --probe           # zeigen, wie das Rastern auf 118 BPM ausfiele
python3 render/takt.py                   # timing.json auf das Musikraster legen
python3 render/scratchvo.py              # → out/scratch-vo.wav (Wegwerf-Stimme zum Timing-Check)
python3 render/sync.py <datei>           # Timing auf die echte Stimme ziehen — siehe unten
python3 render/pruefen.py                # Zeitachse, leere Frames, Tempo  (--fix repariert)

# TON
python3 render/musik.py                  # Musik auf den Film legen → out/music.wav
python3 render/video_music.py doctor     # Video-Ton-/Musik-Extraktion pruefen
python3 render/proben.py                 # echte Schläge aus dem Loop → out/_proben/
python3 render/reference_pipeline.py REFERENZ --bpm 118 --downbeat 0
                                          # Referenzprofil → eigenes Kit/Musik/Stems
python3 render/cuesheet.py               # Hit Points → out/analysis/cue_sheet.json
python3 render/sfx.py                    # Sounddesign → out/sfx.wav
python3 render/sounddesign.py --drums    # optionale eigene Percussion (standardmässig aus)
sh render/mischen.sh                     # Stimme, Musik, Effekte → out/ton-final.wav

# AUSGEBEN
python3 render/bauen.py                  # prüfen und zusammenbauen (--check nur prüfen)
python3 render/fcpxml.py                 # → out/NEXPT-Keynote.fcpxml
python3 render/drehbuch.py               # Abschnitt 4 des Konzepts aus timing.json erzeugen
sh render/paket.sh                       # Download-Paket → out/NEXPT-Keynote-Paket.zip
```

Die **Reihenfolge** ist nicht beliebig. Der Film ist auf die Anschläge *eines bestimmten*
Tracks gerastert; wer die Musik tauscht, muss `takt.py` und den Render nachziehen, sonst
fällt das Alignment auf Zufallsniveau zurück (gemessen 21 % statt 45 %):

```bash
python3 render/musik.py <neue-quelle>   # 1. Anschläge in Filmzeit schreiben
python3 render/proben.py <neue-quelle>  # 2. Klangpalette neu schneiden
python3 render/takt.py                  # 3. Film darauf rastern
python3 render/render.py                # 4. 30 Clips neu
python3 render/scratchvo.py             # 5. Stimme auf die neuen Zeiten
python3 render/cuesheet.py && python3 render/sfx.py
sh render/mischen.sh && python3 render/bauen.py --neu
```

### Video als Musikquelle

Neu: `video_music.py decompose` zerlegt Filmton mit einem konfigurierten lokalen
CDX23-Modell in Musik, Dialog und SFX. Einrichtung, Qualitaetsgrenzen und
GarageBand-Uebergabe stehen in [DECOMPOSITION.md](DECOMPOSITION.md).

`video_music.py` stellt lokale Videos reproduzierbar fuer die vorhandenen
Referenz- und GarageBand-Pipelines bereit. `soundtrack` dekodiert die komplette
Tonmischung als 48-kHz-Stereo-WAV. `music` verwendet den gepinnten
Demucs-Basisweg oder einen explizit konfigurierten lokalen RoFormer-Adapter, um
eine No-Vocals-Mischung zu schaetzen. Diese kann weiterhin Soundeffekte und
Sprachreste enthalten und ist nicht die originale Studio-Musikspur.

```bash
python3 -m pip install -r garageband/requirements-transcription.txt
python3 render/video_music.py doctor
python3 render/video_music.py extract film.mp4 --mode soundtrack
python3 render/video_music.py extract film.mp4 --mode music \
  --quality high --separator auto --vad auto --analyze
```

Audio, Segmentkarte, Analyseprofil und Manifest landen standardmaessig unter
`out/video-music/`. Das Manifest enthaelt SHA-256-Pruefsummen, Backend- und
Modellprovenienz, ein Quality Gate und sichere Folgebefehle fuer
`reference_pipeline.py` und `garageband/workflow.py`.

`--quality high` verlangt bei `--vad auto` Silero VAD sowie im Musikmodus die
getestete Demucs-Version `4.0.1` (Modell `htdemucs_ft`) oder einen RoFormer-
Adapter. Mit `--vad heuristic` kann man bewusst ohne Silero arbeiten; der Lauf
wird dann als `review_required` markiert. Die Segmentkarte ist eine Hilfe zum
Trennen von Musik, Sprache, SFX und Stille, keine Ground-Truth-Stemmaske.
Auch mit Silero bleibt ein High-Quality-Lauf `review_required`, solange
mindestens ein Segment den Konfidenzschwellwert nicht erreicht.

Ein RoFormer-Adapter wird mit `NEXPT_ROFORMER_COMMAND=/pfad/zum/adapter`
aktiviert. Er bekommt `--input PATH --output-dir DIR` und muss genau
`instrumental.wav` oder `no_vocals.wav` schreiben; optional darf
`vocals.wav` hinzukommen. Fuer ein bestandenes High-Quality-Gate schreibt er
zusaetzlich `provenance.json` mit `model`, `version`, `license` und dem
64-stelligen `checkpoint_sha256`; ohne diesen Nachweis bleibt das Ergebnis
`review_required`. Checkpoint und Lizenz bleiben damit explizit in der
Verantwortung des lokalen Adapters.

### Referenzprofil statt Samples aus der Referenz

`reference_pipeline.py` ist der allgemeine, quell-samplefreie Weg fuer eine
neue Referenz. Anders als `abhoeren.py` und `proben.py` schneidet er keine
Schlaege aus dem Quelltrack. Der Analyzer schreibt nur Deskriptoren nach
`out/analysis/reference-profile.json`; alle folgenden Skripte koennen die
Referenzdatei technisch nicht mehr lesen.

```bash
python3 render/reference_pipeline.py referenz.m4a --bpm 118 --downbeat 0 \
  --sound-source samples --download-drums
python3 render/reference_pipeline.py referenz.m4a --preview  # auto: VCSL oder Rueckfall
python3 render/reference_pipeline.py referenz.m4a --bpm 118 --downbeat 0 \
  --garageband --skip-local-music --skip-kit --skip-compare
```

Der erste Befehl verwendet bekannte Tempodaten. Der zweite schaetzt Tempo und
Raster automatisch. Das Ergebnis besteht standardmaessig aus einem
profilbearbeiteten Kit echter CC0-Aufnahmen, vier Musikstems, dem Musikmaster,
separaten SFX und einem Messreport. `--sound-source procedural` erzwingt die
samplefreie Rueckfall-Engine. Details und alle Ausgaben stehen in
`render/AUDIO-REWORK.md`.

Der dritte Befehl schreibt aus demselben reinen Ereignisplan vier MIDI-Tracks
fuer echte GarageBand-Kits. Der WAV-Export folgt auf dem Mac mit
`python3 garageband/session.py render`; SFX bleiben davon getrennt.

## Ton: vier Stufen, alle aus `timing.json`

### 1. Der Takt — `takt.py`

Legt die Szenendauern auf **Achtel** und die grossen Ereignisse auf **Sechzehntel**, bei
**118.00 BPM ab Filmzeit 0.000**. Der Film ist damit genau **68 Takte** lang. In einem
zweiten Durchgang wandert jedes grosse Ereignis auf den nächsten *tatsächlichen* Anschlag
des Tracks — das abstrakte Raster allein hilft nicht, wenn der Schlagzeuger dort Pause macht
(von 272 Vierteln tragen nur 36 % einen Schlag).

| | vorher | Raster allein | Raster + echte Anschläge |
|---|---|---|---|
| grosse Bildereignisse auf einem Anschlag | 15 % | 16 % | **45 %** |
| Szenenanfänge | 23 % | 23 % | **53 %** |
| (Zufallsniveau) | 14 % | 14 % | 14 % |

`takt.py` rastert die **Dauern**, nicht die Startzeiten — die ergeben sich als laufende
Summe. Genau dort lag ein Fehler: `start` und die kumulierte Dauer liefen ab `09_flut`
2.00 s auseinander, Bild 137.5 s gegen Ton 135.4 s. Ab 0:36 lief die Stimme dem Bild voraus.
`pruefen.py` prüft das jetzt als allererstes.

### 2. Die Musik — `musik.py`

Zwei Betriebsarten, automatisch gewählt: Quelle **kürzer** als der Film → Loop, längentreu
auf das Filmraster gerechnet. Quelle **länger** → auf Taktkanten geschnitten.

Ein Loop wird **nicht arrangiert**. Der Versuch, die 16 Takte nach der Dramaturgie neu zu
sortieren, ergab 26 Nahtstellen auf 2:18 — und weil die Taktkanten leise sind (−46 dB kurz
davor), sass der erste Schlag jedes Takts genau auf der Naht und wurde von der Blende
angefressen. Ein Loop ist an seiner eigenen Rundung nahtlos, sonst nirgends.

An den fünf Halte-Beats zieht die Musik auf 28 % zurück. Am Filmende 0.3 s Blende, danach
absolute Stille.

### 3. Das Cue Sheet — `cuesheet.py`

**139 Hit Points** nach `out/analysis/cue_sheet.json`, je mit Zeit, Takt.Zählzeit, Szene,
Art, Stärke 0..1 und Stereoposition. Das ist die Vorlage zum Komponieren — und sie wird
**nicht aus dem Video gemessen**: `timing.json` weiss auf die Millisekunde, *was* passiert,
während eine Schnitterkennung nur „Bewegung bei 84.2 s" melden könnte.

### 4. Die Klänge — `proben.py` und `sfx.py`

`proben.py` schneidet **echte Schläge** aus dem Musikloop (12 Proben in drei Klassen,
ausgewählt nach Sauberkeit). `sfx.py` baut daraus fünf Ebenen: `impact`, `whoosh`, `click`,
`tick`, `riser`.

Die Gestaltung folgt der **Messung**, nicht der Vermutung — und zwar zweier Referenzen, die
gegensätzlich arbeiten:

| gemessen | Apple (75.8 s) | Samsung (78.3 s) |
|---|---|---|
| Energie an Bildschnitten | Median 0.80× / 0.50× / 0.52× — sie *fällt* | Akzent an 4 von 10 Schnitten, Median +84 ms |
| Bewegung → Akzent | — | 19 von 30, Median **+15 ms** |
| Lautheit | −17.7 LUFS, LRA 4.3 | −13.6 LUFS, LRA 7.7 |
| Sounddesign auf Bildereignissen | **keins** | 285 Onsets = 3.64/s |

Apple legt Musik unter das Bild, Samsung vertont es. Der Film folgt der zweiten Schule.
Wichtig dabei: Samsung vertont vor allem **Bewegung**, nicht den Schnitt.

Kalibriert statt geschätzt — die Entzerrung misst die gebaute Spur, hält sie gegen die
Referenzkurve und wendet die Differenz an (vier Runden, begrenzt auf ±10 dB):

| | Referenz | NEXPT |
|---|---|---|
| Bandbalance Sub/Bass/TM/M/H/Luft | 0 / −3.3 / −10.4 / −16.6 / −26.8 / −29.3 dB | **±0.2 dB** |
| Akzentspitze über dem Bett | +11.0 dB | **+10.9 dB** |
| Akzent zum Bildereignis | +15 ms, 63 % innerhalb 100 ms | **±0 ms**, 62 % innerhalb 50 ms |

Jeder Klang wird auf seine eigene **Spitze** ausgerichtet, nicht auf seinen Anfang.

```bash
python3 render/sfx.py --pegel 0.6         # Sounddesign leiser
python3 render/sfx.py --nur schnitt,marker # nur diese Arten
```

**Die Grenze:** der Loop enthält keine tiefe Trommel (tiefster Schwerpunkt 988 Hz). Impacts
entstehen deshalb wie im Studio — echte Aufnahme zwei Oktaven tief transponiert für die
Textur, Sinus darunter fürs Fundament. Für die Endfassung wäre ein Freesound-Token (CC0,
gratis) oder eine kommerzielle Library der Weg.

### Der Mix — `mischen.sh`

```bash
sh render/mischen.sh                  # Stimme + Musik + Effekte
sh render/mischen.sh --ohne-stimme    # Standloop-Fassung
sh render/mischen.sh --ohne-effekte   # zum Vergleich, ohne Sounddesign
sh render/mischen.sh --drums          # zusätzlich die eigene Percussion
```

Ein Filtergraph, dessen Pegel die Schalter setzen — eine stumme Spur ändert bei `amix`
mit `normalize=0` nichts, ein stummer Sidechain-Key komprimiert nicht. Die Musik hat
**zwei** Sidechains: sie tritt unter der Stimme zurück *und* unter jedem Akzent. Das ist
die musikalische Pause, damit die Effekte hörbar bleiben.

Gemischt auf **−14.3 LUFS / LRA 4.0** — bei der Lautheit nahe an Samsung, bei der Dynamik
näher an Apple, weil unser Film durchgehend gesprochen ist.

**Die Musik des Referenzfilms wird nicht kopiert** — sie ist eine geschützte Komposition.

## Zusammenbauen nur mit `bauen.py`

Drei Fehler sind mir beim Zusammenbau mehrfach passiert; `bauen.py` fängt alle drei ab und
verweigert im Zweifel den Bau:

1. **Zusammenbau gestartet, während der Render noch lief** — halb geschriebene Clips landeten
   im Film (einmal wurde daraus eine 41-Sekunden-Datei). Ursache war jedes Mal ein `&` oder
   `nohup … &` in einem ohnehin im Hintergrund laufenden Befehl, wodurch er sofort zurückkam
   und fälschlich „fertig" meldete.
2. **Clips gestrichener Szenen** lagen noch im Ordner und liefen mit.
3. **Clips waren vollständig, aber veraltet** — die Dauerprüfung greift dort nicht, wenn sich
   nur Farben oder Positionen geändert haben. Deshalb prüft `bauen.py` zusätzlich, ob jeder
   Clip **jünger als `timing.json` und `film.html`** ist.

## Vor jeder Abnahme: `pruefen.py`

Zwei Fehlerklassen sieht man im Standbild **nicht**, im Lauf aber sofort:

1. **Leere Frames.** Eine Zeile verschwindet, bevor die nächste kommt — ein sichtbarer
   Aussetzer von zwei, drei Frames. Beim ersten Durchgang waren es 62 Stück.
   `pruefen.py --fix` schliesst sie, indem es `out` bis zum nächsten Layer-Start zieht.
2. **Stillstand.** Löcher ohne jedes Ereignis. Fünf Beats *dürfen* still stehen — dort ist
   die Stille die Pointe (`Moment./Nein.`, beide geflüsterten Einwürfe, `NEIN.`,
   `(auch nicht im UI)`). Sie stehen in der Liste `HALT` und werden übersprungen.

Dazu die Tempokontrolle gegen den Referenzfilm. Wichtig: die Prüfung zählt auch die
**einzelnen Wörter** eines Wort-für-Wort-Aufbaus — wer nur Layer-Startzeiten zählt,
misst sich um den Faktor drei zu langsam.

## Dateien

**Quelle der Wahrheit**

| Datei | Zweck |
|---|---|
| `timing.json` | **Die einzige Datei, die nach der VO-Aufnahme angefasst wird.** Alle Zeiten, Texte, Layer. Bild UND Ton entstehen daraus. |
| `film.html` | Render-Engine. `window.renderAt(t)` ist deterministisch — gleiche `t` ergibt bitgleichen Frame. |
| `fonts/` | **Prototyp-Schriften** (Inter SemiBold, Permanent Marker). Für die Endfassung ersetzen — siehe unten. |

**Bild**

| Datei | Zweck |
|---|---|
| `render.py` | Playwright → PNG-Frames → ffmpeg → ProRes, ein Clip je Szene. |
| `bauen.py` | Prüft (läuft ein Render? Clips vollständig? Fingerabdrücke aktuell?) und baut erst dann zusammen. |
| `fcpxml.py` | Timeline mit Markern für Akt, Szene und Sprechertext. |

**Timing**

| Datei | Zweck |
|---|---|
| `takt.py` | Legt `timing.json` auf das 118-BPM-Raster und zieht die Ereignisse auf echte Anschläge. Sicherung als `timing.json.vor-takt` (nicht im Repo). |
| `pruefen.py` | Vier Prüfungen: Zeitachse, leere Frames, Stillstand, Tempo. `--fix` repariert Löcher. |
| `sync.py` | Zieht das Timing auf die echte Sprecheraufnahme — aus dem FCP-Schnitt oder per Whisper. |

**Ton**

| Datei | Zweck |
|---|---|
| `musik.py` | Musikspur auf den Film legen — Loop arrangieren oder Track schneiden. Schreibt zusätzlich die Anschlagszeiten für `takt.py`. |
| `video_music.py` | Dekodiert eine Video-Tonspur oder schaetzt modular eine No-Vocals-Musikreferenz; schreibt verifizierte WAV-, Segment-, Profil- und Manifestdateien. |
| `music_separation.py` | Waehlt den gepinnten Demucs-Basisweg oder einen expliziten lokalen RoFormer-Adapter und prueft dessen Ausgaben. |
| `audio_segmentation.py` | Schreibt lokale Musik-/Sprach-/SFX-/Stille-Wahrscheinlichkeiten je Zeitsegment; Silero liefert optionale Sprachzeitstempel. |
| `proben.py` | Schneidet echte Schläge aus dem Musikloop → `out/_proben/` (die Klangpalette). |
| `groove.py` | Zieht menschliches Spielgefühl aus dem Groove MIDI Dataset: je Instrument und Sechzehntelposition der mediane Versatz zum Raster und die Anschlagstärke. Gemessen an 220 Aufnahmen, 3408 Takten. |
| `abhoeren.py` | Transkribiert eine Vorlage Schlag für Schlag: Position, Stärke, Versatz und Abklingzeit je Anschlag → `partitur.json`. Der Weg für einen **1:1-Nachbau**. |
| `partitur.py` | Komponiert 68 Takte Drumline auf die Dramaturgie — Motive, Call-and-Response, Geisternoten, Flams, Wirbel. Noten, kein Klang. |
| `drumline.py` | Spielt die Partitur mit den echten Trommeln und dem menschlichen Timing → `out/drumline.wav`. |
| `vcsl.py` | Holt eine Sparse-Auswahl echter Bassdrums, Snares, Toms, Handdrums, Holz-Percussion und Hi-Hats aus der Versilian Community Sample Library (CC0 1.0) → `out/_vcsl/`; mit Velocity-Layern und Round Robins. |
| `reference_drums.py` | Baut daraus vier profilgesteuerte Musikrollen. Waehlt echte Aufnahmen je Anschlag, stimmt und kuerzt sie, formt Transienten und Frequenzbalance, ohne Referenz-Audio zu uebernehmen. |
| `reference_arrangement.py` | Gemeinsamer, klangloser Ereignisplan fuer lokalen Hoertest und GarageBand: neue Motive, Microtiming, Dramaturgie und Platz fuer SFX. |
| `music_reference.py` | Komponiert gelernte Vier-Takt-Motive fuer den Film und liefert getrennte `low`-, `body`-, `tonal`- und `detail`-Stems plus Master. |
| `cuesheet.py` | 139 Hit Points → `out/analysis/cue_sheet.json`. Die Vorlage zum Komponieren. |
| `sfx.py` | Sounddesign aus Cue Sheet und Palette: impact, whoosh, click, tick, riser. |
| `sounddesign.py` | Nur noch die **optionale** eigene Drumline (`--drums`). Musik und Effekte kommen aus `musik.py` bzw. `sfx.py`. |
| `mischen.sh` | Endmischung. Ein Filtergraph, vier Schalter. |

**Stimme**

| Datei | Zweck |
|---|---|
| `scratchvo.py` | Wegwerf-Stimme aus `timing.json` (Piper, offline). **Standard.** |
| `xttsvo.py` | XTTS-v2. **Nicht kommerziell nutzbar** — nur als internes Timing-Muster. |
| `qwenvo.py` | Qwen3-TTS über den HF-Space. Apache 2.0, also kommerziell nutzbar. Braucht `HF_TOKEN`. |

**Ausgabe und Doku**

| Datei | Zweck |
|---|---|
| `drehbuch.py` | Erzeugt Abschnitt 4 des Konzepts aus `timing.json` — Dokument und Film können nicht auseinanderlaufen. |
| `paket.sh` | Bündelt Filme, Timeline, Tonspur, Standbilder und Quellen → `out/NEXPT-Keynote-Paket.zip`. |

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

## Die Stimme passend machen — ohne stundenlang zu schieben

`sync.py` schreibt die gemessenen Ist-Zeiten in `timing.json` zurück. Danach einmal
`render.py`, und **jede Animation sitzt frame-genau auf der echten Stimme.** Zwei Wege:

### Weg A — aus dem Schnitt zurücklesen *(massgeblich)*

Du hörst, der Code rechnet nach. Du schiebst in FCP nach Gefühl, bis es sitzt, exportierst
das Projekt als XML und lässt die Animation nachziehen:

```bash
# in FCP:  Ablage → Exportieren → XML …   → Projekt.fcpxml
python3 render/sync.py Projekt.fcpxml
python3 render/render.py
```

Der Umlauf ist verlustfrei geprüft: exportiert und zurückgelesen ergibt bit-identische Zeiten.
Das ist der Weg, dem man trauen kann — er rät nichts.

### Weg B — die Tonspur vermessen *(erster Wurf)*

```bash
python3 render/sync.py vo.wav
```

**Whisper hört die Aufnahme ab** und liefert Wort-Zeitstempel. Die erkannten Wörter werden
gegen das Drehbuch abgeglichen (`difflib`, verträgt Erkennungsfehler), und daraus steht fest,
wo jede Szene beginnt — unabhängig davon, wo der Sprecher Luft geholt hat. Am Scratch-Take
gemessen: 96 % der Drehbuchwörter zugeordnet.

Das Werkzeug meldet die Deckungsquote, prüft jede Szene auf Plausibilität und **weigert
sich zu raten**, wenn unter 55 % zugeordnet werden. Optionen: `--model medium` (genauer,
langsamer), `--silence` (ohne Whisper, nur Pausenmessung), `--dry` (nur zeigen).

**Weg B ist der schnelle erste Wurf, Weg A die Wahrheit.** Whisper kann sich verhören;
FCPXML kann es nicht.

### Stimme erzeugen — und was nicht geht

| Werkzeug | Status |
|---|---|
| **Piper** (`scratchvo.py`) | läuft, offline, CPU. Frei nutzbar. **Standard.** |
| **XTTS-v2** (`xttsvo.py`) | läuft, aber nur in einem eigenen venv — es ist mit der Whisper-Toolchain (transformers 5.x) nicht verträglich. **Coqui Public Model License: nicht kommerziell.** Nur als internes Timing-Muster. |
| **Qwen3-TTS** (`qwenvo.py`) | lokal **nicht** lauffähig — weder `transformers 5.16` noch git main kennen den Typ `qwen3_tts`. **Über den offiziellen HF-Space aber schon**, auf GPU. Braucht ein kostenloses `HF_TOKEN`; anonym reicht die Quote für rund einen Aufruf. Schickt den Text an einen öffentlichen Dienst. |
| **ElevenLabs** | echtes TTS, kommerziell nutzbar — braucht einen API-Schlüssel und schickt den Text an einen externen Dienst. |
| *Whisper-Modelle* | **erzeugen keine Stimme.** Sie erkennen Sprache — siehe Synchronisation oben. |

#### Qwen3-TTS über den Space

```bash
export HF_TOKEN=hf_...                    # huggingface.co/settings/tokens, Read genügt
python3 render/qwenvo.py                  # fester Sprecher, über alle Zeilen gleich
python3 render/qwenvo.py --speaker Dylan --size 0.6B
python3 render/qwenvo.py --design         # Stimme aus einer Beschreibung
```

Drei Endpunkte stehen zur Verfügung: `generate_custom_voice` (neun feste Sprecher plus
Regieanweisung), `generate_voice_design` (Stimme aus einer Beschreibung) und
`generate_voice_clone`.

**Für eine durchgehende Sprecherstimme den festen Sprecher nehmen.** `voice_design` erzeugt
die Stimme bei jedem Aufruf neu — über 31 Zeilen kann sie abweichen. Die Regieanweisung ist
dieselbe wie im Drehbuch: *trocken, wach, leicht amüsiert, kein Werbeton, kein Pathos.*

#### Eigene Stimme klonen

```bash
export HF_TOKEN=hf_...
python3 render/qwenvo.py --ref meine-stimme.wav      # nutzt out/referenztext.txt
python3 render/sync.py out/vo-klon.wav               # Animation darauf ziehen
python3 render/render.py
```

**Qwen3-TTS steht unter Apache 2.0** und darf kommerziell verwendet werden — deshalb der
Weg für den Messefilm. XTTS-v2 (`xttsvo.py --ref`) klont ebenfalls, ist aber nicht
kommerziell lizenziert.

Der Klon-Endpunkt braucht neben der Aufnahme den **exakten Wortlaut** der Referenz. Darum
ist `out/referenztext.txt` aus dem echten Drehbuch gebaut: der Wortlaut steht fest, und die
Stimme ist beim Einsprechen schon im richtigen Register.

**Aufnahme:** ruhiger Raum ohne Hall, 15–25 cm Abstand, leicht seitlich sprechen, ~80
Sekunden am Stück, Hochdeutsch (die Modelle können kein Schweizerdeutsch). Handy-Sprachmemo
genügt.

**Klonen nur mit Einwilligung der sprechenden Person.** Eine fremde Stimme aus einem fremden
Film zu klonen und als eigene Markenstimme einzusetzen, ist keine Option.

### Scratch-Stimme

```bash
python3 render/scratchvo.py                  # neuronale Stimme (Piper, de_DE-thorsten)
python3 render/scratchvo.py --voice kerstin  # oder eva_k
python3 render/scratchvo.py --rate 1.08      # langsamer (>1) / schneller (<1)
python3 render/scratchvo.py --autofit        # zu kurze Szenen automatisch verlängern
```

Nicht für den Film: der Sprecher muss ein Mensch sein — „Moment. Nein." lebt von trockenem
Timing, das keine Synthese trifft. Aber die Spur macht in zwei Minuten **messbar**, welche
Zeile zu lang ist. Der Bericht am Schluss stellt geplant gegen gesprochen:

```
Szene               geplant  gesprochen   Befund
16_pfeile             3.00s       4.26s   ⚠ +1.26s  zu lang
17_hundert            2.00s       3.91s   ⚠ +1.91s  zu lang
25_seht               4.00s       2.87s     -1.13s  viel Luft
```

`--autofit` verlängert die zu kurzen Szenen und schreibt `timing.json` neu — **nur
verlängern, nie kürzen**: „viel Luft" ist oft Absicht, dort läuft nach dem Satz noch eine
Animation (Unterstrich, Stufen, Vokabelflut). Zwei bis drei Durchläufe konvergieren.

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
