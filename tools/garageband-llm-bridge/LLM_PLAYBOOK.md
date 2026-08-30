# GarageBand Bridge LLM Playbook

Use this bridge as a cautious visual operator plus MIDI generator. GarageBand does not expose a broad project-editing API, so the reliable pattern is inspect, act once, verify.

## Start Here

```bash
python3 garageband_cli.py --pretty capabilities
python3 garageband_cli.py --pretty self-test --output-dir "./self-test-latest"
python3 garageband_cli.py --pretty recipes
python3 garageband_cli.py --pretty run-plan --file "./examples/safe-smoke-plan.json"
```

`capabilities` includes an `agent_decision_guide` for MCP clients. Use it as the routing layer: high-level tab/image tools for song seeds, menu discovery before menu clicks, path/value UI tools before coordinate clicks, and Library/Smart Controls/Loop searches before selection or dragging.

When the user says "given a band score, make music", prefer the unified route first:

```bash
python3 garageband_cli.py --pretty make-music \
  --score-json-file "./examples/tiny-band-score-spec.json" \
  --output-dir "./score-song" \
  --name "score-song" \
  --no-open
```

Use `--score` for MusicXML, `--score-json-file` or `--score-json` for a structured full score, and `--tab`, `--tab-file`, `--image`, or `--url` for guitar-tab sources. For MCP clients, prefer `garageband_make_music` when the user wants direct music output from any supported source. For tab/image sources, inspect or set `bpm`, `capo`, and `tuning`; the bridge detects common text such as `BPM 140`, `Capo 2`, `Drop D tuning`, or `Tuning: DADGBE`, and it can infer tuning from custom row labels such as `D| A| F#| D| A| D|`. Internal measure bars and technique connectors such as `h`, `p`, `/`, `\`, `b`, `r`, and `~` are ignored for timing. Muted `x`/`X` strums are preserved as short low-velocity guitar hits, and auto-bass skips muted-only onsets. Explicit values override detection.

## Make Music From A Band Score

When the user gives a band score or full score, prefer MusicXML over guitar-tab tools. MusicXML preserves separate parts, so the generated MIDI imports into GarageBand as multiple tracks:

```bash
python3 garageband_cli.py --pretty score-to-midi \
  --score "/path/to/band-score.musicxml" \
  --output "./score-song/band-score.mid"
python3 garageband_cli.py --pretty midi-info "./score-song/band-score.mid"
```

For direct music output, use the high-level recipe:

```bash
python3 garageband_cli.py --pretty make-music \
  --score "/path/to/band-score.musicxml" \
  --output-dir "./score-song" \
  --name "score-song" \
  --export-output "./score-song/score-song.wav" \
  --export-format WAVE \
  --export-overwrite
