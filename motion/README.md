# Apple Motion MCP Bridge

Dieser Bridge verbindet einen MCP-Client mit Apple Motion. Er kann Animationen
als versioniertes JSON beschreiben, echte Motion-Projekte untersuchen, sichere
Template-Kopien erzeugen und Motion über die macOS-Bedienungshilfen steuern.

## Warum ein Template nötig ist

Apple dokumentiert Templates, veröffentlichte Parameter und den Filmexport,
aber keine allgemeine API zum Erzeugen beliebiger Motion-Projekte. Deshalb
erfindet dieser Code kein internes `.motn`-XML. Ein Basistemplate wird einmal
in der installierten Motion-Version gespeichert. Veränderliche Text- oder
Farbwerte können darin explizite Token tragen:

```text
{{MOTION:TITLE}}
{{MOTION:ACCENT_COLOR}}
```

Der Bridge kopiert das Original, ersetzt XML-escaped Werte, verweigert fehlende
oder überzählige Werte und validiert das Ergebnis erneut als XML. Alternativ
können bekannte veröffentlichte Bedienelemente per Accessibility-Pfad gebunden
werden. Diese Pfade werden zuerst mit `ui-snapshot` ermittelt und nie geraten.

## Schnellstart

Überall ausführbar:

```bash
python3 -m motion.cli validate-spec motion/examples/nexpt-kinetic-title.json
python3 -m motion.cli capabilities
```

Auf dem Mac:

1. Motion installieren und mindestens einmal öffnen.
2. Dem Terminal beziehungsweise MCP-Host unter **Systemeinstellungen →
   Datenschutz & Sicherheit → Bedienungshilfen** Zugriff geben.
3. Ein eigenes Motion-Basistemplate mit den gewünschten Ebenen, Rig-Reglern
   oder Platzhaltern speichern.
4. Eine Arbeitskopie erzeugen und öffnen:

```bash
python3 -m motion.cli render-template \
  motion/base/NEXPT-title.motn \
  out/motion/NEXPT-title-working.motn \
  motion/examples/template-values.json

python3 -m motion.cli open out/motion/NEXPT-title-working.motn
python3 -m motion.cli ui-snapshot --max-depth 5
```

`python3 -m motion.cli export-dialog` öffnet mit `⌘E` den Filmexport. Der
Bridge bestätigt ihn absichtlich nicht blind, weil Ziel, Codec und vorhandene
Dateien geprüft werden müssen. Danach kann `screenshot` einen visuellen Beleg
speichern.

## MCP einrichten

`motion/mcp-config.example.json` in die MCP-Konfiguration übernehmen und `cwd`
auf dieses Repository setzen. Der Server spricht MCP über stdin/stdout und
benötigt keine Python-Pakete. Die wichtigsten Tools sind:

- `motion_validate_animation`, `motion_compile_plan`, `motion_run_plan`
- `motion_inspect_project`, `motion_render_template`
- `motion_ui_snapshot`, `motion_find_ui_elements`, `motion_set_ui_value`
- `motion_open`, `motion_save`, `motion_export_dialog`, `motion_screenshot`

Mit `motion_run_plan(..., dry_run=true)` lässt sich jeder Ablauf vor der echten
UI-Steuerung vollständig prüfen.

## Tests

Die plattformunabhängigen Unit- und E2E-Tests prüfen CLI, MCP-stdio,
Dateierzeugung, Plan-Compilation, Dry-Runs sowie Fehler- und Schutzpfade:

```bash
python3 -m unittest discover -s tests -p 'test_motion*.py' -v
```

Ein Live-Test gegen Apple Motion ist aus Sicherheitsgründen opt-in. Er startet
Motion, liest den Accessibility-Baum und erstellt einen temporären Screenshot;
er speichert und exportiert nichts:

```bash
MOTION_LIVE_E2E=1 python3 -m unittest tests.test_motion_live_e2e -v
```

Optional kann mit `MOTION_LIVE_PROJECT=/pfad/probe.motn` ein entbehrliches
Testprojekt geöffnet werden. Vorher müssen Bedienungshilfen- und
Bildschirmaufnahme-Rechte für das Terminal beziehungsweise den MCP-Host gesetzt
sein.

## Animationsformat

Die Spezifikation definiert Projektgröße, Bildrate, Dauer, Ebenen und
Keyframes. Unterstützte Ebenentypen sind `text`, `image`, `video`, `shape` und
`group`; unbekannte Eigenschaften, ungeordnete Keyframes, fehlende Assets und
überlange Ebenen werden abgewiesen. Das Beispiel liegt unter
`motion/examples/nexpt-kinetic-title.json`.

Das JSON ist die gestalterische Quelle der Wahrheit. Das konkrete Motion-
Template bleibt die versionsabhängige Ausführungsschicht. Dadurch können wir
später weitere Templates und Bindings hinzufügen, ohne den MCP-Vertrag oder die
Animationsdaten neu zu bauen.
