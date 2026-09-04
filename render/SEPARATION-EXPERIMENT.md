# Wiederholbarer CDX-Vergleich: Standard gegen High

`run-ab` fuehrt beide CDX-Profile gegen **denselben bekannten Referenz-Corpus**
aus. Mehrere Wiederholungen zeigen beobachtete Schwankungen durch die
zufaelligen CDX-Shifts. Der Befehl optimiert keine Parameter, waehlt keinen
besten Lauf aus und erklaert kein Profil automatisch zum Sieger.

## Voraussetzungen

Vor dem ersten Lauf muessen alle `preflight`-Bedingungen erfuellt sein:

- echter als `isolated-recordings` deklarierter Stereo-Corpus mit den drei
  dokumentierten Kontrollfaellen;
- sichere CDX-Konfiguration mit Standard- und allen drei High-Gewichten;
- funktionsfaehiger, eingeschraenkter PyTorch-Lader;
- mit `--verify-runtime` registrierter und unveraenderter Runtime-Fingerprint;
- CPU oder tatsaechlich verfuegbares CUDA.

Referenz-/Checkpoint-Downloads oder Paketinstallationen finden nicht statt.
Eine bestandene Vorpruefung authentifiziert weder die Referenzlabels noch die
Checkpoint-Herkunft. Setup: [DECOMPOSITION.md](DECOMPOSITION.md). Corpus-Import:
[SEPARATION-BENCHMARK.md](SEPARATION-BENCHMARK.md).

## Start und kontrollierte Etappen

```bash
python3 render/separation_benchmark.py run-ab \
  out/separation-benchmark/reference-v1/corpus.json \
  --cdx-config /pfad/cdx-config.json \
  --repeats 3 --device cpu --timeout 600 \
  --output-dir out/separation-benchmark/cdx-standard-vs-high-01
```

Standardmaessig entstehen sechs vollstaendige Profil-Laeufe. Jeder verarbeitet
alle Cases. Das Zeitlimit gilt **je Case/Modellprozess**, nicht fuer den ganzen
Versuch. High verarbeitet sein Drei-Checkpoint-Ensemble innerhalb dieses
Prozesses und kann deutlich laenger dauern. `--repeats` erlaubt 1–5 Paare.

Zum Begrenzen einer Sitzung nur einen neuen Profil-Lauf ausfuehren:

```bash
python3 render/separation_benchmark.py run-ab \
  out/separation-benchmark/reference-v1/corpus.json \
  --cdx-config /pfad/cdx-config.json \
  --repeats 3 --max-new-runs 1 \
  --output-dir out/separation-benchmark/cdx-standard-vs-high-01

# Spaeter mit exakt denselben Parametern fortsetzen:
python3 render/separation_benchmark.py run-ab \
  out/separation-benchmark/reference-v1/corpus.json \
  --cdx-config /pfad/cdx-config.json \
  --repeats 3 --resume \
  --output-dir out/separation-benchmark/cdx-standard-vs-high-01
```

`--max-new-runs` begrenzt nur den aktuellen Aufruf. Ein unvollstaendiger
Versuch liefert Exitcode 2. Fertige Profil-Pakete bleiben unveraendert. Der
gerade laufende Profil-Lauf ist transaktional: Ein Abbruch veroeffentlicht ihn
nicht teilweise; beim Fortsetzen startet nur dieser Profil-Lauf neu.

Fehlgeschlagene Cases werden als Messergebnis gespeichert und **nicht**
automatisch wiederholt. Das verhindert stilles Best-of-Cherry-Picking. Fuer
einen bewussten neuen Versuch – beispielsweise nach einer Runtime-Aenderung –
einen neuen Ausgabeordner verwenden. Es gibt kein `--overwrite`.

## Was beim Fortsetzen geprueft wird

Der unveraenderliche Plan bindet:

- Corpus-ID, Cases und deklarierte Referenzart;
- CDX-Konfigurationshash und Runtime-Fingerprints;
- Geraet, Wiederholungszahl, Zeitlimit und Metrik-Gates;
- Metrik-/Auswertungsregeln und Hashes aller beteiligten Integrationsdateien.

Vor neuer Rechenarbeit werden alle fertigen Berichte, Laufbelege und alle darin
akzeptierten WAV-Hashes geprueft; unbekannte Artefakte im Stem-Paket blockieren.
Jeder Laufbeleg enthaelt Versuch, Wiederholung, Profil und Berichts-
hash. Das versehentliche Kopieren eines Standard-Laufs in eine andere
Wiederholung wird abgewiesen. Lokale Checksums sind kein signierter
Fremdnachweis und schuetzen nicht gegen einen Angreifer, der alle Artefakte
bewusst neu faelscht.

Eine nicht blockierende Prozesssperre verhindert parallele Schreiber auf
Linux/macOS. Sie wird vom Kernel auch nach einem Prozessabbruch freigegeben.
Unvollstaendige temporaere Ordner werden weder als Resultat verwendet noch
automatisch geloescht.

## Offline auswerten

```bash
python3 render/separation_benchmark.py summarize-ab \
  out/separation-benchmark/cdx-standard-vs-high-01
```

Dies prueft die gespeicherten Paket-Hashes und braucht weder Modellruntime noch
Originalquellen. Es beweist deshalb nicht, dass diese spaeter noch vorhanden
oder unveraendert sind. Die aktiven Voraussetzungen werden nur bei `run-ab`
erneut geprueft.

Pro Case/Rolle zeigt `high_minus_standard` Anzahl, Median, Minimum und Maximum
der gepaarten Differenzen:

| Wert | Interpretation |
|---|---|
| `snr_db_delta`, `si_sdr_db_delta` | Positiv spricht numerisch fuer High |
| `silent_window_rms_delta` | Negativ bedeutet weniger unerwuenschte Energie in Referenz-Stille |
| `*_gate_passes` | Anzahl bestandener Rollen-Gates je Profil |
| `missing_or_failed_trials` | Unvollstaendige Paare; sie werden nicht aus dem Nenner entfernt |

Wiederholungen desselben Falls sind keine unabhaengigen Aufnahmen. Daher gibt
es keine Konfidenzintervalle, Signifikanzbehauptung oder automatische
Profilfreigabe. `overall_winner` und `perceptual_quality_verified` bleiben
`null` beziehungsweise `false`; Hoerfreigabe und GarageBand-Abnahme bleiben
separate Schritte. `--strict` liefert Exitcode 2, wenn zwar alle Laeufe beendet
sind, aber mindestens ein numerisches Gate verfehlt wurde.

## Testgrenze

Unit-Tests verwenden explizite Preflight-/Modell-Doubles. Die E2E-Tests fuehren
Parser, Prozessgrenzen, FFmpeg, Transaktionen, Unterbrechung/Fortsetzung,
Fehlerzaehler und Offline-Auswertung aus. Sie sind kein echter neuronaler
Modelllauf und kein Nachweis verbesserter Trenn- oder Klangqualitaet.

Standardsuite nach diesem Schritt: **332 Tests, 329 bestanden und drei
optionale Live-Tests uebersprungen**. Neu sind 23 Unit- und sechs E2E-Tests.
Die aktuelle Umgebung besitzt weiterhin keine CDX-Modellruntime; deshalb wurde
in diesem Schritt kein neuer echter Standard-/High-Modellvergleich ausgefuehrt.
