# Blinde Hoerpruefung fuer CDX Standard gegen High

Die numerischen A/B-Metriken messen bekannte Einzelspuren, aber keine
wahrgenommenen Artefakte, Klangnatuerlichkeit oder praktische Nutzbarkeit in
GarageBand. `separation_listening.py` schliesst diese Luecke mit einem lokalen,
blinden A/B-Workflow. Es fuehrt keine neue Modellinferenz aus und bestimmt
keinen automatischen Sieger.

## Voraussetzungen

- ein vollstaendig abgeschlossener `run-ab`-Versuch ohne fehlgeschlagene Cases;
- der exakt dazugehoerende Referenz-Corpus;
- ausreichend freier Speicher fuer bytegleiche Kopien aller Kandidaten und
  Referenzen. Das Paket ist auf 8 GiB begrenzt.

Unvollstaendige Versuche werden nicht teilweise verpackt. Fehlgeschlagene
Cases werden nicht aus dem Hoertest entfernt, weil dies die Auswahl verzerren
wuerde.

## 1. Blindes Paket erstellen

```bash
python3 render/separation_listening.py build \
  out/separation-benchmark/cdx-standard-vs-high-01 \
  out/separation-benchmark/reference-v1/corpus.json \
  --output-dir out/separation-benchmark/listening-01
```

Das Ergebnis trennt die weitergebbaren Daten von der Aufloesung:

```text
listening-01/
├── public/                  # nur diesen Ordner an Reviewer geben
│   ├── README.md
│   ├── manifest.json
│   ├── review-template.json
│   └── audio/
│       ├── references/     # Mix und bekannte Zielspur je Case
│       └── items/          # anonyme A.wav und B.wav
└── private/
    └── key.json            # bis zum Abschluss nicht weitergeben
```

Items und Kandidatenseiten werden mit dem kryptografisch sicheren lokalen
Zufallsgenerator gemischt. Die Anzahl der High-Zuordnungen auf Seite A und B
unterscheidet sich hoechstens um eins. Profilnamen, Job-IDs und die Zuordnung
stehen nicht im `public`-Paket. Wer gleichzeitig Zugriff auf den A/B-Versuch
oder den privaten Schluessel besitzt, kann die lokale Verblindung jedoch
aufheben; sie ist kein Schutz gegen einen absichtlichen Angreifer.

Alle WAVs werden ohne Normalisierung, Gain-Anpassung, Resampling oder
Neukodierung kopiert. Manifest und privater Schluessel binden ihre SHA-256-
Werte an Experiment und Corpus. Symlinks, unbekannte Artefakte, veraenderte
Dateien und fehlende Trial/Case/Rollen-Kombinationen werden abgewiesen.

## 2. Bewertung ausfuellen

`public/review-template.json` pro Person kopieren. `reviewer_id` muss eindeutig
sein. Fuer jedes Item sind folgende Werte Pflicht:

| Feld | Werte |
|---|---|
| `preference` | `A`, `B`, `tie`, `both_unusable` |
| `confidence` | 1 unsicher bis 5 sehr sicher |
| `reference_match` | 1 passt nicht bis 5 passt sehr gut |
| `isolation` | 1 starke Fremdanteile bis 5 sauber isoliert |
| `artifact_free` | 1 starke Artefakte bis 5 keine wahrnehmbaren Artefakte |

Zuerst die bekannte Referenz, danach A und B bei unveraenderter
Wiedergabelautstaerke abhoeren. Der Mix ist Kontext. Fuer den ganzen Durchgang
dieselben Kopfhoerer oder Monitore verwenden und Klangverbesserer deaktivieren.
Notizen sind optional und auf 2'000 Zeichen pro Item begrenzt.

## 3. Bewertungen validieren und entblinden

```bash
python3 render/separation_listening.py summarize \
  out/separation-benchmark/listening-01 \
  /pfad/review-christian.json /pfad/review-02.json \
  --experiment out/separation-benchmark/cdx-standard-vs-high-01 \
  --corpus out/separation-benchmark/reference-v1/corpus.json \
  --output-dir out/separation-benchmark/listening-summary-01
```

Vor der Entblindung prueft der Befehl erneut:

- Manifest, privaten Schluessel und alle verpackten WAV-Hashes;
- exakte Referenzbindung an den Corpus;
- Kandidatenbindung an Profil, Trial, Case und Rolle im A/B-Versuch;
- vollstaendige, eindeutig benannte Reviewer und ganzzahlige Skalenwerte;
- unveraenderte Bewertungsdateien waehrend der Auswertung.

Die Zusammenfassung enthaelt je Rolle und insgesamt:

- Praeferenzzaehler fuer `standard`, `high`, `tie` und `both_unusable`;
- beobachtete Anzahl, Median, Minimum und Maximum fuer
  `high_minus_standard` je Bewertungskriterium;
- Konfidenzverteilung und eine deskriptive Aufschluesselung je Item.

Wiederholte Bewertungen derselben Aufnahmen sind keine neuen unabhaengigen
Aufnahmen. Deshalb bleiben `overall_winner: null` und
`perceptual_quality_verified: false`. Eine ausgefuellte JSON-Datei dokumentiert
eine erklaerte menschliche Bewertung; der Code kann nicht beweisen, dass die
Person wirklich gehoert oder kontrollierte Wiedergabebedingungen eingehalten
hat. Die Freigabe des Profils und die GarageBand-Abnahme bleiben bewusste
Entscheidungen.

## Testgrenze

Die Unit- und E2E-Tests verwenden deklarierte CDX-Testdoubles und generierte
Diagnosesignale. Sie pruefen Prozessgrenzen, echte WAV-Dateien, Bytegleichheit,
Verblindung, Transaktionen, Manipulationsschutz und Entblindung. Sie sind kein
akustischer Nachweis fuer die realen Modelle.

Standardsuite nach diesem Schritt: **353 Tests, 350 bestanden und drei
optionale Live-Tests uebersprungen**. Neu sind 15 Unit- und sechs E2E-Tests.
In dieser Umgebung wurden weiterhin keine echten CDX-Checkpoints und keine
isolierten Aufnahme-Referenzen bereitgestellt; deshalb belegt der Testlauf die
Softwarevertraege, nicht eine hoerbare Modellverbesserung.
