# Bekannte Einzelspuren statt nur Summenpruefung

Dieser Benchmark misst die Zuordnung zu `music`, `dialogue` und `sfx` gegen
bekannte Originalspuren. Zwei getrennte Aussagen werden ausgewiesen:

- `mix_consistency`: ergeben die Schaetzungen zusammen den Mix?
- `numerical_gate_passed`: stimmen auch die einzelnen, benannten Spuren mit
  ihren Referenzen ueberein und erfuellen die deklarierten Grenzwerte?

Vertauschte Musik-/Dialogspuren oder ein auf drei Dateien verteilter Mix
koennen die erste Pruefung bestehen und die zweite verfehlen. Es wird kein
Summenrest umverteilt und keine Rollenvertauschung automatisch korrigiert.

## 1. Messverfahren selbst testen – ohne Modelle

```bash
python3 render/separation_benchmark.py self-test \
  --output-dir out/separation-benchmark/controls-01
```

Der Befehl erzeugt drei deterministische Zwei-Sekunden-Faelle: ueberlagerte
Signale, einen Fall ohne Dialog und reine Musik. Sine-/Rauschsignale sind
ausschliesslich Messkontrollen. Insbesondere ist das Signal im Dialog-Slot
**keine echte Sprache**. Es handelt sich nicht um einen Klangvorschlag fuer
das Video und nicht um einen Modellqualitaetsnachweis.

Fuenf Kontrollen pruefen das Messverfahren:

| Kontrolle | Summen-Gate | Einzelspur-Gates |
|---|---|---|
| Unveraenderte bekannte Einzelspuren (`oracle`) | bestanden | bestanden |
| Musik und Dialog vertauscht | bestanden | fehlgeschlagen |
| Jede Ausgabe ist ein Drittel des Mixes | bestanden | fehlgeschlagen |
| Musikanteil in stiller Dialogspur, aus Musik abgezogen | bestanden | fehlgeschlagen |
| Musikspur stummgeschaltet | fehlgeschlagen | fehlgeschlagen |

Diese Erwartungen wurden mit dem Self-Test geprueft. `self_test_passed: true`
bezieht sich nur auf korrekte Messung; `model_inference_executed` und
`perceptual_quality_verified` bleiben `false`.

## 2. Einen echten Referenz-Corpus bauen

Die vorhandenen MP3-/Videomischungen enthalten keine separat bekannten
Originalspuren. Daraus geschaetzte Stems duerfen nicht als Ground Truth fuer
denselben Separator dienen. Benutzung des Beispiels:

1. [benchmark-sources.example.json](benchmark-sources.example.json) als eigene
   Spezifikation ablegen und Pfade, Herkunft und Nutzungsbedingungen ersetzen.
2. Echte isolierte Musik-, Sprach- und Effektaufnahmen bereitstellen. Innerhalb
   jedes Falls muessen Laenge, Samplerate und Kanalzahl exakt gleich sein.
3. Referenzen als `isolated-recordings` deklarieren. `null` bedeutet bewusst
   fehlende Quelle und erzeugt eine gleich lange stille Referenzspur.
4. Die Angaben werden dokumentiert, nicht unabhaengig authentifiziert.

```bash
python3 render/separation_benchmark.py build /pfad/benchmark-sources.json \
  --output-dir out/separation-benchmark/reference-v1
```

Unterstuetzt: 1–20 Faelle, je 1–30 Sekunden WAV, 8–96 kHz, Mono oder Stereo,
maximal 64 MiB pro Eingabedatei. CDX-Laeufe benoetigen einen Stereo-Corpus.
Der Builder normalisiert, kuerzt oder resampelt die Originale nicht.
Ein expliziter `mix_gain` wird auf alle Spuren eines Falls gleich angewendet;
die neuen Float32-Referenzen werden danach summiert. Bei Pegeln ueber 0 dBFS
wird der Build abgebrochen. Originaldateien bleiben unveraendert.

`corpus.json` enthaelt relative Paketpfade, Metadaten, Herkunft, SHA-256-Werte
der Originale und Referenzen sowie eine reproduzierbare Corpus-ID. Ein
geaenderter oder ausserhalb des Pakets verlinkter Referenzbestand wird
abgewiesen. Bestehende Zielordner werden nicht ueberschrieben.

