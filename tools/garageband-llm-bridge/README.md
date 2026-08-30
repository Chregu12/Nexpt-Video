# GarageBand LLM Bridge

This is a local CLI and minimal MCP server that lets an LLM control the installed GarageBand app on macOS.

It is not a fake GarageBand project editor. It uses:

- GarageBand's tiny native AppleScript surface: `renderPreview`
- macOS Accessibility automation for menus and keyboard shortcuts
- normal macOS file opening for `.band` projects and audio files
- a tab-to-MIDI workflow so an LLM can turn readable guitar tab into a GarageBand-importable song seed
- optional macOS Vision OCR for extracting guitar tab from a local image path or image URL

## What I found

Current GarageBand exposes only one useful AppleScript command in its scripting dictionary: `renderPreview`. Most useful control has to go through menus, keyboard shortcuts, or external audio/MIDI files.

I also checked `cli-anything-garageband` 1.0.0 from PyPI. It is a separate JSON/audio-mixing CLI, not a live GarageBand controller.

## Install

The bridge has no third-party runtime dependencies; it shells out to macOS tools that ship with the OS (`osascript`, `sips`, `screencapture`, `swift`). You can run it straight from this folder with `python3 garageband_cli.py ...`, or install it to get the `garageband-bridge` and `garageband-bridge-mcp` commands plus the MCP server entry point:

```bash
python3 -m pip install -e .
garageband-bridge --pretty capabilities
```

Requires Python 3.10 or newer and macOS with GarageBand installed.

## Quick Start

From this folder:

```bash
python3 garageband_cli.py --pretty status
python3 garageband_cli.py --pretty capabilities
python3 garageband_cli.py --pretty self-test --output-dir "./self-test-latest"
python3 garageband_cli.py --pretty recipes
python3 garageband_cli.py --pretty run-plan --file "./examples/safe-smoke-plan.json"
python3 garageband_cli.py --pretty arrange-tab-to-midi --tab-file "/path/to/tab.txt" --output "/tmp/arranged.mid" --style rock --repeat-count 2
python3 garageband_cli.py --pretty score-to-midi --score "/path/to/band-score.musicxml" --output "/tmp/band-score.mid"
python3 garageband_cli.py --pretty score-spec-schema
python3 garageband_cli.py --pretty score-spec-validate --file "./examples/tiny-band-score-spec.json"
python3 garageband_cli.py --pretty score-spec-to-midi --file "./examples/tiny-band-score-spec.json" --output "/tmp/band-score-spec.mid"
python3 garageband_cli.py --pretty make-from-score --score "/path/to/band-score.musicxml" --output-dir "./score-song" --export-output "./score-song/score-song.wav" --export-format WAVE --export-overwrite
python3 garageband_cli.py --pretty make-from-score-spec --file "./examples/tiny-band-score-spec.json" --output-dir "./score-song-json" --no-open
python3 garageband_cli.py --pretty launch
python3 garageband_cli.py --pretty menus --enabled-only
python3 garageband_cli.py --pretty menu-map --enabled-only
python3 garageband_cli.py --pretty menu-search export --enabled-only --top-menu Share
python3 garageband_cli.py --pretty ui-search "Smart Controls" --enabled-only
python3 garageband_cli.py --pretty ui-search-click Stop --role AXButton
python3 garageband_cli.py --pretty ui-search-info "Master Volume" --role AXSlider
python3 garageband_cli.py --pretty ui-search-details "Tempo" --role AXSlider --max-depth 3
python3 garageband_cli.py --pretty ui-search-action "Tempo" increment --role AXSlider --max-depth 3
python3 garageband_cli.py --pretty project-settings
python3 garageband_cli.py --pretty project-setting-options
python3 garageband_cli.py --pretty set-project-settings --tempo 128 --key-signature "C major" --time-signature "4/4"
python3 garageband_cli.py --pretty list-tracks
python3 garageband_cli.py --pretty set-track --index 1 --mute false --solo false
python3 garageband_cli.py --pretty list-regions
python3 garageband_cli.py --pretty ui-controls --max-depth 3
python3 garageband_cli.py --pretty wait-ui "Loop Browser" --enabled-only --timeout 5
python3 garageband_cli.py --pretty midi-info "./examples/arranged-smoke-plan.mid"
python3 garageband_cli.py --pretty ui-snapshot --max-depth 3
python3 garageband_cli.py --pretty screenshot --output "/tmp/garageband-window.png"
python3 garageband_cli.py --pretty window-rect
python3 garageband_cli.py --pretty transport play_stop
python3 garageband_cli.py --pretty export-song --output "./exports/current-song.wav" --format WAVE
python3 garageband_cli.py --pretty audio-info "./exports/current-song.wav"
python3 garageband_cli.py --pretty menu "View > Show Loop Browser"
python3 garageband_cli.py --pretty open "/path/to/project.band"
python3 garageband_cli.py --pretty render-preview "/path/to/project.band"
```

