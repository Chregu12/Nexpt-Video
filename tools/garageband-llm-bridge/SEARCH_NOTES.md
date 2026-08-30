# Search Notes

Checked on 2026-06-13.

## Existing options

- `cli-anything-garageband` 1.0.0 on PyPI exists, but inspection showed it stores its own JSON session and renders/mixes WAV files. It does not drive the installed GarageBand app.
- `PsychQuant/che-logic-pro-mcp` is a real Logic Pro MCP with app control, shortcuts, MIDI tools, and Scripter helpers. It is useful inspiration, but it targets Logic Pro, not GarageBand.
- `steipete/macos-automator-mcp` is a generic macOS AppleScript/JXA MCP. It can already run scripts that control GarageBand through System Events, but it is not GarageBand-specific.

## Local verification

- `/Applications/GarageBand.app` is installed.
- `sdef /Applications/GarageBand.app` shows a tiny scripting dictionary with only `renderPreview`.
- GarageBand menus are visible to System Events, so a specific bridge can enumerate and click menu items when Accessibility permission is available.