## 3. Modelle ausfuehren oder externe Schaetzungen bewerten

```bash
python3 render/separation_benchmark.py run-cdx \
  out/separation-benchmark/reference-v1/corpus.json \
  --cdx-config /pfad/cdx-config.json --quality standard --device cpu \
  --timeout 600 --strict --output-dir out/separation-benchmark/cdx-standard-01

python3 render/separation_benchmark.py run-cdx \
  out/separation-benchmark/reference-v1/corpus.json \
  --cdx-config /pfad/cdx-config.json --quality high --device cpu \
  --timeout 1800 --strict --output-dir out/separation-benchmark/cdx-high-01
```

Der vorhandene CDX-Adapter wird wiederverwendet, einschliesslich lokaler
Checkpoint-/Checkout-Pruefung, Runtime-Lock sofern registriert, und des
konfigurierten Laders. [CDX-Setup](DECOMPOSITION.md). Es gibt keine automatischen
Modell- oder Daten-Downloads. Standard und High werden nicht als gleichwertig
verifiziert betrachtet. Das Zeitlimit gilt je Fall fuer den Modellprozess.
CDX resampelt intern auf 44.1 kHz und gibt die Stems auf dem Corpus-Sampleraster
aus; dies wird nicht durch nachtraegliches Fitting der Referenzen kompensiert.

Eine misslungene Summenpruefung verhindert hier absichtlich nicht die weitere
Einzelspurmessung. Modellfehler und fehlende/defekte Ausgaben werden als
fehlgeschlagene Faelle aufgelistet. Sie verschwinden nicht aus dem Nenner.
Ausgabepakete enthalten `report.json` und die modellierten Einzelspuren unter
`estimates/<case-id>/{music,dialogue,sfx}.wav`.

Andere Backends koennen exakt diese Dateistruktur liefern:

```bash
python3 render/separation_benchmark.py evaluate \
  out/separation-benchmark/reference-v1/corpus.json \
  --estimates-dir /pfad/andere-schaetzungen --name anderer-kandidat \
  --strict --output-dir out/separation-benchmark/anderer-kandidat-01
```

Externe Ausgaben werden als `external-unverified` gekennzeichnet. Der
Dateivergleich bestaetigt nicht, welches Modell sie tatsaechlich erzeugt hat.

## Kennzahlen und Grenzen

| Kennzahl | Aussage / Grenze |
|---|---|
| Waveform-SNR | Fehler gegen dieselbe benannte Referenz, inklusive Pegel- und Phasenfehlern |
| SI-SDR | Signalanteil gegen Projektionsrest; ignoriert einen gemeinsamen Skalierungsfaktor |
| SI-SDR-Verbesserung | Differenz zum unverarbeiteten Mix als Schaetzung derselben Quelle |
| Energie in Referenz-Stille | Unerwuenschte Ausgabe in 250-ms-Fenstern mit Referenz-RMS ≤ 0.00001 |
| Quellen-Projektionsmatrix | Lineare Anteile bekannter Quellen; kein wahrgenommener Leakage-Prozentsatz |
| Summenrest | Diagnose der gemeinsamen Rekonstruktion, getrennt von den Einzelspuren |