```

For MCP clients, call `garageband_score_to_midi` when a multi-track MIDI is enough, or `garageband_make_music` when the user wants the score opened in GarageBand or exported as audio. Use `garageband_midi_info` to verify track names, channels, note counts, tempo changes, time-signature changes, rehearsal/section markers, sustain pedal events, and imported volume/pan control changes. MusicXML `score-partwise` and `score-timewise` files are both accepted; `midi-instrument` channel/program/volume/pan metadata is preserved when present, MusicXML transposition is applied so written parts for instruments such as Bb trumpet or piccolo play at sounding pitch, 8va/8vb octave-shift directions are applied to sounding pitch, grace notes are rendered as short MIDI notes before the main note when there is room, harmony/chord symbols are rendered as a generated chord accompaniment track, sustain pedal directions are written as MIDI CC64, drum `score-instrument` names and `midi-unpitched` values map unpitched notes to kick/snare/hat-style GM pitches, specific instrument names such as electric guitar and bassoon are mapped before broader words such as guitar or bass, tied notes are merged into sustained MIDI notes instead of repeated attacks, and single-/multi-measure repeat symbols replay the previous measure group. Simple MusicXML forward/backward repeat barlines and common first/second endings are expanded into actual repeated playback; for coda-style navigation, prefer a notation export with playback unfolded.

If the LLM has already interpreted the full score into parts and notes, skip MusicXML and call `garageband_score_spec_to_midi` or `garageband_make_from_score_spec` with a JSON score spec:

```json
{
  "title": "Tiny Band",
  "bpm": 132,
  "key_signature": "E minor",
  "time_signature": "4/4",
  "parts": [
    {
      "name": "Electric Guitar",
      "instrument": "electric guitar",
      "dynamic": "mf",
      "notes": [
        {"pitch": "E4", "duration": 1},
        {"pitches": ["E4", "G4", "B4"], "duration": 2, "dynamic": "f"}
      ]
    },
    {
      "name": "Drum Kit",
      "is_percussion": true,
      "notes": [
        {"drum": "kick", "duration": 1},
        {"drum": "snare", "duration": 1}
      ]
    }
  ]
}
```

Call `garageband_score_spec_schema` before composing a score object, then `garageband_validate_score_spec` before generating MIDI or opening GarageBand. Use beat units for `start` and `duration`. Omit `start` for sequential notes in a part; use `pitches` for chords; use drum names such as `kick`, `snare`, `closed_hat`, `open_hat`, `crash`, and `ride` for percussion parts. Use top-level `key_signature` for values such as `"Bb major"` or `"E minor"` so GarageBand receives the score's harmonic home as a MIDI key signature event. Use `dynamic` on a part, section, or note for score markings such as `p`, `mp`, `mf`, `f`, `ff`, or `fff`; the bridge maps those into MIDI note velocity so GarageBand imports audible strong/soft phrasing.

For complete song forms, prefer per-part `sections` over one flat `notes` list. A section has `name`, optional `repeat`, optional `dynamic`, optional `articulation`, and `notes`. Section names become MIDI markers, which `garageband_midi_info` can verify. Add a part-level `mix` object for initial GarageBand import balance; `volume`, `pan`, `reverb`, and `chorus` become MIDI control changes. Add top-level `tempo_changes` when the song should speed up or slow down across sections, and `time_signature_changes` when the meter changes. `garageband_midi_info` reports key data as `key_signature`, tempo maps as `tempo_changes`, meter maps as `time_signatures`, section names as `markers`, and mix data as `control_changes`.

```json
{
  "title": "Section Band",
  "key_signature": "E minor",
  "tempo_changes": [{"beat": 0, "bpm": 96}, {"beat": 4, "bpm": 124}, {"beat": 12, "bpm": 132}],
  "time_signature_changes": [{"beat": 0, "time_signature": "4/4"}, {"beat": 12, "time_signature": "6/8"}],
  "parts": [
    {
      "name": "Electric Guitar",
      "instrument": "electric guitar",
      "mix": {"volume": "78%", "pan": -0.25, "reverb": "18%"},
      "sections": [
        {"name": "Intro", "articulation": "staccato", "notes": ["E4:1", "G4:1", "[E4,G4,B4]:2"]},
        {"name": "Verse", "repeat": 2, "dynamic": "mf", "notes": ["E4:1", "G4:1", "B4:1", "G4:1"]},
        {"name": "Chorus", "dynamic": "f", "articulation": "accent", "notes": ["[E4,G4,B4]:2", "[A4,C5,E5]:2"]}
      ]
    }
  ]
}
```

Use `articulation` on a part, section, or individual note for `staccato`, `tenuto`, `legato`, `accent`, or `marcato`. Verify the result with `garageband_midi_info`: staccato/legato show up in `note_length_by_channel`, and accent/marcato show up in `velocity_by_channel`.

For direct audio, call `garageband_make_music` with `score_spec`, `score_json_file`, `export_output`, `export_format`, and `export_overwrite` if replacement is acceptable. Then call `garageband_audio_info` on the exported file to verify it is non-empty and has real duration/channel/sample-rate metadata. The local proof path is `examples/make-score-spec-live/tiny-band-json-live.wav`, generated from `examples/tiny-band-score-spec.json` through GarageBand.

## Make Music From An Online Tab Image

1. Extract tab first:

```bash
python3 garageband_cli.py --pretty image-to-tab --url "https://example.com/tab.png"
```

2. If the extracted tab looks right, create and open the GarageBand seed:

```bash
python3 garageband_cli.py --pretty make-from-tab \
  --url "https://example.com/tab.png" \
  --output-dir "./song-from-image" \
  --name "song-from-image" \
  --bpm 118 \
  --arrange \
  --style rock \
  --repeat-count 2 \
  --show-library \
  --show-smart-controls \
  --discard-unsaved \
  --export-output "./song-from-image/song-from-image.wav" \
  --export-format WAVE \
  --export-overwrite