The first UI action may trigger macOS permission prompts.

## LLM Operating Loop

For autonomous use, start with:

```bash
python3 garageband_cli.py --pretty capabilities
python3 garageband_cli.py --pretty self-test --output-dir "./self-test-latest"
```

Then follow this loop:

1. Inspect visible state with `ui-snapshot` or `screenshot`.
2. Perform one menu, shortcut, path, or coordinate action.
3. Verify with another `ui-snapshot` or `screenshot`.
4. Keep generated proof files in an output folder.

Use `recipes` for tested high-level patterns such as making music from an online tab image, clicking named controls, clicking visual-only controls, transport actions, and opening the export dialog.

`capabilities` also returns an `agent_decision_guide` for MCP clients. It tells an LLM which tool family to prefer for common user intents: high-level tab/image recipes first for song seeds, menu discovery before menu clicks, path/value UI tools before coordinate clicks, and Library/Smart Controls/Loop searches before selection or dragging.

For the broad "given a band score, make music" path, use the unified route:

```bash
python3 garageband_cli.py --pretty make-music \
  --score-json-file "./examples/tiny-band-score-spec.json" \
  --output-dir "./score-song" \
  --name "score-song" \
  --no-open
```

Swap `--score-json-file` for `--score` with a MusicXML file, or for `--tab`, `--tab-file`, `--image`, or `--url` when the source is guitar tab. Add `--export-output "./score-song/score-song.wav" --export-format WAVE --export-overwrite` when GarageBand should render audio.

For repeatable multi-step work, use `run-plan` with JSON:

```bash
python3 garageband_cli.py --pretty run-plan --file "./examples/safe-smoke-plan.json"
```

`run-plan` reuses UI snapshots across `ui_search` and `ui_controls` steps by default when the plan contains no UI-changing action between them. Set `"cache_ui": false` in a plan if every UI discovery step must force a fresh read.

Plan steps look like:

```json
{
  "name": "inspect-and-capture",
  "cache_ui": true,
  "steps": [
    {"action": "status"},
    {"action": "ui_snapshot", "args": {"max_depth": 2}},
    {"action": "screenshot", "args": {"output_path": "/tmp/garageband-proof.png"}}
  ]
}
```

Available plan actions mirror the bridge commands: `status`, `capabilities`, `self_test`, `launch`, `open`, `menus`, `menu_map`, `menu_search`, `menu_search_click`, `menu`, `ui_snapshot`, `ui_search`, `ui_controls`, `wait_ui`, `ui_search_click`, `ui_search_info`, `ui_search_details`, `ui_search_set`, `ui_search_action`, `project_settings`, `project_setting_options`, `set_project_settings`, `list_tracks`, `select_track`, `set_track`, `list_regions`, `smart_controls`, `set_smart_control`, `library_search`, `library_select`, `loop_search`, `loop_select`, `loop_drag`, `ui_click`, `ui_info_path`, `ui_details_path`, `ui_click_path`, `ui_action_path`, `ui_set_value`, `screenshot`, `annotated_screenshot`, `window_rect`, `window_click`, `window_drag`, `type_text`, `shortcut`, `transport`, `export_dialog`, `export_song`, `audio_info`, `midi_info`, `tab_to_midi`, `arrange_tab_to_midi`, `image_to_tab`, `image_to_midi`, `arrange_image_to_midi`, `score_to_midi`, `score_spec_schema`, `score_spec_validate`, `score_spec_to_midi`, `make_music`, `make_from_score`, `make_from_score_spec`, `make_from_tab`, `dismiss_save_prompt`, and `wait`.

For menu-heavy workflows, use recursive menu discovery first:

