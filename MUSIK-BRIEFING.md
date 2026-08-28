# Musik-Briefing

Was noch fehlt, damit die Tonspur trägt — und warum ich es nicht selbst machen kann.

## Die Lage

Der gelieferte Loop ist gut und stilistisch richtig. Gemessen: **118.01 BPM**, erster Downbeat
0.480 s, **16 Takte** (33.54 s), danach digitale Stille — ein sauberer Loop. Er spielt sehr eng
auf sein eigenes Raster (Median 1–2 ms zum Sechzehntel) und hat mit 38 starken Anschlägen auf
33.5 s dieselbe Dichte wie die Referenzfilme: 52 % der Viertel tragen einen Schlag.

Das Problem ist nur die Länge. Der Film ist **68 Takte** lang, der Loop 16 — er läuft also
**4¼-mal** durch. Und die Pegel seiner 16 Takte liegen alle zwischen −22.4 und −14.4 dB, fast
alle zwischen −15 und −16: **kein Breakdown, kein Hochpunkt, kein Absturz.**

Genau die drei Stellen, an denen ein Track dem Film folgen müsste.

## Warum ich das nicht löse

Ich kann Ton messen, schneiden, schichten, filtern und im Raster ausrichten. Ich kann **keine
Musik komponieren** — nichts schreiben, das nach gespielt klingt. Jeder Versuch in diese
Richtung endet in Synthese, und Synthese klingt nach Synthese.

Zwei Sackgassen sind schon belegt und müssen nicht wiederholt werden:

**Den Loop umsortieren.** Die 16 Takte nach der Dramaturgie neu anzuordnen ergab 26 Nahtstellen
auf 2:18, davon 16 Blöcke von nur einem Takt Länge. Und weil die Taktkanten leise sind (−46 dB
kurz davor), sitzt der erste Schlag jedes Takts genau auf der Naht und wird von der Blende
angefressen. Ein Loop ist an seiner eigenen Rundung nahtlos, sonst nirgends.

**Selbst synthetisieren.** Sinus plus gefiltertes Rauschen ist ein Synthesizer, egal wie sorgfältig
man ihn an eine Referenzkurve anlegt.

## Was gebraucht wird

**Vier weitere Blöcke**, mit demselben Werkzeug und demselben Klang wie der vorhandene Loop.
Ganze Blöcke, keine Schnipsel — dann setze ich sie ohne eine einzige Naht zusammen.

Für alle vier gilt:

- **Exakt 118 BPM**, 4/4
- **Ganze Takte**, beginnend auf der Eins, ohne Auftakt
- Derselbe Instrumentensatz: Marschtrommel, Snare, Rim Clicks, Stöcke, gedämpfte Toms
- Kein Gesang, keine Melodie, kein Akkordinstrument, keine Flächen
- Trocken, viel Leerraum, spielerisch synkopiert

| # | Länge | Rolle im Film | Was drin sein muss |
|---|---|---|---|
| **A — Intro** | 8 Takte | Takt 1–8 · „Wir sind Raphael und Christian" bis „Moment. Nein." | Sehr dünn. Nur Stöcke und ein gelegentlicher Rim, kein voller Groove. Baut über die 8 Takte leicht auf. |
| **B — Groove** | *vorhanden* | der Hauptteil | Der gelieferte Loop. Bleibt wie er ist. |
| **C — Breakdown** | 8 Takte | Takt 27–34 · `(das ist der Trick)` · „Ein Chaos?" · „NEIN." · Wiederaufbau | Erste 4 Takte fast nichts — ein einzelner Rim je Takt reicht. Ab Takt 5 kommt der Groove zurück, aber noch halb. |
| **D — Hochpunkt** | 16 Takte | Takt 42–57 · „100% verbunden." · „Sehen es alle. SOFORT." · Tabelle · Dateistapel | Die dichteste Fassung. Volle Snare, Toms dazu, Wirbel. Bei Takt 8 ein kurzer Absturz von 2 Takten (dort steht „Aber Struktur ist noch keine Übersicht"), danach wieder auf. |
| **E — Schluss** | 16 Takte | Takt 59–68 · „Du siehst, was du brauchst." bis „NEXPT ist dein Partner" | Baut über die ersten 12 Takte auf, letzte 4 Takte tragen ohne neue Steigerung. Endet auf der Eins von Takt 17, nicht ausblendend. |

### Prompt-Vorlage

Falls das Werkzeug einen Text-Prompt nimmt, hier die Fassung, die zum vorhandenen Loop passt —
je Block den kursiven Teil ersetzen:

> Minimalist percussion for a premium tech commercial. Dry marching snare, rim clicks, stick
> percussion, muted toms, organic drum hits. Exactly 118 BPM, 4/4, starts on the downbeat, no
> pickup. Playful syncopation, quirky stops and starts, punchy accents, lots of negative space.
> No vocals, no melody, no chords, no pads, no synth, minimal bass. Dry and close, small room.
> *[Rolle einsetzen: „Very sparse intro, sticks only, slowly building over 8 bars." /
> „Breakdown: near silence for 4 bars, then the groove returns at half density." /
> „Peak intensity: full snare, toms, rolls — with a 2-bar drop at bar 9." /
> „Final build over 12 bars, then 4 bars holding steady, ending hard on the downbeat."]*

### Wohin damit

Die vier Dateien nach `out/_musik/` legen, benannt nach ihrer Rolle:

```
out/_musik/a-intro.mp3
out/_musik/b-groove.mp3      (= der vorhandene apple-style-118.mp3)
out/_musik/c-breakdown.mp3
out/_musik/d-hochpunkt.mp3
out/_musik/e-schluss.mp3
```

Dann:

```bash
python3 render/musik.py --bloecke      # setzt sie zum Arrangement zusammen
python3 render/proben.py               # Klangpalette neu schneiden
python3 render/takt.py                 # Film auf die neuen Anschläge rastern
python3 render/render.py               # 30 Clips neu
python3 render/cuesheet.py && python3 render/sfx.py
sh render/mischen.sh && python3 render/bauen.py --neu
```

## Die zweite offene Sache: die Stimme

Gemessen liegt die **Roboter-Scratchstimme** bei −7.9 dB der Gesamtenergie und damit fast so
laut wie die Musik (−5.9 dB). Sie ist ein Platzhalter und war nie als Teil des Films gedacht —
wer den Film heute hört, hört zu einem grossen Teil sie. Eine echte Aufnahme ist der grösste
einzelne Sprung, der in dieser Tonspur noch drin ist, grösser als alles am Sounddesign.

## Die dritte: echte Effekte

Das Sounddesign nutzt echte Schläge aus dem Loop, aber der enthält keine tiefe Trommel
(tiefster Schwerpunkt 988 Hz). Unter den Impacts liegt deshalb ein Sinus als Fundament — die
einzige verbliebene Synthese in der ganzen Spur, und in der Effektspur unter 80 Hz auch nur
−6.1 dB gegenüber deren Gesamtenergie.

Sauber lösen lässt sich das mit einer der beiden Quellen:

| | |
|---|---|
| **Freesound-Token** | gratis, CC0-Filter, die Lizenz steht je Datei fest. Reicht für Impacts, Whooshes und Foley. |
| **Kommerzielle Library** | Splice, Soundly, Boom — CHF 100–300 im Jahr, deutlich bessere Auswahl. |

`python3 render/sfx.py --ohne-sinus` baut die Effektspur ohne das Fundament, wenn du hören
willst, was es beiträgt.