```

3. Verify:

```bash
python3 garageband_cli.py --pretty ui-snapshot --max-depth 2
python3 garageband_cli.py --pretty screenshot --output "./song-from-image/garageband-proof.png"
```

Use `arrange-image-to-midi` or `make-from-tab --arrange` when you want GarageBand to open a fuller sketch with guitar, bass, and drums instead of only the tab guitar part. Add `--style rock|pop|blues|metal|folk` and `--repeat-count 2` when the source is a short riff that should become a longer song seed.

Local proof for the original online-picture path:

- source image: `examples/online-tab-proof/clear-online-tab.png`
- live export: `examples/online-tab-proof/live-url-export/online-tab-url-live.wav`
- screenshot proof: `examples/online-tab-proof/live-url-export/online-tab-url-live-garageband.png`

The proof was run by serving `examples/online-tab-proof` over local HTTP and calling `make-from-tab --url http://127.0.0.1:8765/clear-online-tab.png ... --export-output ...`, then checking the WAV with `audio-info`.

## Set Project Musical Settings

Read the current musical settings before changing them:

```bash
python3 garageband_cli.py --pretty project-settings
python3 garageband_cli.py --pretty project-setting-options
python3 garageband_cli.py --pretty set-project-settings --tempo 128 --key-signature "C major" --time-signature "4/4"
python3 garageband_cli.py --pretty project-settings
```

For MCP clients, call `garageband_project_settings`, `garageband_project_setting_options`, then `garageband_set_project_settings`, then read again to verify. Key signature and time signature are chosen through GarageBand's own popup menus by typing the target label and confirming it; sharp keys use a tested arrow-key fallback inside the popup. Setting calls report `exact` and `all_exact`; false means GarageBand did not accept that UI change.

## Tracks And Regions

After opening a generated MIDI, call `garageband_list_tracks` and `garageband_list_regions` to inspect what GarageBand made visible. Use `garageband_set_track` with `index` or `name` to adjust visible track headers:

```bash
python3 garageband_cli.py --pretty list-tracks
python3 garageband_cli.py --pretty select-track --index 2
python3 garageband_cli.py --pretty select-track --index 2 --fast
python3 garageband_cli.py --pretty select-track --name "Acoustic Guitar"
python3 garageband_cli.py --pretty set-track --index 1 --mute false --solo false
python3 garageband_cli.py --pretty set-track --name "Acoustic Guitar" --volume 0.75
python3 garageband_cli.py --pretty list-regions
```

Use `select-track` before Library or Smart Controls changes so GarageBand applies them to the intended visible track. Add `--fast` when the visible row index is already known; omit it when you need name matching. Track commands operate on visible track headers. If the target track is out of view, first scroll or zoom the Tracks area with the UI tools.

## Smart Controls

Use Smart Controls when the user wants to shape the selected track's sound, switch Track/Master controls, or inspect EQ/plugin controls:

```bash
python3 garageband_cli.py --pretty smart-controls
python3 garageband_cli.py --pretty set-smart-control --query EQ --action press
python3 garageband_cli.py --pretty set-smart-control --path "window[1]/8/1/3/2" --action press
```