```bash
python3 garageband_cli.py --pretty menu-map --enabled-only --max-depth 5
python3 garageband_cli.py --pretty menu-search "export" --enabled-only --top-menu Share
python3 garageband_cli.py --pretty menu "Share > Export Song to Disk..."
```

When the search should be unique, `menu-search-click` and `ui-search-click` combine discovery and action:

```bash
python3 garageband_cli.py --pretty ui-search-click Stop --role AXButton
python3 garageband_cli.py --pretty menu-search-click "Show Keyboard" --top-menu Window
```

They fail instead of clicking when more than one match is found unless `--allow-first` is passed.

## Make Music From A Band Score

For the simplest LLM-facing workflow, call `make-music`. It accepts exactly one source: MusicXML, JSON score spec, tab text/file, or tab image/URL. For a real multi-instrument score, use MusicXML or JSON score spec instead of guitar tab so GarageBand imports separate parts as multiple tracks:

```bash
python3 garageband_cli.py --pretty make-music \
  --score "/path/to/band-score.musicxml" \
  --output-dir "./score-song" \
  --name "score-song"
```

For lower-level MIDI-only work, use MusicXML directly:

```bash
python3 garageband_cli.py --pretty score-to-midi \
  --score "/path/to/band-score.musicxml" \
  --output "/path/to/band-score.mid"
```

Compressed `.mxl` and plain `.xml` MusicXML files are also supported, including both `score-partwise` and `score-timewise` documents. The converter reads score tempo changes, time-signature changes, written-to-sounding transposition for instruments such as Bb trumpet or piccolo, 8va/8vb octave-shift directions, grace notes as short MIDI notes, MusicXML harmony/chord symbols as a generated chord accompaniment track, sustain pedal directions as MIDI CC64, tied notes as sustained MIDI notes, single- and multi-measure repeat symbols, simple forward/backward repeats, common first/second endings, rehearsal/words markers, drum `score-instrument` names and `midi-unpitched` values for kick/snare/hat mapping, and MusicXML `midi-instrument` channel/program/volume/pan metadata when available. If the score omits MIDI metadata, it assigns each part to its own MIDI channel, maps specific instrument names such as electric guitar, bassoon, and double bass before broader words such as guitar or bass, and keeps drum/percussion parts on MIDI channel 10. `midi-info` reports imported MusicXML tempo maps under `tempo_changes`, meter maps under `time_signatures`, rehearsal/section text under `markers`, sustain pedal and initial mix data under `control_changes`.

Simple MusicXML repeat barlines and single-/multi-measure repeat symbols are expanded before MIDI is written, so a repeated verse, riff, drum groove, or bass figure plays the requested number of times instead of importing only the printed measures once. Common first/second endings are followed during that expansion. Coda, dal segno, and other navigation markings are not expanded yet; export those scores from notation software as fully unfolded MusicXML when exact playback is required.

For JSON score specs, a part or individual note can include `dynamic` values such as `p`, `mp`, `mf`, `f`, `ff`, or `fff`. MusicXML direction dynamics such as `<p/>` and `<ff/>` are also mapped into MIDI velocity, and `midi-info` reports `velocity_by_channel` so agents can verify strong/soft phrasing.

For complete song forms, JSON score specs can use per-part `sections` instead of a flat `notes` list. Each section has a `name`, optional `repeat`, optional `dynamic`, and its own notes. Section names are written as MIDI markers, so `midi-info` can verify an imported arrangement has markers such as Intro, Verse 1, Verse 2, and Chorus:

```bash
python3 garageband_cli.py --pretty make-music \
  --score-json-file "./examples/section-band-score-spec.json" \
  --output-dir "./section-song" \
  --name "section-song" \
  --no-open
python3 garageband_cli.py --pretty midi-info "./section-song/section-song.mid"
```

For a basic mix, each JSON score part can include `mix` with `volume`, `pan`, `reverb`, and `chorus`. `volume`, `reverb`, and `chorus` accept `0-127`, `0.0-1.0`, or percent text; `pan` accepts `0-127`, `-1.0..1.0`, or `left`/`center`/`right`. These are written as MIDI CC7, CC10, CC91, and CC93, and `midi-info` reports them under `control_changes`.

For tempo maps, add top-level `tempo_changes` with `beat` and `bpm` values, such as `{"beat": 0, "bpm": 96}` followed by `{"beat": 12, "bpm": 132}`. These are written as MIDI tempo meta events, and `midi-info` reports them under `tempo_changes`.