Die skalare SI-SDR-Projektion folgt
[Le Roux et al., SDR – Half-baked or Well Done?, Gleichung 5](https://arxiv.org/abs/1811.02508).
Zusaetzliche pegelabhaengige Messung verhindert, dass eine gute SI-SDR allein
eine stark abgesenkte oder invertierte Ausgabe als korrekt erscheinen laesst.
DC wird fuer SI-SDR je Kanal entfernt; die Projektion ist gemeinsam ueber
alle Kanaele. Es gibt kein Mono-Downmixing, Latenz-Fitting oder Filter-Fitting.

Messwerte sind auf −120 bis +120 dB begrenzt; JSON enthaelt kein NaN/Infinity.
Bei stiller Referenz wird kein SDR erfunden: er ist `null`, stattdessen wird
die absolute Ausgabeenergie geprueft. Eine stumme Schaetzung einer aktiven
Quelle erhaelt −120 dB SI-SDR. Bei stark korrelierten Referenzen wird die
Quellen-Projektionsmatrix als nicht auswertbar gemeldet.

Die Standard-Grenzwerte sind **vorlaeufige Engineering-Werte**, keine an
Hoertests kalibrierten Akzeptanzgrenzen:

```json
{
  "minimum_snr_db": 10.0,
  "minimum_si_sdr_improvement_db": 3.0,
  "maximum_silent_rms": 0.0001,
  "maximum_mix_residual_ratio": 0.1
}
```

Eine eigene JSON-Konfiguration kann mit `--gate-config` uebergeben werden und
wird im Bericht gespeichert. Bereits perfekte Mix-Baselines muessen nicht
ueber die numerische 120-dB-Obergrenze hinaus verbessert werden.
Alle Rollen muessen ihre Gates bestehen. Der Bericht zeigt pro Rolle
Fallzahlen und Medianwerte; kurze/leise Quellen werden nicht durch eine
energiedominante Musikspur in einem Gesamtscore verdeckt.

## 4. Faire, gepaarte Vergleiche

```bash
python3 render/separation_benchmark.py compare \
  out/separation-benchmark/cdx-standard-01/report.json \
  out/separation-benchmark/cdx-high-01/report.json \
  --output-dir out/separation-benchmark/standard-vs-high
```

Corpus-ID, Case-Abdeckung, Metrik-/Benchmark-Codehash, Gates und Messregeln muessen
uebereinstimmen. Pro Fall und Rolle wird `rechts minus links` ausgewiesen,
einschliesslich der Energie in Referenz-Stille und beider Gate-Ergebnisse.
Fehlende oder fehlgeschlagene Faelle bleiben sichtbar; es wird kein pauschaler
Modellsieger aus einem unvollstaendigen oder synthetischen Test abgeleitet.
Nach Aenderungen am Mess-/Ladecode die gespeicherten Stems mit `evaluate`
erneut messen; reine Berichtsaenderungen duerfen die Vergleichbarkeit nicht
stillschweigend vortaeuschen.
Feste Referenzen bedeuten nicht bitidentische Modellinferenz: insbesondere
CDX verwendet zufaellige Shifts. Fuer belastbare Modellvergleiche sind mehrere
Laeufe, repraesentative Aufnahmen und Hoerpruefungen weiterhin erforderlich.

Exitcodes: `0` Messung abgeschlossen; `1` Konfigurations-/Referenzfehler;
`2` fehlgeschlagene Faelle, unvollstaendiger Vergleich oder verfehlte Gates bei
`--strict`. Fehlerhafte Modellresultate bleiben als Diagnosebericht erhalten,
inkonsistente Referenzen erzeugen hingegen kein gueltiges Ergebnispaket.

## Tests / aktueller Nachweis

```bash
python3 -m unittest discover -s tests

NEXPT_RUN_KNOWN_STEMS_LIVE=1 \
NEXPT_CDX_CONFIG=/pfad/cdx-config.json \
NEXPT_KNOWN_STEM_CORPUS=/pfad/echte-referenzen/corpus.json \
python3 -m unittest discover -s tests -p test_separation_benchmark_live.py -v
```

Ausgefuehrt: deterministischer Self-Test, analytische Metriktests sowie
CLI-/ffmpeg-Integration mit ausdruecklichem CDX-Testdouble. Ein Testdouble
liefert eine perfekte Summe, verfehlt aber korrekt die neuen Einzelspur-Gates.
Standardsuite nach dieser Erweiterung: 262 Tests, davon 259 bestanden und
drei optionale Live-Tests uebersprungen. Neu sind 43 regulaere Tests und ein
separater opt-in Test fuer bekannte isolierte Aufnahmen.
In diesem Entwicklungsschritt wurde **kein neuer echter Modellvergleich mit
isolierten Aufnahmen** ausgefuehrt; die Modellruntime und ein entsprechender
gelabelter Aufnahme-Corpus waren nicht vorhanden. Die vorherigen realen
Referenzlaeufe stehen weiterhin in [CDX-VALIDATION.md](CDX-VALIDATION.md).

Der opt-in Live-Test lehnt den synthetischen Kontroll-Corpus ab und verlangt
einen sicheren CDX-Lader. Nach expliziter Aktivierung sind fehlende
Voraussetzungen Testfehler, keine erfolgreichen Skips. Ein bestandener
numerischer Benchmark ersetzt weder Hoerfreigabe noch GarageBand-Abnahme.