For MCP clients, call `garageband_smart_controls` first. Prefer a returned `path` for `garageband_set_smart_control`; query matching is useful for obvious labels such as `EQ`, `Track`, or `Master`. If `control_count` is `0`, GarageBand is showing an empty Smart Controls state for the selected track/patch, so choose a different Library sound or use the visible tabs.

## Library Sounds

Use Library commands when the user asks for a different GarageBand sound, patch, or instrument flavor on the selected track:

```bash
python3 garageband_cli.py --pretty library-search Guitar
python3 garageband_cli.py --pretty library-select Guitar --name Guitar
```

For MCP clients, call `garageband_library_search` first and select only from returned visible results. Installed GarageBand sound packs vary, so do not assume a fixed patch catalog.

## Apple Loops

Use Loop Browser commands when the user wants to find loop material inside GarageBand:

```bash
python3 garageband_cli.py --pretty loop-search Drums
python3 garageband_cli.py --pretty loop-select Drums --index 1
python3 garageband_cli.py --pretty loop-drag Drums --index 4 --destination-x 390 --destination-y 195 --acknowledge-content-install-risk
```

For MCP clients, call `garageband_loop_search` first. The Loop Browser is exposed as a huge table, so this command returns filtered item counts and visible row counts rather than every loop name. Use `garageband_loop_select` with a visible row index, then verify with a screenshot before dragging or placing the loop. Rows with download icons can trigger Apple's sound/content installer; call `garageband_loop_drag` only after inspecting the screenshot and setting `acknowledge_content_install_risk`.

## Export Audio

Use `garageband_export_song` or the CLI `export-song` when the user wants a real audio file from the current GarageBand project:

```bash
python3 garageband_cli.py --pretty export-song --output "./exports/current-song.wav" --format WAVE
python3 garageband_cli.py --pretty export-song --output "./exports/current-song.mp3" --format MP3 --quality "High Quality"
python3 garageband_cli.py --pretty audio-info "./exports/current-song.wav"
```

Supported formats are `AAC`, `MP3`, `AIFF`, and `WAVE`. The command refuses to overwrite unless `overwrite` or `--overwrite` is set. Export results include nested `audio_info`; prefer WAVE when an agent needs full duration, channels, sample rate, and frame-count verification.

For one-call tab/image-to-audio work, prefer `make-from-tab` with `--export-output` or MCP `garageband_make_from_tab` with `export_output`. That flow creates the MIDI, opens it in GarageBand, then exports through GarageBand's own dialog.

## Click Visible Controls

Prefer stable paths over coordinates:

```bash
python3 garageband_cli.py --pretty ui-snapshot --max-depth 3
python3 garageband_cli.py --pretty ui-search "Smart Controls" --enabled-only --max-depth 3
python3 garageband_cli.py --pretty ui-controls --max-depth 3
python3 garageband_cli.py --pretty wait-ui "Smart Controls" --enabled-only --timeout 5
python3 garageband_cli.py --pretty ui-search-click Stop --role AXButton
python3 garageband_cli.py --pretty ui-search-info "Master Volume" --role AXSlider
python3 garageband_cli.py --pretty ui-search-details "Tempo" --role AXSlider --max-depth 3
python3 garageband_cli.py --pretty ui-search-set "Master Volume" "0.7" --role AXSlider
python3 garageband_cli.py --pretty ui-search-action "Tempo" increment --role AXSlider --max-depth 3
python3 garageband_cli.py --pretty ui-info-path "window[1]/6/5"
python3 garageband_cli.py --pretty ui-click-path "window[1]/6/5"
python3 garageband_cli.py --pretty ui-action-path "window[1]/6/1/3" decrement
```

