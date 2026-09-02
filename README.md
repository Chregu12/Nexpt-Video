# Nexpt-Video

Keynote-Film für **NEXPT Work** — Konzept, Drehbuch und lauffähige Pipeline vom Text bis
zur fertigen Tonmischung.

**2:18.3 · exakt 68 Takte à 118 BPM · 30 Szenen · 1920×1080/30p**

---

## Wo was liegt

### Lesen

| | |
|---|---|
| [**KEYNOTE-FILM-KONZEPT.md**](./KEYNOTE-FILM-KONZEPT.md) | Das Hauptdokument. Frame-für-Frame-Analyse der Referenzfilme, 13 Stil-Regeln, Story, vollständiges Drehbuch, Design-Spezifikation, Tonkonzept, Produktionsplan, offene Fragen. |
| [**MUSIK-BRIEFING.md**](./MUSIK-BRIEFING.md) | Was für die Musik noch fehlt, warum ich es nicht selbst machen kann, und die genaue Bestellung für die vier fehlenden Blöcke. |
| [**garageband/README.md**](./garageband/README.md) | Der GarageBand-Weg: Partitur bei uns, Klang aus echten Drum Kits. Was wo läuft, und warum die letzten drei Schritte einen Mac brauchen. |
| [**garageband/TRANSCRIPTION.md**](./garageband/TRANSCRIPTION.md) | Instrumental zuerst als editierbare Spuren rekonstruieren, mit einer unveraenderten 1:1-Referenzspur vergleichen und danach direkt in GarageBand anpassen. |
| [**motion/README.md**](./motion/README.md) | Apple-Motion-MCP: Animationen als JSON beschreiben, echte Motion-Templates sicher befüllen und die Mac-App kontrolliert über Bedienungshilfen steuern. |
| [**higgsfield/README.md**](./higgsfield/README.md) | Seedance-2.0-Bridge: Cloud-Clips über serverseitige Env-Secrets erzeugen, Referenzen sicher hochladen und geprüfte MP4-Dateien an Final Cut und Motion übergeben. |
| [**render/README.md**](./render/README.md) | Die Pipeline: was jedes Skript tut, in welcher Reihenfolge es laufen muss, und warum es so gebaut ist. |

### Ansehen und anhören

