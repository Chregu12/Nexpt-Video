# Reference audio to real GarageBand drums

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
7. capture a verification screenshot;
8. export WAVE through GarageBand;
9. verify the audio header and reject an export shorter than the 68-bar score;
10. write `garageband/arrangements/nexpt-work-68/session-result.json`.

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
| `garageband/presets/` | selected installed kits and mix values |
| `tools/garageband-llm-bridge/` | unchanged upstream Bridge copy |

NEXPT-specific logic does not modify the Bridge. The copied Bridge is the
unmodified MIT-licensed upstream at commit `f3d12e8`; provenance and update
instructions are in
[`tools/garageband-llm-bridge/HERKUNFT.md`](../tools/garageband-llm-bridge/HERKUNFT.md).
Its deterministic test suite runs without GarageBand; only UI automation and
audio export require a real Mac.

## Verification

```bash
python3 -m unittest \
  tests/test_reference_audio.py \
  tests/test_garageband_pipeline.py

python3 -m pytest -q tools/garageband-llm-bridge/tests
```

The project tests cover deterministic event planning, local/Score parity,
four independent tracks, Bridge validation, non-quantized microtiming, exact
timeline length, preset validation and the non-mutating dry-run plan.