For meter maps, add top-level `time_signature_changes` with `beat` and `time_signature` values, such as `{"beat": 0, "time_signature": "4/4"}` followed by `{"beat": 12, "time_signature": "6/8"}`. These are written as MIDI time signature meta events, and `midi-info` reports them under `time_signatures`.

For key signatures, add top-level `key_signature` such as `"Bb major"` or `"E minor"`. The lower-level object form `{"fifths": -2, "mode": "major"}` is also accepted. MusicXML `<key>` data is preserved too. These are written as MIDI key signature meta events, and `midi-info` reports them under `key_signature` and `key_signatures`.

For articulation, add `articulation` to a note, section, or part. Supported values include `staccato`, `tenuto`, `legato`, `accent`, and `marcato`. Staccato shortens MIDI note length, legato extends it, and accent/marcato boost velocity; `midi-info` reports `note_length_by_channel` and `velocity_by_channel` for verification.

For the full direct-music workflow, use `make-from-score`. It creates the MIDI, opens it in GarageBand, captures a screenshot, and can export audio through GarageBand:

```bash
python3 garageband_cli.py --pretty make-from-score \
  --score "/path/to/band-score.musicxml" \
  --output-dir "./score-song" \
  --name "score-song" \
  --export-output "./score-song/score-song.wav" \
  --export-format WAVE \
  --export-overwrite
```

Use `--bpm` only when you want to override the score tempo. Use `midi-info` after generation to verify track names, channels, and note counts.