| | |
|---|---|
| **out/NEXPT-Keynote-ANIMATIC-OHNE-STIMME.mp4** | **Die Fassung zum Anschauen.** Bild, Musik und Sounddesign, ohne Sprache — der ehrlichere Blick auf Rhythmus und Effekte. |
| **out/NEXPT-Keynote-ANIMATIC-SCRATCH.mp4** | Dasselbe mit der Roboter-Scratchstimme als Platzhalter fürs Timing. |
| **out/NEXPT-Keynote-DRUMLINE-OHNE-STIMME.mp4** | Der Nachbau der Vorlage aus eigenen Trommeln. Liegt als **Beleg einer Sackgasse** bei, nicht als Fassung zur Auswahl — warum, steht in `render/README.md` unter `abhoeren.py`. |
| **out/NEXPT-Keynote-ANIMATIC-OHNE-EFFEKTE.mp4** | Dieselbe Mischung ohne Sounddesign, zum Vergleichen. |
| **out/NEXPT-Keynote-ANIMATIC.mp4** | Nur Bild, ganz ohne Ton. |
| **out/stills/** | Ein Standbild je Szene. |

### Weiterverarbeiten

| | |
|---|---|
| **out/NEXPT-Keynote.fcpxml** | Timeline für Final Cut Pro, 30 Clips mit Markern für Akt, Szene und Sprechertext. |
| **out/analysis/samsung/** | Die gelieferte Analyse des Referenzfilms — Report, JSON und 54er-Cue-Sheet. Die Zahlen darin sind die Zielwerte, gegen die `sfx.py` kalibriert. |
| **out/analysis/cue_sheet.json** | **114 Hit Points**: Zeit, Takt.Zählzeit, Szene, Art, Stärke, Stereoposition. Die Vorlage zum Komponieren — das, was ein Komponist oder Sounddesigner braucht. |
| **out/ton-final.wav** | Die fertige Mischung. Daneben `ton-final-ohne-stimme.wav` und `ton-ohne-effekte.wav`. |
| **out/sfx.wav** · **out/scratch-vo.wav** | Die Einzelspuren. Die Musikspur liegt nicht im Repo, siehe unten. |
| `out/drums.wav` | Die optionale eigene Percussion. Standardmässig **nicht** in der Mischung — sie auf einen Schlagzeugtrack zu legen ergibt Matsch. Mit `sh render/mischen.sh --drums`. |
| `out/music-garageband.wav` · `out/sfx-original.wav` | Neue Musik aus echten GarageBand-Kits und die weiterhin getrennte Effektspur. Der GarageBand-Export entsteht auf dem Mac. |
| `out/scratch-vo-xtts.wav` · `out/probe-qwen3-tts.wav` | Stimm-Muster aus zwei anderen Verfahren, zum Vergleichen. XTTS ist **nicht kommerziell nutzbar**, Qwen3-TTS schon — Details in [render/README.md](./render/README.md). |

### Nicht im Repo

| | |
|---|---|
| `out/_musik/` | Der Musiktrack. Die Lizenz hängt am Lizenznehmer, nicht am Repository — eigene Kopie dort ablegen, dann `python3 render/musik.py`. |
| `out/music.wav` | Der blosse Schnitt daraus. Wird von `musik.py` erzeugt. |
| `out/_proben/` | Die aus dem Loop geschnittene Klangpalette. Wird von `proben.py` erzeugt. |
| `out/_groove/` | Groove MIDI Dataset (Magenta, CC BY 4.0) — 1150 Aufnahmen echter Schlagzeuger. Mit `python3 render/groove.py --laden`. |
| `out/_vcsl/` | Sparse-Auswahl echter Drums und Percussion aus der Versilian Community Sample Library — **CC0 1.0**, mit `python3 render/vcsl.py` wiederherstellbar. |
| `out/scenes/*.mov` | ProRes 422 HQ, ein Clip je Szene (267 MB). Mit `python3 render/render.py`. |
| `render/fonts/`, `render/voices/*.onnx`, `render/asr/whisper-*/` | Schriften, Stimm- und Spracherkennungsmodelle. Je mit eigenem Ladeskript. |

---

## Schnellstart

```bash
pip install playwright && python3 -m playwright install chromium
```

**Nur das Bild neu bauen** (nach einer Änderung an `timing.json` oder `film.html`):

```bash
python3 render/pruefen.py        # Zeitachse, leere Frames, Tempo
python3 render/render.py         # 30 ProRes-Clips
python3 render/bauen.py          # prüfen und zusammenbauen
```

**Nur den Ton neu bauen** (Bild bleibt, wie es ist):

```bash
python3 render/musik.py          # Musik auf den Film legen
python3 render/proben.py         # Klangpalette aus dem Loop schneiden
python3 render/vcsl.py           # echte Trommeln holen (CC0, einmalig)
python3 render/cuesheet.py       # Hit Points
python3 render/sfx.py            # Sounddesign
sh render/mischen.sh             # Mischung
python3 render/bauen.py          # neu muxen (Bild wird nicht neu kodiert)
```

**Alles neu, nach einem Musikwechsel.** Die Reihenfolge ist hier nicht beliebig: der Film
ist auf die Anschläge *eines bestimmten* Tracks gerastert. Wer die Musik tauscht, ohne
`takt.py` und den Render nachzuziehen, fällt auf Zufallsniveau zurück — gemessen 21 % statt
45 %.

```bash
python3 render/musik.py <neue-quelle>    # 1. Anschläge in Filmzeit schreiben
python3 render/proben.py <neue-quelle>   # 2. Klangpalette neu schneiden
python3 render/takt.py                   # 3. Film auf die neuen Anschläge rastern
python3 render/render.py                 # 4. 30 Clips neu
python3 render/scratchvo.py              # 5. Stimme auf die neuen Zeiten
python3 render/cuesheet.py && python3 render/sfx.py
sh render/mischen.sh && python3 render/bauen.py --neu
```

**Die eigene Partitur statt des Loops:**

```bash
python3 render/vcsl.py           # echte Trommeln (CC0, einmalig)
python3 render/groove.py         # menschliches Timing aus echten Aufnahmen
python3 render/partitur.py       # 68 Takte komponieren
python3 render/drumline.py       # von den echten Trommeln spielen lassen
sh render/mischen.sh --drumline  # damit mischen
```

**Eine Musikreferenz analysieren und daraus eine eigene Klangsprache bauen:**

```bash
python3 render/reference_pipeline.py "/pfad/referenz.m4a" \
  --bpm 118 --downbeat 0 --sound-source samples \
  --download-drums --preview
