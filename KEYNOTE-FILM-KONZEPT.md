# NEXPT Work — Keynote-Film

**Konzept, Drehbuch und Produktionsplan**
Stil-Referenz: Apple, *„Every product carbon neutral by 2030"* ([YouTube](https://www.youtube.com/watch?v=66XwG1CLHuU))
Einsatz: Messe- / Event-Keynote (Opener vor Publikum)
Laufzeit: **3:20** · Sprache: DE (EN-Version vorgesehen) · Format: 16:9, Voice-Over

---

## 0. Grundlage und Vorbehalt

Zum Referenzvideo: YouTube blockt das Auslesen der Seite. Verifiziert sind über die
oEmbed-Schnittstelle **Titel** („Every product carbon neutral by 2030"), **Kanal** (Apple)
und **Thumbnail**. Den Schnitt selbst konnte ich nicht ansehen. Die Stilanalyse in Abschnitt 1
beruht daher auf Apples dokumentierter Haus-Sprache für Commitment-Filme dieser Reihe,
nicht auf einer Einstellungsanalyse dieses konkreten Films.

**Falls Beats abweichen:** die Beat-Struktur in Abschnitt 3 ist bewusst modular. Sag mir,
was im Original anders läuft, und ich ziehe es nach.

Produktseite: gelesen aus `Chregu12/Nexpt-2.0` — `README.md`, `apps/nexpt-work/docs/OVERVIEW.md`,
`docs/architecture/UOMF-DOMAIN-FIT.md`, `docs/architecture/UOMF-WELTC-DECISION.md`,
`apps/nexpt-work/docs/business/BUSINESS_CASE_NEXPT.md`.

---

## 1. Was diesen Apple-Stil trägt — sieben Regeln

Diese sieben Regeln sind der eigentliche Stil. Wer sie bricht, dreht einen normalen Imagefilm.

| # | Regel | Warum sie wirkt |
|---|---|---|
| **1** | **Ein Versprechen, datiert und messbar.** Nicht „nachhaltiger", sondern „jedes Produkt CO₂-neutral bis 2030". | Ein überprüfbarer Satz ist Haltung. Ein Adjektiv ist Werbung. |
| **2** | **Kalter Einstieg ohne Logo.** Erst nach dem Problem kommt die Marke. | Das Publikum hört zu, weil es noch nicht weiss, wer spricht. |
| **3** | **Sparsamer Text, viel Stille.** ~220 Wörter auf 3:20. Kurze Aussagesätze, keine Nebensätze. | Der Ton trägt, wo Text erklären würde. |
| **4** | **Zahlen als Vollbild-Typografie.** Keine Charts, keine Bulletpoints. Eine Zahl, ein Bild. | Eine Zahl allein auf der Leinwand ist eine Behauptung, zu der man steht. |
| **5** | **Makro gegen Mikro.** Weltkarte gegen eine einzelne Hand. Lieferkette gegen ein Bauteil. | Massstabswechsel erzeugt Bedeutung ohne Erklärung. |
| **6** | **Eine ehrliche Lücke.** Explizit sagen, was noch nicht erreicht ist. | Das ist der teuerste und wirksamste Moment. Er kauft die Glaubwürdigkeit für alles davor. |
| **7** | **Kein Feature-Tour.** Der Film verkauft eine Verpflichtung, kein Produkt. Screenshots kommen fast nicht vor. | Die Demo läuft nach der Keynote. Der Film macht sie erst sehenswert. |

**Anti-Regeln — das kommt nicht vor:** Sprecher im Bild, Testimonials, Logowand,
„Wir sind Ihr Partner für…", Musik mit Beat-Drop, Feature-Listen, Bildschirm-Aufnahmen
mit Mauszeiger, Stock-Footage von lächelnden Menschen am Whiteboard.

---

## 2. Die Übertragung: Was ist NEXPTs „carbon neutral by 2030"?

Apples Versprechen funktioniert, weil es **etwas abschafft** (CO₂), **datiert** ist (2030)
und **prüfbar** (pro Produkt). NEXPT Work braucht ein Äquivalent mit denselben drei Eigenschaften.

Was NEXPT Work laut Architektur wirklich abschafft, ist **das zweite System**: die kanonische
Fünf-Stufen-Hierarchie (`goal → program → deliverable → work_package → action`), `work_mode`
und der Vokabular-Layer tragen Wasserfall/HERMES, Scrum, SAFe, ITIL und Treuhand auf
demselben Modell — die Branche ist Konfiguration, nicht Code.

> ### Das Versprechen des Films
> # „Eine Arbeit. Ein Modell."
> **Keine zweite Plattform, wenn das Projekt in den Betrieb geht.**

Das ist der Satz, der als Titelkarte steht, der die vier Kapitel klammert und der am Ende
wiederholt wird. Alles im Film dient diesem einen Satz.

**Der Gegner im ersten Akt** ist nicht ein Wettbewerber, sondern der **Systembruch**:
dieselbe Arbeit, fünfmal modelliert, in fünf Werkzeugen, mit fünf Vokabularen — und der
Übergang vom Projekt in den Betrieb als Copy-Paste.

### Die vier Kapitel (Apples Materials / Electricity / Transportation / Water)

| Apple | NEXPT Work | Fachlicher Kern | Der Satz |
|---|---|---|---|
| Materials | **Struktur** | `canonical_type`, 5 Stufen, `hierarchy_rules` | „Fünf Stufen. Mehr braucht Arbeit nicht." |
| Electricity | **Sprache** | `vocabulary_entries` je Branche, DE/EN | „Dieselbe Struktur. Eure Wörter." |
| Transportation | **Modus** | `work_mode`: `change → run → maintenance` | „Ein Projekt endet. Die Arbeit nicht." |
| Water | **Regel** | Approval-Gates, RACI, Kapazität, Policies | „Governance ist Konfiguration. Nicht Code." |

---

## 3. Beat Sheet — 3:20

| TC | Beat | Bild | Ton | Text im Bild |
|---|---|---|---|---|
| 0:00–0:12 | **Kalter Einstieg** | Schwarz. Dann: eine einzelne Zeile in einer Tabelle, extremes Makro. Der Cursor blinkt. Schnitt: dieselbe Aufgabe in einem zweiten Werkzeug. Dritten. Vierten. | Stille, dann ein tiefer Ton, der nicht auflöst | — |
| 0:12–0:35 | **Das Problem** | Split auf 5 Kacheln, alle mit *derselben* Aufgabe in anderem Vokabular: *Story · Arbeitspaket · Incident · Mandat · Change*. Sie driften auseinander. | Sehr leises Sirren, ein Puls | `Dieselbe Arbeit.` → `Fünf Modelle.` |
| 0:35–0:48 | **Der Bruch** | Ein Balken „Projektabschluss". Dahinter: der Betrieb beginnt bei null. Ein Export als CSV, per Hand wieder eingetippt. | Der Puls bricht ab. Stille. | `Und dann fängt der Betrieb von vorne an.` |
| 0:48–1:00 | **Titelkarte** | Schwarz → Weiss. Nur Typografie, zentriert, viel Luft. Erstes Auftreten der Marke. | Erster warmer Akkord | **`Eine Arbeit. Ein Modell.`** klein darunter: `NEXPT Work` |
| 1:00–1:28 | **Kapitel 1 — Struktur** | Fünf Ebenen bauen sich vertikal auf, eine nach der anderen, mit hörbarem Einrasten. Kein UI — reine Geometrie. | Score setzt ein, ruhig | `Ziel · Programm · Ergebnis · Arbeitspaket · Aktion` |
| 1:28–1:56 | **Kapitel 2 — Sprache** | Dieselbe Geometrie, stehenbleibend. Nur die **Beschriftungen** morphen: Scrum → HERMES → ITIL → Treuhand. Die Struktur bewegt sich nicht. | Score hält, ein Instrument kommt dazu | `Ein Modell.` (Zahl-Vollbild) |
| 1:56–2:24 | **Kapitel 3 — Modus** | **Das Herzstück.** Ein einzelnes Item, Makro. Der Modus schaltet um: `change` → `run`. Der Rahmen bleibt, das Item wandert nicht in ein anderes System. Weit ziehen: dasselbe Item, jetzt im Betriebs-Board. | Score öffnet sich | `Projekt → Betrieb` · `Dasselbe Item.` |
| 2:24–2:44 | **Kapitel 4 — Regel** | Ein Gate schliesst. Zwei Rollen bestätigen. Es öffnet. Trocken, mechanisch, ohne Effekt. | Score reduziert sich auf einen Ton | `Konfiguration. Nicht Code.` |
| 2:44–3:02 | **Die ehrliche Lücke** | Schnitt auf Schwarz. Text allein, keine Musik unter dem ersten Satz. | Musik setzt aus, dann wieder ein | *(siehe Drehbuch — Abstimmung nötig, Abschnitt 8)* |
| 3:02–3:20 | **Schluss** | Weiss. Die fünf Ebenen ein letztes Mal, klein, ruhig. Dann nur der Satz. | Score löst auf einem offenen Akkord auf | **`Eine Arbeit. Ein Modell.`** → `NEXPT Work` |

---

## 4. Drehbuch / Sprechertext

> **Regie:** Eine Stimme, weiblich oder männlich, ruhig, tief, kein Werbeduktus.
> Tempo langsam. **Die Pausen sind Teil des Textes** — die eckigen Angaben einhalten.
> Schweizer Hochdeutsch, keine Dialektfärbung, „ss" statt „ß".

```
[0:12]
Eine Aufgabe.

[Pause 2s]

Fünf Systeme. Fünf Sprachen. Fünf Wahrheiten.

[0:35]
Und wenn das Projekt fertig ist,
fängt der Betrieb noch einmal von vorne an.

[Pause 3s — Bild trägt allein]

[0:48 — Titelkarte, kein Text]

[1:00]
Arbeit hat eine Struktur.
Ziel. Programm. Ergebnis. Arbeitspaket. Aktion.

[Pause 2s]

Fünf Stufen. Mehr braucht sie nicht.

[1:28]
Was sich ändert, ist nicht die Struktur.
Es sind die Wörter.

Story. Arbeitspaket. Incident. Mandat.

[Pause 2s]

Dieselbe Struktur. Eure Wörter.

[1:56]
Ein Projekt endet.

[Pause 2s]

Die Arbeit nicht.

Bei uns wechselt sie nicht das System.
Sie wechselt den Modus.

[2:24]
Freigaben. Rollen. Kapazität.
Wer was entscheiden darf, steht nicht im Code.

[Pause 1s]

Es ist Konfiguration.

[2:44 — DIE EHRLICHE LÜCKE, Fassung wählen, s. Abschnitt 8]
Wir sind nicht fertig.
Der Betrieb läuft heute noch neben diesem Modell — nicht darin.
Das steht in unserer Architektur-Dokumentation.
Nicht im Kleingedruckten.

[Pause 2s]

Wir sagen Ihnen, wo wir stehen.
Und wohin wir gehen.

[3:02]
Eine Arbeit.

[Pause 1.5s]

Ein Modell.

[Pause 2s]

NEXPT Work.
```

**Wortzahl: ca. 120.** Das ist Absicht. Apple-Commitment-Filme laufen bei etwa einem Drittel
der Wortdichte eines normalen Imagefilms. Wenn beim ersten Schnitt der Impuls kommt,
„da fehlt noch was" — nicht nachgeben. Da fehlt nichts, da ist Raum.

---

## 5. Bildsprache

**Grundsatz: keine Screenshots.** Der Film zeigt das *Modell*, nicht die *Oberfläche*.
Die Oberfläche kommt in der Demo nach dem Film. Wo doch UI nötig ist (Kapitel 3, Sekunde
2:10–2:20): rahmenlos, ohne Browserchrom, ohne Mauszeiger, extrem herangezoomt auf ein
einziges Element.

| Element | Festlegung |
|---|---|
| **Palette** | Zwei Zustände: Schwarz (Akt 1, das Problem) und Weiss (ab Titelkarte). Genau **eine** Akzentfarbe aus dem NEXPT-Brand für den aktiven Zustand. Kein Verlauf, kein Glow. |
| **Typografie** | Eine Schrift, zwei Schnitte. Vollbild-Textkarten: Satz zentriert, mindestens 40 % Weissraum, Zeilenlänge nie über 6 Wörter. |
| **Bewegung** | Alles bewegt sich mit *ease-out*, nie linear, nie federnd. Elemente rasten ein, sie schweben nicht. Kamera: langsame, gleichmässige Fahrten, kein Handheld. |
| **Makro-Ebene** | Der Kontrast lebt vom Wechsel: eine Zeile in Grossaufnahme gegen ein Portfolio in der Totalen. Mindestens ein harter Massstabssprung pro Kapitel. |
| **Menschen** | Höchstens zwei kurze Einstellungen, beide **ohne Blick in die Kamera**: eine Hand an einer Tastatur, jemand, der an einem Board vorbeigeht. Keine Gesichter, kein Lächeln, keine Meetings. |
| **Bühnenformat** | Master in 16:9, 4K. Zusatz-Export für ultrabreite LED-Wände (32:9) — dabei den Weissraum links/rechts erweitern, **nicht** die Typografie skalieren. |

---

## 6. Ton

Der Ton macht in diesem Genre etwa die Hälfte der Wirkung — entsprechend budgetieren.

- **Akt 1 (0:00–0:48):** kein Score. Nur Sounddesign — Tastenanschläge, ein tiefer Puls,
  Raumton. Der Puls bricht bei 0:35 ab. Diese Stille ist der wichtigste Moment vor der Titelkarte.
- **Akt 2 (1:00–2:44):** ein einziges Score-Stück, das über vier Kapitel schichtweise
  aufbaut — je Kapitel ein Instrument mehr. Kein Beat, kein Drop, keine Snare.
- **Akt 3 (2:44):** Musik setzt für den ersten Satz der ehrlichen Lücke **komplett aus**.
  Trockene Stimme auf Schwarz. Danach kommt sie leiser zurück und löst offen auf.
- **Musikrechte:** Komposition kaufen, nicht lizenzieren. Ein Stock-Track macht aus dem
  Film sofort einen Imagefilm — der Score ist hier die Signatur.
- **Sprachversionen:** Voice-Over statt Sprecher im Bild heisst, die EN-Fassung ist ein
  Studiotag, kein zweiter Dreh. Von Anfang an so planen.
- **Messe-Loop-Fassung:** eine Variante **ohne Ton, mit Untertiteln** für den Stand.
  Am Stand hört niemand zu. Diese Fassung braucht grössere Typografie und ~15 % längere
  Standzeiten pro Textkarte.

---

## 7. Produktion

### Drei Umsetzungstiefen

| | **A — Realdreh** | **B — Hybrid** *(Empfehlung)* | **C — Motion Design** |
|---|---|---|---|
| **Ansatz** | Gedrehte Bilder: Büro, Baustelle, Serverraum, Treuhandbüro | Wenige gedrehte Makro-Einstellungen + Motion Design für die Modell-Ebenen | Reine Typografie und Geometrie, kein Dreh |
| **Passt zum Stil?** | Ja, aber nur bei kompromissloser Ausführung | **Ja** — das Modell ist ohnehin abstrakt, das Reale gibt ihm Erdung | Bedingt — wird schnell kühl und austauschbar |
| **Dauer** | 8–12 Wochen | **5–7 Wochen** | 3–4 Wochen |
| **Grössenordnung** ¹ | CHF 40–80k | **CHF 12–25k** | CHF 3–8k |
| **Risiko** | Halbherzig gedrehtes Material zerstört den Stil sofort | Balance zwischen Real und Grafik muss im Storyboard sitzen | Wirkt ohne starken Score wie ein Erklärvideo |

¹ Richtwerte Schweizer Markt, Schätzung meinerseits — kein Angebot. Für Verbindliches
mindestens zwei Offerten einholen.

**Warum B:** Der Kern des Films (die fünf Ebenen, der Moduswechsel) ist ein abstraktes
Modell und lässt sich nicht filmen. Gleichzeitig braucht der Film zwei bis drei reale,
haptische Einstellungen, damit er nicht in reine Grafik kippt. B kauft genau das ein und
nichts darüber hinaus.

### Ablauf

1. **Freigabe Kernsatz** — „Eine Arbeit. Ein Modell." trägt oder trägt nicht. Alles Weitere hängt daran.
2. **Zahlen beschaffen** (Abschnitt 8) — vor dem Storyboard, nicht danach.
3. **Entscheid ehrliche Lücke** (Abschnitt 8) — verändert Akt 3 grundlegend.
4. **Storyboard**, Beat für Beat gegen Abschnitt 3.
5. **Scratch-Voice-Over** selbst einsprechen und gegen das Storyboard legen. Hier fällt auf, ob der Text zu lang ist — er ist es fast immer.
6. **Score-Briefing parallel zum Animatic**, nicht am Schluss.
7. **Produktion.**
8. **Exporte:** Keynote-Master 16:9 · Ultrawide 32:9 · Stand-Loop ohne Ton mit Untertiteln · EN-Fassung · Social-Schnitt 60 s (Akt 1 + Titelkarte + Schluss).

### Für die Bühne

- Der Film ist der **Opener**, er läuft vor dem ersten gesprochenen Wort. Kein Anmoderieren.
- **Kein Applaus-Beat am Ende.** Der Film löst offen auf, die Person betritt in die Stille hinein die Bühne und nimmt den Schlusssatz auf: *„Eine Arbeit. Ein Modell. Ich zeige Ihnen, was das heisst."*
- Saallicht während des Films auf null, inklusive Bühnenlicht. Die Schwarz-auf-Schwarz-Passagen in Akt 1 brauchen das.
- Ton über die Saal-PA, nicht über die Leinwandlautsprecher. Der tiefe Puls in Akt 1 muss körperlich spürbar sein.

---

## 8. Offene Punkte

### 8.1 Zahlen — von dir

Regel 4 („Zahlen als Vollbild") ist der Kern des Stils und der einzige Teil, den ich nicht
erfinden darf. Apples Film funktioniert, weil jede Zahl geprüft ist. Ich brauche zwei bis
drei Zahlen, die belastbar sind:

| Slot | Gesucht | Beispiel für die Form |
|---|---|---|
| Akt 1, 0:25 | Wie viele Werkzeuge führt ein typischer Zielkunde parallel? | „Im Schnitt **7** Systeme." |
| Kapitel 2, 1:50 | Anzahl Branchen-Vokabulare live | „**5** Branchen. **1** Modell." |
| Kapitel 3, 2:20 | Was der Moduswechsel spart — Zeit, Doppelerfassungen, Migrationsaufwand | „**0** Migrationen." |

Wenn belastbare Kundenzahlen fehlen: lieber eine Systemzahl aus der Plattform selbst
(kanonische Stufen, Branchen-Templates, Services) als eine geschätzte Marktzahl. Eine
geschätzte Zahl auf der Leinwand kostet genau die Glaubwürdigkeit, die Regel 6 aufbauen soll.

### 8.2 Die ehrliche Lücke — Entscheidung nötig

Das ist der stärkste Moment des Films und zugleich der einzige, der Rückfragen auslösen kann.
Grundlage ist `docs/architecture/UOMF-DOMAIN-FIT.md`: ITIL- und Treuhand-Arbeit läuft heute
über ein zweites Case-Modell **neben** dem UOMF-Kern, nicht darin. Die Dokumentation nennt das
selbst „strukturell gebrochen".

Genau diese Offenheit ist Apples Move — und sie funktioniert nur, wenn sie echt ist.
Drei Fassungen, absteigend nach Mut:

- **Fassung 1 — offen** *(im Drehbuch oben, die wirksamste)*
  > „Wir sind nicht fertig. Der Betrieb läuft heute noch neben diesem Modell — nicht darin."

  Maximal glaubwürdig. Setzt voraus, dass ihr die Roadmap dahinter im Gespräch am Stand
  belegen könnt, und dass die Geschäftsleitung das öffentlich mitträgt.

- **Fassung 2 — als Richtung formuliert** *(sicherer, fast so stark)*
  > „Projekt und Betrieb in einem Modell — daran arbeiten wir. Wir sagen Ihnen, wo wir stehen."

- **Fassung 3 — weglassen**
  Nicht empfohlen. Ohne Regel 6 ist es ein gut gemachter Imagefilm, aber kein Film in
  diesem Stil. Der ehrliche Moment ist das, was die vorherigen zwei Minuten glaubwürdig macht.

### 8.3 Von mir noch zu klären

- Bestätigung, ob das Referenzvideo tatsächlich der ernste Commitment-Film ist (Abschnitt 0).
- NEXPT Brand-Assets: Schrift, Akzentfarbe, Logo-Sperrzone — für die Typografie-Festlegungen.
- Messe, Datum und Bühnenformat (Leinwandmasse, Seitenverhältnis, PA vorhanden?).
