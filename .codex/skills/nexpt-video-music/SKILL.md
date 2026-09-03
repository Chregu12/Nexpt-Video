---
name: nexpt-video-music
description: Extract a verified soundtrack or a locally separated music estimate from a video, map music/speech/SFX by time segment, analyze musical traits, and route the artifact into NEXPT's reference-music or editable GarageBand workflows. Use when the user supplies audio or video and asks to extract, isolate, inspect, imitate, or reconstruct its music.
---

# NEXPT video music

Work from the repository root. Keep the source unchanged and place generated
audio below `out/video-music/` unless the user chooses another path.

## Route the request

1. Run `python3 render/video_music.py doctor` before the first extraction. Read
   `ready.music`, `ready.high_music`, the separator versions and speech detector.
2. Determine which artifact the user actually wants:
   - Complete soundtrack, including dialogue and SFX: use `--mode soundtrack`.
   - Music with voice reduced: use `--mode music`. This requires the pinned
     Demucs baseline or an explicitly configured RoFormer adapter. It remains
     an estimate; SFX and vocal remnants can remain.
   - Descriptors only, with no extracted audio: run
     `python3 render/reference_analyzer.py VIDEO --output PROFILE.json` directly.
3. Extract and verify:

```bash
python3 render/video_music.py extract VIDEO \
  --mode soundtrack \
  --output out/video-music/NAME-soundtrack.wav \
  --vad heuristic
```

For an estimated music bed plus acoustic profile:

```bash
python3 render/video_music.py extract VIDEO \
  --mode music \
  --quality high \
  --separator auto \
  --vad auto \
  --output out/video-music/NAME-music-estimate.wav \
  --analyze
```

`--quality high` requires Silero VAD when `--vad auto` is used. An explicit
`--vad heuristic` fallback is allowed, but the run must return
`status: review_required`; do not present it as a passed high-quality run.
Even with Silero, a high-quality run stays `review_required` when any segment
falls below the classifier's review threshold.

To opt into a local RoFormer implementation, set `NEXPT_ROFORMER_COMMAND` or
pass `--roformer-command`. The executable must accept
`--input PATH --output-dir DIR` and write exactly one of `instrumental.wav` or
`no_vocals.wav`; optional `vocals.wav` is recorded. For a passed high-quality
gate it must also write `provenance.json` with nonempty `model`, `version`,
`license`, and the 64-digit `checkpoint_sha256`; otherwise the result is
`review_required`. Do not guess a third-party checkpoint, license or syntax.

4. Read the emitted JSON, manifest and `*.segments.json`. Report the selected
audio stream, hashes, duration, extraction mode, backend/model, quality-gate
status and music/speech/SFX summary. Do not call a run successful when any
declared artifact is missing or its hash differs.

## Continue into NEXPT

Choose one continuation after extraction:

- Build new, sample-free music from measured traits:
  `python3 render/reference_pipeline.py EXTRACTED.wav --preview`
- Reconstruct approximate editable notes and instruments for GarageBand:
  `python3 garageband/workflow.py EXTRACTED.wav --quality high --prepare-dry-run`
- On the GarageBand Mac, resume the verified workflow with `--resume --prepare`
  only after reviewing its quality gate and patch inventory.

Use `--audio-stream N` when a video contains multiple language or mix tracks.
Only use `--overwrite` when the user explicitly intends to replace the named
generated artifact.

## Preserve the contracts

- `soundtrack` preserves audible programme content but converts it to 48 kHz,
  stereo, 24-bit PCM; it is not a byte-identical container copy.
- `music` is an estimated `no_vocals` result, not the original studio music
  stem. It does not reliably remove sound effects.
- Silero supplies trained speech timestamps only. Music/SFX probabilities are
  spectral routing heuristics and require review; they are not ground truth.
- A finished mix cannot reveal exact original stems, MIDI, samples, plug-ins,
  automation, or instrument patches.
- GarageBand notes and patches are an editable approximation. Keep the extracted
  audio as the immutable A/B reference track.
- Never commit uploaded references, extracted audio, Demucs work files, or
  generated GarageBand projects. Commit only code, tests, schemas, and docs.