```

Dabei werden keine Ausschnitte der Referenz weiterverwendet. Ein JSON-Profil
steuert ein Instrument aus echten CC0-Trommelaufnahmen, eine gelernte
Vier-Takt-Rhythmusgrammatik und eine auf das NEXPT-Cue-Sheet zugeschnittene
68-Takt-Komposition. Velocity-Layer und Round Robins wechseln die reale
Aufnahme je Anschlag. Musik (`low`, `body`, `tonal`, `detail`) und SFX bleiben
getrennte Stems. Siehe [render/AUDIO-REWORK.md](./render/AUDIO-REWORK.md).

**Dieselbe gelernte Komposition mit echten GarageBand-Kits vorbereiten:**

```bash
python3 render/reference_pipeline.py "/pfad/referenz.m4a" \
  --bpm 118 --downbeat 0 \
  --garageband --skip-local-music --skip-kit --skip-compare

python3 garageband/session.py doctor
python3 garageband/session.py render --dry-run
```

Die Analyse und MIDI-Erzeugung laufen überall; Kit-Auswahl und WAV-Export nur
auf einem Mac mit GarageBand. `garageband/session.py render` schreibt die Musik
nach `out/music-garageband.wav`. Die SFX bleiben separat in
`out/sfx-original.wav`. Der komplette Ablauf, inklusive Auswahl installierter
Kits, steht in [garageband/README.md](./garageband/README.md).

**Dieselbe Instrumentalmusik zuerst rekonstruieren und danach bearbeiten:**

```bash
python3 garageband/workflow.py "/pfad/instrumental.m4a" \
  --quality high \
  --garageband-inventory garageband/catalogs/installed-patches.json \
  --require-inventory --prepare-dry-run

# Auf dem Mac dieselben per SHA-256 verifizierten Artefakte weiterverwenden:
python3 garageband/workflow.py "/pfad/instrumental.m4a" \
  --quality high \
  --garageband-inventory garageband/catalogs/installed-patches.json \
  --require-inventory --resume --prepare