When an LLM has interpreted a score into structured parts and notes, use the JSON score spec directly:

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
      "notes": [
        {"pitch": "E4", "duration": 1},
        {"pitches": ["E4", "G4", "B4"], "duration": 2}
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

Use `score-spec-schema` before generating a score object, and `score-spec-validate` before opening GarageBand:

```bash
python3 garageband_cli.py --pretty score-spec-schema
python3 garageband_cli.py --pretty score-spec-validate --file "./examples/tiny-band-score-spec.json"
```

Each note's `start` and `duration` are in quarter-note beats. If `start` is omitted, notes play sequentially inside that part. Pitches use names such as `C4`, `F#3`, or `Bb4`; chords use `pitches`. Drum parts can use names such as `kick`, `snare`, `closed_hat`, `open_hat`, `crash`, and `ride`.

```bash
python3 garageband_cli.py --pretty score-spec-to-midi \
  --file "./examples/tiny-band-score-spec.json" \
  --output "./score-song/tiny-band-score-spec.mid"
```

To go all the way to an audio file through GarageBand:

```bash
python3 garageband_cli.py --pretty make-from-score-spec \
  --file "./examples/tiny-band-score-spec.json" \
  --output-dir "./examples/make-score-spec-live" \
  --name "tiny-band-json-live" \
  --discard-unsaved \
  --export-output "./examples/make-score-spec-live/tiny-band-json-live.wav" \
  --export-format WAVE \
  --export-overwrite
```

The checked example artifacts are:

- `examples/make-score-spec-live/tiny-band-json-live.mid`
- `examples/make-score-spec-live/tiny-band-json-live-garageband.png`
- `examples/make-score-spec-live/tiny-band-json-live.wav`

Verify exported audio with `audio-info`:

```bash
python3 garageband_cli.py --pretty audio-info \
  "./examples/make-score-spec-live/tiny-band-json-live.wav"
```

## Make Music From A Tab

If an LLM already has ordinary six-line ASCII tab, run:

```bash
python3 garageband_cli.py --pretty tab-to-midi \
  --tab-file "/path/to/tab.txt" \
  --output "/path/to/riff.mid" \
  --bpm 110 \
  --open
```

Inline tab also works:

```bash
python3 garageband_cli.py --pretty tab-to-midi \
  --tab 'e|--0--2--3--|
B|--1--3--0--|
G|--0--2--0--|
D|--2--0--0--|
A|--3-----2--|
E|--------3--|' \
  --output "/tmp/garageband-riff.mid" \
  --bpm 96
```

The bridge can also read a tab image through macOS Vision OCR and create MIDI directly:

```bash
python3 garageband_cli.py --pretty image-to-midi \
  --image "/path/to/tab-image.png" \
  --output "/path/to/riff-from-image.mid" \
  --bpm 108 \
  --open
```

For a more song-like sketch, generate a multi-track arrangement. This creates separate guitar, bass, and drum tracks in one GarageBand-importable MIDI file:

```bash
python3 garageband_cli.py --pretty arrange-image-to-midi \
  --image "/path/to/tab-image.png" \
  --output "/path/to/arranged-riff.mid" \
  --bpm 108 \
  --style rock \
  --repeat-count 2 \
  --open
```

For an online image URL:

```bash
python3 garageband_cli.py --pretty image-to-midi \
  --url "https://example.com/tab-image.png" \
  --output "/path/to/riff-from-url.mid" \
  --bpm 108
```

To inspect OCR before making MIDI:

```bash
python3 garageband_cli.py --pretty image-to-tab --image "/path/to/tab-image.png"
```

Image OCR works best with clear, high-contrast, monospaced tab. The tool repairs common OCR issues such as missing vertical bars and split tab lines, but messy photos may still need manual correction.

Tab text and OCR output are checked for common tempo, capo, and tuning notes such as `BPM 140`, `Tempo: 92`, `Capo 2`, `capo on 3rd fret`, `Drop D tuning`, or `Tuning: DADGBE`. The parser also understands tab line labels as tuning, so custom-labeled rows such as `D|`, `A|`, `F#|`, `D|`, `A|`, `D|` are mapped by six-string order. Internal measure bars do not consume timing columns, so `--0--|--2--` keeps the same spacing as `--0----2--`; hammer-on, pull-off, slide, bend, release, and vibrato markers such as `5h7`, `7p5`, `5/7`, `7\5`, `7b9r7`, and `7~` also do not add extra rest columns. Muted `x`/`X` strums are emitted as short low-velocity guitar hits so rhythmic scratches are not lost, while generated bass skips muted-only onsets. Detected values are returned as `bpm`, `capo`, `tuning`, and `string_pitches`, then applied to the generated MIDI. Pass `--bpm`, `--capo 0`, or `--tuning "standard"` / `--tuning "D A D G B E"` to override OCR or page-title ambiguity.

The repository includes a checked live proof for the original online-picture workflow. A clean tab PNG is served over local HTTP as a URL, then `make-from-tab --url` downloads it, extracts tab with Vision OCR, opens the arranged MIDI in GarageBand, exports WAV, and verifies the audio:

```bash
cd examples/online-tab-proof
python3 -m http.server 8765 --bind 127.0.0.1
```

In another terminal:

```bash
python3 garageband_cli.py --pretty make-from-tab \
  --url "http://127.0.0.1:8765/clear-online-tab.png" \
  --output-dir "./examples/online-tab-proof/live-url-export" \
  --name "online-tab-url-live" \
  --bpm 118 \
  --arrange \
  --style rock \
  --repeat-count 2 \
  --discard-unsaved \
  --export-output "./examples/online-tab-proof/live-url-export/online-tab-url-live.wav" \
  --export-format WAVE \
  --export-overwrite
python3 garageband_cli.py --pretty audio-info \
  "./examples/online-tab-proof/live-url-export/online-tab-url-live.wav"
```

Proof artifacts:

- `examples/online-tab-proof/clear-online-tab.png`
- `examples/online-tab-proof/live-url-export/online-tab-url-live.mid`
- `examples/online-tab-proof/live-url-export/online-tab-url-live-garageband.png`
- `examples/online-tab-proof/live-url-export/online-tab-url-live.wav`
- `examples/online-tab-proof/live-url-export/online-tab-url-live-verified-return.wav`

For the full autonomous workflow, use `make-from-tab`. It accepts tab text, a tab text file, a local tab image, or an image URL; creates MIDI; opens it in GarageBand; handles an optional generated-project save prompt; opens requested panels; snapshots the UI; and captures a screenshot:

```bash
python3 garageband_cli.py --pretty make-from-tab \
  --image "/path/to/tab-image.png" \
  --output-dir "/path/to/output-folder" \
  --name "riff-from-picture" \
  --bpm 118 \
  --arrange \
  --style rock \
  --repeat-count 2 \
  --show-library \
  --show-smart-controls \
  --discard-unsaved
```

Add `--export-output` when the user wants the whole recipe to finish with a real audio file:

```bash
python3 garageband_cli.py --pretty make-from-tab \
  --image "/path/to/tab-image.png" \
  --output-dir "./song-from-image" \
  --name "song-from-image" \
  --bpm 118 \
  --arrange \
  --style rock \
  --repeat-count 2 \
  --discard-unsaved \
  --export-output "./song-from-image/song-from-image.wav" \
  --export-format WAVE \
  --export-overwrite
```

Arranged MIDI styles: `auto`, `rock`, `pop`, `blues`, `metal`, and `folk`. `--repeat-count` repeats the parsed tab phrase before writing the MIDI, which is useful when a source image only contains a short riff.

Use `--bpm`, `--capo`, and `--tuning` on `tab-to-midi`, `arrange-tab-to-midi`, `image-to-midi`, `arrange-image-to-midi`, `make-from-tab`, or `make-music` when the source says a tempo, capo, or alternate tuning is present and the automatic detection needs an explicit value.

`--discard-unsaved` is intentionally explicit. It clicks GarageBand's `Don't Save` button only if GarageBand shows a save prompt while opening the generated MIDI.

## Project Musical Settings

GarageBand's LCD controls expose the current tempo, key signature, and time signature through Accessibility:

```bash
python3 garageband_cli.py --pretty project-settings
python3 garageband_cli.py --pretty project-setting-options
python3 garageband_cli.py --pretty set-project-settings --tempo 128
python3 garageband_cli.py --pretty set-project-settings --key-signature "C major" --time-signature "4/4"
```

For MCP clients, use `garageband_project_settings` before and after `garageband_set_project_settings` to verify the values GarageBand accepted. Use `garageband_project_setting_options` to list known key and time-signature options. Key signature and time signature are selected through GarageBand's native popups by typing the target label and pressing Return, then reading the accepted value back; sharp keys use a tested popup-navigation fallback because GarageBand's typeahead treats `#` inconsistently. All setting calls report `exact`/`all_exact`; treat false as "GarageBand did not accept that UI change." Tempo uses GarageBand's increment/decrement actions and reports the actual value plus whether it matched exactly, because GarageBand may step tempo coarsely in some UI states.

## Operate Tracks And Regions

Use `list-tracks` after opening or importing MIDI to inspect visible track headers and their controls:

```bash
python3 garageband_cli.py --pretty list-tracks
python3 garageband_cli.py --pretty select-track --index 2
python3 garageband_cli.py --pretty select-track --index 2 --fast
python3 garageband_cli.py --pretty select-track --name "Acoustic Guitar"
python3 garageband_cli.py --pretty set-track --index 1 --mute false --solo false
python3 garageband_cli.py --pretty set-track --name "Acoustic Guitar" --volume 0.75
python3 garageband_cli.py --pretty list-regions
```

`select-track` clicks a visible track header so later Library and Smart Controls actions target that track. Use `--fast` when you already know the visible row index and want geometry-based selection without a slower name scan. `set-track` works on visible track headers. It can set `--mute`, `--solo`, `--volume`, `--pan`, and `--rename`, then returns a fresh readback. If the target track is not visible, scroll or zoom the Tracks area first with the general UI/coordinate tools.

## Shape Sound With Smart Controls

Use `smart-controls` to show GarageBand's Smart Controls panel and list the visible Track/Master/Controls/EQ tabs plus any exposed knobs, sliders, buttons, or fields:

```bash
python3 garageband_cli.py --pretty smart-controls
python3 garageband_cli.py --pretty set-smart-control --query EQ --action press
python3 garageband_cli.py --pretty set-smart-control --path "window[1]/8/1/3/2" --action press
```

Some selected tracks or patches show an empty Smart Controls state. In that case `control_count` is `0`, but the returned tabs still let an LLM switch between Track, Master, Controls, and EQ views. Inspect `smart-controls` first, then use `set-smart-control` with a returned `path` whenever possible.

## Choose Library Sounds

Use `library-search` to show GarageBand's Library, fill the Library search box, and list the visible results for the selected track:

```bash
python3 garageband_cli.py --pretty library-search Guitar
python3 garageband_cli.py --pretty library-select Guitar --name Guitar
```

GarageBand's installed sound packs vary by Mac. Always inspect `library-search` results first, then select by `--name`, `--index`, or `--allow-first` when the visible result is acceptable.

## Search Apple Loops

Use `loop-search` to show GarageBand's Apple Loops browser, fill its search field, and read the filtered item count and visible-row count:

```bash
python3 garageband_cli.py --pretty loop-search Drums
python3 garageband_cli.py --pretty loop-select Drums --index 1
python3 garageband_cli.py --pretty loop-drag Drums --index 4 --destination-x 390 --destination-y 195 --acknowledge-content-install-risk
```

GarageBand exposes the Loop Browser as a very large Accessibility table, so the bridge does not enumerate every loop name. Filter first, inspect `item_count` and `visible_row_count`, then select a visible row by index. Before `loop-drag`, capture a screenshot and avoid rows with download icons unless the user is ready for Apple's sound/content installer prompt.

## Export Audio

Use `export-song` to render the current GarageBand project through GarageBand's own export dialog:

```bash
python3 garageband_cli.py --pretty export-song --output "./exports/current-song.wav" --format WAVE
python3 garageband_cli.py --pretty export-song --output "./exports/current-song.mp3" --format MP3 --quality "High Quality"
python3 garageband_cli.py --pretty audio-info "./exports/current-song.wav"
```

Supported formats are `AAC`, `MP3`, `AIFF`, and `WAVE`. The command refuses to replace an existing file unless `--overwrite` is provided, waits for GarageBand to create a non-empty file, and returns nested `audio_info` metadata for the exported file. Use `audio-info` independently when you need to verify an existing export's bytes, format, duration, sample rate, channel count, and frame count. The high-level `make-from-tab` recipe can also export after opening the generated MIDI by passing `--export-output`, `--export-format`, and optionally `--export-overwrite`; its `audio_export` result includes the same nested verification metadata.

## Operate Visible GarageBand Controls

Use `ui-snapshot` to inspect visible controls and get stable paths for the current UI state:

```bash
python3 garageband_cli.py --pretty ui-snapshot --max-depth 2
python3 garageband_cli.py --pretty ui-search "Loop Browser" --enabled-only --max-depth 3
python3 garageband_cli.py --pretty ui-search-click Stop --role AXButton
python3 garageband_cli.py --pretty ui-search-info "Master Volume" --role AXSlider
python3 garageband_cli.py --pretty ui-search-details "Tempo" --role AXSlider --max-depth 3
python3 garageband_cli.py --pretty ui-search-set "Master Volume" "0.7" --role AXSlider
python3 garageband_cli.py --pretty ui-search-action "Tempo" increment --role AXSlider --max-depth 3
python3 garageband_cli.py --pretty ui-controls --max-depth 3
python3 garageband_cli.py --pretty wait-ui "Loop Browser" --enabled-only --timeout 5
```

Use `ui-search-click`, `ui-search-info`, `ui-search-details`, `ui-search-set`, and `ui-search-action` when a label or description should identify exactly one visible control. They fail instead of acting when a search is ambiguous unless `--allow-first` is passed. `ui-search-details` reports available Accessibility actions, attributes, min/max values, geometry, and current value. `ui-search-action` supports `increment`, `decrement`, and `press`, which is useful for sliders and controls that do not accept direct value setting.

When you already have a specific path from `ui-snapshot` or `ui-search`, act on that path:

```bash
python3 garageband_cli.py --pretty ui-info-path "window[1]/6/5"
python3 garageband_cli.py --pretty ui-details-path "window[1]/6/1/3"
python3 garageband_cli.py --pretty ui-click-path "window[1]/6/5"
python3 garageband_cli.py --pretty ui-action-path "window[1]/6/1/3" decrement
python3 garageband_cli.py --pretty ui-set-value "window[1]/6/17" "0.7"
```

Name-based clicks are still available for simpler cases:

```bash
python3 garageband_cli.py --pretty ui-click Stop --role AXButton --exact
```

For controls that do not expose useful Accessibility names, use the screenshot plus window-relative coordinate tools:

```bash
python3 garageband_cli.py --pretty screenshot --output "/tmp/garageband-window.png"
python3 garageband_cli.py --pretty annotated-screenshot --output "/tmp/garageband-click-map.png" --map-output "/tmp/garageband-click-map.json"
python3 garageband_cli.py --pretty window-rect
python3 garageband_cli.py --pretty window-click 482 52
python3 garageband_cli.py --pretty window-drag 1229 55 1280 55 --delay 0.2
python3 garageband_cli.py --pretty type-text "guitar"
```

Coordinates are macOS window points, not Retina screenshot pixels. `annotated-screenshot` draws a coordinate grid and numbered boxes over the GarageBand window, then writes a JSON click map whose `window_center` values can be passed to `window-click` and whose `path` values can be passed to `ui-click-path`. `ui-snapshot` includes each visible element's `position` and `size` in screen points, which is also useful for calibration.

## MCP Config

Ready-to-use example: `mcp-config.example.json`.

Use this with MCP clients that support stdio servers:

```json
{
  "mcpServers": {
    "garageband": {
      "command": "python3",
      "args": [
        "/Users/xuanrutao/Documents/Codex/2026-06-13/find-or-perfect-or-build-an/outputs/garageband-llm-bridge/garageband_mcp.py"
      ]
    }
  }
}
```

## MCP Tools

- `garageband_status`
- `garageband_capabilities`
- `garageband_self_test`
- `garageband_recipes`
- `garageband_run_plan`
- `garageband_launch`
- `garageband_open`
- `garageband_render_preview`
- `garageband_list_menus`
- `garageband_menu_map`
- `garageband_find_menu_items`
- `garageband_click_menu_search`
- `garageband_click_menu`
- `garageband_ui_snapshot`
- `garageband_find_ui_elements`
- `garageband_ui_controls_summary`
- `garageband_wait_ui`
- `garageband_click_ui_search`
- `garageband_ui_search_info`
- `garageband_ui_search_details`
- `garageband_ui_search_set`
- `garageband_ui_search_action`
- `garageband_click_ui`
- `garageband_ui_info_path`
- `garageband_ui_details_path`
- `garageband_click_ui_path`
- `garageband_set_ui_value`
- `garageband_ui_action_path`
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
- `garageband_screenshot`
- `garageband_annotated_screenshot`
- `garageband_window_rect`
- `garageband_window_click`
- `garageband_window_drag`
- `garageband_type_text`
- `garageband_shortcut`
- `garageband_transport`
- `garageband_export_dialog`
- `garageband_export_song`
- `garageband_audio_info`
- `garageband_midi_info`
- `garageband_tab_to_midi`
- `garageband_arrange_tab_to_midi`
- `garageband_image_to_tab`
- `garageband_image_to_midi`
- `garageband_arrange_image_to_midi`
- `garageband_score_to_midi`
- `garageband_score_spec_schema`
- `garageband_validate_score_spec`
- `garageband_score_spec_to_midi`
- `garageband_make_music`
- `garageband_make_from_score`
- `garageband_make_from_score_spec`
- `garageband_make_from_tab`
- `garageband_dismiss_save_prompt`
- `garageband_permissions`

## Permission Setup

Open:

`System Settings > Privacy & Security`

Grant the app running this bridge:

- Automation permission to control GarageBand
- Accessibility permission to control System Events

For Codex or Terminal-based use, that usually means granting the terminal app or Codex desktop app Accessibility and Automation access.

## Development And Tests

The deterministic core (guitar-tab parsing, MIDI generation, MIDI inspection, OCR-text repair, export-format normalization, and the plan runner) is covered by a fast unit-test suite that does not require GarageBand, Swift, or network access. The MCP tool surface is also guarded against drift between the advertised tools, the dispatch table, and this README.

```bash
python3 -m pip install -e ".[test]"
pytest
```

The suite lives in `tests/`. The on-device `self-test` command remains the integration check for the GarageBand-dependent paths (Accessibility, screenshots, export dialog):

```bash
python3 garageband_cli.py --pretty self-test --output-dir "./self-test-latest"
```

## Honest Limits

GarageBand does not provide a broad public automation API. This bridge can reliably launch/open projects, inspect menus, click menus, screenshot the GarageBand window, inspect visible UI controls, click visible controls by name, path, or window coordinate, drag at window coordinates, type text, set supported UI values by path, list and adjust visible track headers, list visible regions, search/select visible Library results, filter/select visible Apple Loop rows, send shortcuts, export the current song to audio through GarageBand's export dialog, call `renderPreview`, OCR tab images/URLs, generate MIDI from guitar tab for GarageBand import, and run a higher-level tab-to-GarageBand recipe with screenshots, panel setup, and optional audio export. Creating tracks, deeper region editing, or changing plugin knobs may be possible through additional menu/dialog automation, but those flows are UI-state-dependent and should be added as tested recipes rather than invented as direct API calls.

For deeper DAW automation, Logic Pro is a better target because existing MCP work can combine keyboard automation with CoreMIDI virtual ports and Scripter templates.
