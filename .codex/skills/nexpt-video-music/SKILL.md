---
name: nexpt-video-music
description: Extract a complete audio track or an estimated speech-reduced music bed from a local video, verify the result, analyze its musical traits, and route it into NEXPT's reference-music or editable GarageBand workflows. Use when the user supplies a video and asks to extract, isolate, analyze, imitate, or reconstruct its music.
---

# NEXPT video music

Work from the repository root. Keep the source unchanged and place generated
audio below `out/video-music/` unless the user chooses another path.

## Route the request

1. Run `python3 render/video_music.py doctor` before the first extraction.
2. Determine which artifact the user actually wants:
   - Complete soundtrack, including dialogue and SFX: use `--mode soundtrack`.
   - Music with voice reduced: use `--mode music`. This requires Demucs and is
     an estimate; SFX and vocal remnants can remain.
   - Descriptors only, with no extracted audio: run
     `python3 render/reference_analyzer.py VIDEO --output PROFILE.json` directly.
3. Extract and verify:

```bash
python3 render/video_music.py extract VIDEO \
  --mode soundtrack \
  --output out/video-music/NAME-soundtrack.wav
```

For an estimated music bed plus acoustic profile:

```bash
python3 render/video_music.py extract VIDEO \
  --mode music \
  --output out/video-music/NAME-music-estimate.wav \
  --analyze
```

4. Read the emitted JSON and its manifest. Report the selected audio stream,
output path, SHA-256, duration, extraction mode, and limitations. Do not call a
run successful when the manifest or output is missing.

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
- `music` is Demucs `no_vocals`, not the original studio music stem. It does not
  reliably remove sound effects.
- A finished mix cannot reveal exact original stems, MIDI, samples, plug-ins,
  automation, or instrument patches.
- GarageBand notes and patches are an editable approximation. Keep the extracted
  audio as the immutable A/B reference track.
- Never commit uploaded references, extracted audio, Demucs work files, or
  generated GarageBand projects. Commit only code, tests, schemas, and docs.
