# Reference audio to editable GarageBand tracks

Filmton kann vor der Transkription in **Musik, Dialog und SFX** zerlegt werden.
Nur `music.wav` wird an den GarageBand-Workflow uebergeben; Effekte bleiben
separat. Siehe [Reference Decomposition](../render/DECOMPOSITION.md).
Demucs-/RoFormer-Separation wird mit der Video-Pipeline geteilt. Beide
Transkriptions-CLIs unterstuetzen `--separate roformer --roformer-command PATH`.

## Generative Erweiterung mit claude-music und ACE-Step

[`AgriciDaniel/claude-music`](https://github.com/AgriciDaniel/claude-music)
ist als unveränderte, MIT-lizenzierte Kopie unter `tools/claude-music/`
eingebunden. Der NEXPT-Adapter verändert den Upstream nicht. Er ergänzt den
bisherigen GarageBand-Workflow um sechs lokale Audiooperationen:

- Text → Musik (`generate`)
- Referenz → neue Stilvariante (`cover`)
- Abschnitt neu erzeugen (`repaint`)
- Spuren extrahieren (`extract`)
- Instrumentebene ergänzen (`lego`)
- Musik verlängern (`complete`)

Die Trennung bleibt absichtlich erhalten:

```text
Text oder Referenz
        ↓
claude-music / ACE-Step
        ↓
verifizierte WAV + SHA-256
        ├── unverändert als GarageBand-Audiospur
        └── garageband/workflow.py
                 ↓
          approximative MIDI-/Instrumentspuren
          + unveränderte A/B-Referenz
```

ACE-Step und die Modellgewichte sind nicht im Repository. Die schnelle
Generierung benötigt normalerweise einen NVIDIA-/CUDA-Rechner; GarageBand
läuft anschließend auf dem Mac. Beide Schritte dürfen daher auf getrennten
Rechnern stattfinden.

Konfiguration:

```bash
cp garageband/ai-music.example.json garageband/ai-music.json
# ace_step_dir in der lokalen, ignorierten Datei anpassen

python3 -m garageband.generative status
python3 -m garageband.generative plan \
  garageband/ai-music-request.example.json
python3 -m garageband.generative generate \
  garageband/ai-music-request.example.json
```

Der `plan`-Befehl erzeugt keine Datei und startet kein Modell. `generate`
verwendet keine Shell-Strings, akzeptiert höchstens vier Kandidaten, prüft den
JSON-Vertrag des Upstreams und verifiziert jede Ausgabedatei mit SHA-256.
Bestehende Quelldateien werden nicht überschrieben.

Für MCP ersetzt `garageband/mcp-config.example.json` die bisherige direkte
Konfiguration des Upstream-Servers. Der kombinierte Server stellt alle
bisherigen GarageBand-Tools und zusätzlich bereit:

- `garageband_ai_status`
- `garageband_ai_plan`
- `garageband_ai_generate`
- `garageband_ai_handoff_plan`
- `garageband_ai_generate_and_handoff`

Ein Handoff-Plan mit echter GarageBand-UI-Aktion verlangt explizit
`acknowledge_live_ui=true`. Standardmäßig wird lediglich die geprüfte
Generierungs- oder Rekonstruktionsplanung zurückgegeben.

There are now two deliberately separate workflows:

| Goal | Command | Behavior |
|---|---|---|
| create a new, reference-inspired drum performance | `garageband/compose.py` | learns descriptors, then composes new events |
| reconstruct the supplied instrumental before editing it | `garageband/transcribe.py` | preserves source timing, detects notes/instruments and generates matching GarageBand patch selections |
| run the guarded end-to-end reconstruction | `garageband/workflow.py` | stages artifacts, verifies hashes/contracts, applies quality gates and optionally prepares GarageBand |
| measure a GarageBand export against the source | `garageband/evaluate.py` | reports duration, onset, chroma and structural similarity without claiming recovered originals |

For the copy-first workflow, including the original 1:1 A/B track, separate
instrument-specific MIDI tracks, all 128 General MIDI programs, GarageBand
world/synth extensions and confidence-aware installed-patch selection inside
the GarageBand project, see [TRANSCRIPTION.md](./TRANSCRIPTION.md).

Before the first high-quality transcription on a Mac, inventory the actual
Sound Library. This avoids assuming that every GarageBand installation has the
same version, language or downloaded packs:

```bash
python3 garageband/session.py inventory \
  --track-index 1 \
  --output garageband/catalogs/installed-patches.json
```

Pass that file to `garageband/transcribe.py --garageband-inventory ...`.

For the normal copy-first path, prefer the product-level command:

```bash
python3 garageband/workflow.py "/path/to/instrumental.m4a" \
  --quality high \
  --garageband-inventory garageband/catalogs/installed-patches.json \
  --require-inventory --prepare-dry-run
```

It writes one ignored arrangement workspace with source/configuration hashes,
Score JSON, MIDI, preset, analysis reports and a quality gate. Use
`--resume --prepare` on the Mac to reuse exactly those verified artifacts.

The code can now analyze an MP3/M4A, learn its rhythmic language and create a
new four-track performance for recorded GarageBand kits. Music and sound
effects remain separate from analysis through final export.

It does **not** recover the original samples, MIDI or stems from a finished
stereo file. That is mathematically underdetermined. It measures tempo,
sixteenth-note probabilities, four-bar behavior, dynamics, microtiming,
frequency families and arrangement energy, then writes a new performance
that follows those principles without embedding source audio.

## The actual pipeline

```text
Reference MP3/M4A
        |
        v
render/reference_analyzer.py
        |
        +-- out/analysis/reference-profile.json
        |      descriptors only; no copied samples
        v
render/reference_arrangement.py
        |      one shared, deterministic event plan
        +-----------------------------+
        |                             |
        v                             v
local listening preview          garageband/compose.py
(CC0 samples/procedural)              |
                                      +-- Score Spec JSON
                                      +-- four-track MIDI
                                             |
                                             v
                                  garageband/session.py (macOS)
                                             |
                              recorded kit patches + mix + WAV

Sound effects: render/sfx_original.py -> out/sfx-original.wav
Music:        GarageBand             -> out/music-garageband.wav
```

`reference_arrangement.py` is the important seam: the local preview and the
GarageBand export consume the exact same newly generated events. A preview can
no longer sound rhythmically different merely because it used another output
engine.

## 1. Analyze and prepare the GarageBand score

From the repository root, on Linux or macOS:

```bash
python3 render/reference_pipeline.py "/path/to/reference.m4a" \
  --bpm 118 --downbeat 0 \
  --garageband --skip-local-music --skip-kit --skip-compare
```

This writes:

| File | Purpose |
|---|---|
| `out/analysis/reference-profile.json` | private, local descriptor profile |
| `garageband/scores/nexpt-work-68.json` | auditable Bridge Score Spec v1 |
| `garageband/scores/nexpt-work-68.mid` | four independent MIDI tracks |
| `out/sfx-original.wav` | separate sound-effect stem |

To rebuild the score from an existing profile:

```bash
python3 garageband/compose.py --midi
python3 garageband/compose.py --bericht
```

The current mapping is deliberately split into four tracks:

| Learned role | GarageBand track | Drum articulations |
|---|---|---|
| `low` | `NEXPT Low` | kick |
| `body` | `NEXPT Body` | snare, rim |
| `tonal` | `NEXPT Tonal` | low/mid/high tom |
| `detail` | `NEXPT Detail` | closed/open hat, ride, crash |

Each role uses a separate MIDI channel. GarageBand therefore retains separate
tracks and the Mac runner can choose a recorded patch, volume and pan for each
one. A silent MIDI-0 timeline anchor ends precisely on beat 272, so the
imported arrangement remains exactly 68 bars long.

## 2. Check the Mac before touching GarageBand

```bash
python3 garageband/session.py doctor
python3 garageband/session.py render --dry-run
```

`doctor` validates the score with the bundled Bridge on every platform. On a
Mac it also reports whether GarageBand is installed and shows the required
permissions. Grant the terminal or Codex app:

- System Settings > Privacy & Security > Accessibility
- System Settings > Privacy & Security > Automation > GarageBand

The dry run prints every planned command but does not open, click or export
anything.

## 3. Render through recorded GarageBand kits

On the Mac:

```bash
python3 garageband/session.py render \
  --output out/music-garageband.wav
```

The runner performs and verifies these stages:

1. validate the Score Spec;
2. generate/import its MIDI into GarageBand;
3. inspect the visible imported track names;
4. select each track;
5. search the installed Library for the configured patch;
6. apply the patch and per-track volume/pan;
7. re-inspect the visible tracks after all patch and mix changes;
8. capture a verification screenshot;
9. export WAVE through GarageBand;
10. verify the audio header and reject an export shorter than the 68-bar score;
11. write `garageband/arrangements/nexpt-work-68/session-result.json`.

Existing audio is never overwritten unless `--overwrite` is explicit. An
unsaved GarageBand project is never discarded unless `--discard-unsaved` is
explicit.

## Installed kits vary

The default preset is
[`presets/recorded-kit.json`](./presets/recorded-kit.json). It requests the
recorded `SoCal` patch for all four role tracks so the performance sounds like
one coherent kit. GarageBand version, language and downloaded sound packs can
change Library names. The runner therefore does not silently choose a random
replacement: if the preferred patch is absent, it stops and reports the
visible results.

Discover patches on the selected Mac:

```bash
python3 garageband/session.py discover Drums --track-index 1
python3 garageband/session.py discover Percussion --track-index 3
```

Copy an exact returned name into `patch.preferred` in the preset. Set
`allow_first` to `true` only if choosing the first visible match is acceptable.

## Music and sound effects stay separate

GarageBand receives only the musical score. SFX are produced from the film cue
sheet by `render/sfx_original.py`; they are not learned from the music reference
and are never baked into the MIDI. The final mix receives two explicit files:

```text
out/music-garageband.wav
out/sfx-original.wav
```

This keeps later changes safe: a kit, groove or music level can change without
regenerating motion/UI effects, and an SFX edit cannot alter the music.

## Ownership boundary

| Path | Ownership |
|---|---|
| `render/reference_analyzer.py` | reference measurements |
| `render/reference_arrangement.py` | new groove, timing and dramatic arc |
| `garageband/compose.py` | role-to-drum mapping and Score Spec |
| `garageband/session.py` | NEXPT-specific Mac recipe |
| `garageband/workflow.py` | guarded orchestration, hash-bound resume and quality gates |
| `garageband/evaluate.py` | technical source/export A/B measurement |
| `garageband/generative.py` | safe claude-music/ACE-Step adapter and verified GarageBand handoff |
| `garageband/mcp.py` | combined upstream GarageBand MCP plus generative tools |
| `garageband/presets/` | selected installed kits and mix values |
| `tools/garageband-llm-bridge/` | unchanged upstream Bridge copy |
| `tools/claude-music/` | unchanged pinned claude-music copy |

NEXPT-specific logic does not modify the Bridge. The copied Bridge is the
unmodified MIT-licensed upstream at commit `f3d12e8`; provenance and update
instructions are in
[`tools/garageband-llm-bridge/HERKUNFT.md`](../tools/garageband-llm-bridge/HERKUNFT.md).
Its deterministic test suite runs without GarageBand; only UI automation and
audio export require a real Mac.

Die zweite Upstream-Kopie ist `claude-music` am Commit `5aa0173`; Herkunft,
Lizenz und Updategrenze stehen in
[`tools/claude-music/HERKUNFT.md`](../tools/claude-music/HERKUNFT.md). Die
NEXPT-Tests benötigen weder GPU noch ACE-Step. Eine echte Generierung benötigt
die separat konfigurierte ACE-Step-Installation.

## Verification

```bash
python3 -m unittest tests/test_garageband_e2e.py -v
python3 -m unittest \
  tests/test_garageband_session_unit.py \
  tests/test_garageband_transcription_unit.py \
  tests/test_garageband_workflow.py \
  tests/test_garageband_evaluate.py -v
python3 -m unittest discover -s tests -v

python3 -m unittest \
  tests/test_garageband_generative.py \
  tests/test_garageband_generative_e2e.py -v

python3 -m pytest -q tools/garageband-llm-bridge/tests
```

The E2E suite crosses the public CLI and file boundaries from audio through
Score JSON/MIDI, Bridge validation and the editable prepare plan. It also
simulates the Mac Library boundary to verify installed exact/family patch
selection, refuses stale patch inventories instead of selecting a random
sound, and rejects exports that are shorter than the generated score. The
workflow tests cross the public CLI, verify staged outputs, hash-bound resume,
overwrite protection and a complete prepare plan. The A/B tests cover
latency-compensated onset matching, pitch-class similarity and strict score
output. The unit tests cover malformed presets/inventories, strict
Score/Preset compatibility, deterministic MIDI-channel fallbacks, exact and
partial patch selection, aliases, manual overrides and Bridge error
normalization. The remaining project tests cover deterministic event planning,
local/Score parity, non-quantized microtiming and exact timeline length.