```

Die Originaldatei bleibt als stummgeschaltete `REFERENCE — Original 1:1`-Spur
im Projekt. Demucs, Basic Pitch und eine hierarchische CLAP-Klassifikation
erzeugen darunter instrumentbezogene MIDI-Spuren. Die Taxonomie deckt alle 128
General-MIDI-Programme und GarageBand-Erweiterungen ab. Ein Mac-Inventar ordnet
die erkannten Instrumente den tatsaechlich installierten Sound-Library-Patches
zu. Confidence und manuelle Overrides decken unsichere Stereo-Mischungen ab.
Der Workflow verhindert stilles Ueberschreiben, bindet Resume an Quelle,
Konfiguration und Artefakt-Hashes und blockiert schwache Transkriptionen vor
der GarageBand-Automation. Nach dem Export bewertet `garageband/evaluate.py`
Dauer, Onsets, Pitch Classes und Klangprofil gegen die Originalspur.
Grenzen und der genaue Mac-Ablauf stehen in
[garageband/TRANSCRIPTION.md](./garageband/TRANSCRIPTION.md).

**Musikkandidaten lokal mit ACE-Step erzeugen und an GarageBand übergeben:**

```bash
cp garageband/ai-music.example.json garageband/ai-music.json
python3 -m garageband.generative status
python3 -m garageband.generative plan garageband/ai-music-request.example.json
```

Die eingebundene `claude-music`-Engine kann instrumentale Kandidaten erzeugen,
Referenzen in einen neuen Stil überführen und Abschnitte neu generieren. Der
Adapter prüft die Audioausgaben und übergibt sie wahlweise unverändert oder an
die bestehende editierbare GarageBand-Rekonstruktion. Details und die
kombinierte MCP-Konfiguration stehen in
[garageband/README.md](./garageband/README.md).

**Animationen in Apple Motion vorbereiten und per MCP steuern:**

```bash
python3 -m motion.cli validate-spec motion/examples/nexpt-kinetic-title.json
python3 -m motion.cli capabilities
python3 -m motion.cli ui-snapshot --max-depth 5   # auf einem Mac mit Motion
```

Der Motion-Bridge nutzt ein echtes, mit der installierten Motion-Version
gespeichertes Basistemplate und erzeugt daraus sichere Arbeitskopien. Er kann
veröffentlichte oder per Accessibility gefundene Regler binden, Projekte
öffnen und speichern, den Exportdialog öffnen und Screenshots zur Kontrolle
erstellen. Das interne `.motn`-Format wird bewusst nicht erfunden oder blind
umgeschrieben. MCP-Konfiguration, Animationsschema und Mac-Einrichtung stehen
in [motion/README.md](./motion/README.md).

**Seedance-2.0-Clips über Higgsfield vorbereiten:**

```bash
export HIGGSFIELD_API_KEY_ID='...'
export HIGGSFIELD_API_KEY_SECRET='...'
export HIGGSFIELD_SEEDANCE_ENDPOINT='/endpoint-aus-higgsfield-cloud'

python3 -m higgsfield.cli status
python3 -m higgsfield.cli plan higgsfield/seedance-request.example.json
python3 -m higgsfield.cli generate \
  higgsfield/seedance-request.example.json \
  --acknowledge-paid-generation
```

Lokale Bild-, Video- und WAV-Referenzen werden über offizielle Presigned URLs
hochgeladen. Der asynchrone Job wird mit Backoff abgefragt; das Ergebnis wird
als MP4 und Manifest unter `out/higgsfield/` gespeichert und für Final Cut und
Motion ausgewiesen. Secrets erscheinen weder im Plan noch im MCP-Ergebnis.
Schnittstellenstand und Einschränkungen stehen in
[higgsfield/README.md](./higgsfield/README.md).

**Varianten des Tons:**

```bash
sh render/mischen.sh --ohne-stimme     # Standloop-Fassung
sh render/mischen.sh --ohne-effekte    # ohne Sounddesign, zum Vergleich
sh render/mischen.sh --drums           # zusätzlich die eigene Percussion
python3 render/sfx.py --pegel 0.6      # Sounddesign leiser
```

**Wenn die echte Stimme da ist:**

```bash
python3 render/sync.py <vo.wav|Projekt.fcpxml>   # Timing darauf ziehen
```

---

## Die Idee in drei Sätzen

`timing.json` ist die einzige Quelle der Wahrheit. Bild, Stimme, Musikraster, Cue Sheet und
Sounddesign entstehen alle daraus — kein Werkzeug misst am fertigen Video herum, was es aus
den Autorendaten exakt wissen kann. Und jede Gestaltungsentscheidung ist an den
Referenzfilmen **gemessen**, nicht geraten; wo eine Messung meiner Vermutung widersprochen
hat, steht das im Konzept und im Code.

Produktgrundlage: [Chregu12/Nexpt-2.0](https://github.com/Chregu12/Nexpt-2.0) — `apps/nexpt-work`.
