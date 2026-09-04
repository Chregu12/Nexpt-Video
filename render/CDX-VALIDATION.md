# CDX-Laufzeitpruefung – 2026-09-04

Die Integration fuehrt echte Checkpoint-Inferenz aus. Die technische Abnahme
der Trennung ist fuer die beiden getesteten Referenzen **nicht bestanden**.
Diese Aussagen sind getrennt; es wird keine Studio-Stem- oder 1:1-Qualitaet
behauptet.

## Verwendete Umgebung

- Linux x86_64, Python 3.12.13, CPU; zwei OMP-/MKL-Threads.
- PyTorch / Torchaudio `2.11.0+cpu`, Demucs `4.0.1`, librosa `0.11.0`.
- Vollstaendiger Versionssnapshot: [requirements-cdx-cpu.txt](requirements-cdx-cpu.txt).
- Upstream: `aaa75640d8fd68418948fe4cd2c2d263d042cbb9`, unveraenderter Checkout.
- Standardgewicht: `97d170e1-dbb4db15.th`, 53 916 935 Bytes.
- Lokaler SHA-256: `dbb4db154df7e45a5cb72d1659c48937e757f6d6b0eef8ca4199e6e38f8d8f37`.
- Eingeschraenkter PyTorch-Lader; kein `weights_only=False`, keine dynamische
  Freigabe unbekannter Checkpoint-Klassen und kein Audio-Upload.

Die Code-Lizenz des Upstreams ist MIT. Eine eigenstaendige Lizenzfreigabe der
Gewichte wurde nicht nachgewiesen. Gewichte und Referenzaudio werden hier
nicht weiterverteilt. Die Hash-Angabe dokumentiert die heruntergeladene Datei,
nicht eine unabhaengige Herausgeberauthentifizierung.

## Echte Referenzlaeufe

Jeweils die ersten fuenf Sekunden, Standard-Checkpoint, unveraenderter
Grenzwert `maximum_residual_ratio=0.1`:

| Referenz | Echte Inferenz / drei WAV-Stems | Rest/Mix-RMS | Striktes Gate |
|---|---|---:|---|
| Hochgeladener Videoausschnitt | ausgefuehrt | 0.346274 | fehlgeschlagen |
| Hochgeladene Instrumentalmusik | ausgefuehrt | 0.194311 | fehlgeschlagen |

Der explizit aktivierte Live-E2E-Test mit dem Video endet deshalb mit einem
Testfehler, nicht mit einem Skip oder einem Erfolg. Die Smoke-Befehle geben
Exitcode 1 zurueck und veroeffentlichen kein Erfolgspaket. Ein separater
nicht-strikter Diagnoselauf bestaetigt lesbare, endliche, zeitlich ausgerichtete
Stems; dessen Status bleibt `review_required`.

Die Differenz ist `RMS(mix - music - dialogue - sfx) / RMS(mix)`, kein Mass
fuer Sprachverstaendlichkeit, musikalische Treue oder Uebersprechen. Der
Upstream nutzt zufaellige Shifts; Wiederholungen koennen leicht abweichen.
Der Grenzwert wurde nicht angehoben und der Rest nicht auf Stems verteilt.

## Grenzen der Abnahme

Die automatisierte Standardsuite testet unter anderem Runtime-Locks, sichere
Loader-Konfiguration, Timeouts, CLI, echte ffmpeg-Dekodierung, Transaktionen
und manipulierte Ergebnisprotokolle. Ihre Modell-Doubles belegen keine
akustische Leistung. Standardsuite: 218 Tests, davon 216 bestanden und zwei
opt-in Tests uebersprungen. Der Live-Modelltest wurde zusaetzlich explizit
aktiviert; sein oben beschriebener Fehler bleibt davon getrennt sichtbar.

Nicht getestet: Drei-Checkpoint-Ensemble, CUDA, macOS/Apple Silicon und die
GarageBand-Oberflaeche. Naechster fachlicher Schritt ist ein gelabelter
A/B-Benchmark fuer Modellqualitaet; eine Lockerung des Gates waere kein
Nachweis verbesserter Trennung.