Search first when you know the label but not the path. Use `ui-controls` when you want a compact list of visible buttons, checkboxes, sliders, fields, popups, and radio buttons.
Use `wait-ui` after an action that opens a panel, dialog, or control surface.
Use `ui-search-click` only for specific labels that should match one control; it refuses ambiguous matches by default.
Use `ui-search-info` and `ui-search-set` for sliders and editable fields when you know the visible label or Accessibility description but not the path.
Use `ui-search-details` before experimenting with unfamiliar controls; it reports actions, attributes, min/max values, geometry, and current value.
Use `ui-search-action` for controls that expose actions instead of direct values, such as incrementing/decrementing sliders or pressing action-only controls.

Use coordinates only when Accessibility names are not useful:

```bash
python3 garageband_cli.py --pretty screenshot --output "./garageband-window.png"
python3 garageband_cli.py --pretty annotated-screenshot --output "./garageband-click-map.png" --map-output "./garageband-click-map.json"
python3 garageband_cli.py --pretty window-rect
python3 garageband_cli.py --pretty window-click 1483 52
```

Coordinates are macOS window points, not Retina screenshot pixels. Prefer `annotated-screenshot` for visual-only work: it draws numbered target boxes and a coordinate grid, then writes a JSON click map. Use a target's `window_center` with `garageband_window_click`, or its `path` with `garageband_click_ui_path`.

## Multi-Step Plans

Use `run-plan` when you want a repeatable sequence instead of individual calls:

```bash
python3 garageband_cli.py --pretty run-plan --file "./examples/safe-smoke-plan.json"
```

For MCP clients, call `garageband_run_plan` with:

```json
{
  "plan": {
    "name": "capture-current-window",
    "cache_ui": true,
    "steps": [
      {"action": "status"},
      {"action": "ui_snapshot", "args": {"max_depth": 2}},
      {"action": "annotated_screenshot", "args": {"output_path": "./garageband-click-map.png"}},
      {"action": "screenshot", "args": {"output_path": "./garageband-proof.png"}}
    ]
  }
}
```

Plans reuse UI snapshots across discovery steps by default, then clear that cache after clicks, menu actions, shortcuts, typing, or other visible UI changes.

Keep plans conservative: inspect before acting, do one meaningful action, then verify.

## Menu Discovery

Many GarageBand features live behind menus and submenus. Search before clicking:

```bash
python3 garageband_cli.py --pretty menu-map --enabled-only --max-depth 5
python3 garageband_cli.py --pretty menu-search "loop" --enabled-only --top-menu View
python3 garageband_cli.py --pretty menu "View > Show Loop Browser"
python3 garageband_cli.py --pretty menu-search-click "Show Keyboard" --top-menu Window
```

For MCP clients, use `garageband_find_menu_items` to get exact paths, then `garageband_click_menu`.

## MCP Starting Tools

Call these first from an MCP client:

- `garageband_capabilities`
- `garageband_self_test`
- `garageband_recipes`
- `garageband_run_plan`
- `garageband_menu_map`
- `garageband_find_menu_items`
- `garageband_click_menu_search`
- `garageband_ui_snapshot`
- `garageband_find_ui_elements`
- `garageband_ui_controls_summary`
- `garageband_wait_ui`
- `garageband_click_ui_search`
- `garageband_ui_search_info`
- `garageband_ui_search_details`
- `garageband_ui_search_set`
- `garageband_ui_search_action`
- `garageband_project_settings`
- `garageband_project_setting_options`
- `garageband_set_project_settings`
- `garageband_list_tracks`
- `garageband_select_track`
- `garageband_set_track`
- `garageband_list_regions`
- `garageband_smart_controls`
- `garageband_set_smart_control`
- `garageband_library_search`
- `garageband_library_select`
- `garageband_loop_search`
- `garageband_loop_select`
- `garageband_loop_drag`
- `garageband_export_song`
- `garageband_screenshot`
- `garageband_annotated_screenshot`

Then use the specific tool for the chosen action.

## Boundaries

This bridge can automate most visible GarageBand workflows that menus, shortcuts, dialogs, and Accessibility expose. It cannot directly rewrite hidden GarageBand project internals or plugin state through a native API because GarageBand does not publish that kind of automation surface.
