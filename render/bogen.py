#!/usr/bin/env python3
"""Dem Original-Loop einen Bogen geben — ohne einen einzigen Sample zu ersetzen.

    python3 bogen.py              -> out/music-bogen.wav
    python3 bogen.py --bericht    nur die Kurve zeigen, nichts schreiben

WAS HIER DAS PROBLEM IST UND WAS NICHT

Der Loop klingt richtig, weil er richtig IST — es ist die lizenzierte Aufnahme,
echte Perkussion, kein Nachbau. Sein einziges Problem war nie der Klang. Er
laeuft 4.25 mal durch (16 Takte Quelle, 68 Takte Film) und hat deshalb ueber
2:18 kein Auf und Ab: Takt 9 klingt wie Takt 25 wie Takt 57.

Zwei Wege wurden schon probiert und sind beide gescheitert:

  Takte umsortieren   26 Nahtstellen auf 2:18, 16 der 27 Bloecke nur einen
                      Takt lang. Weil Taktkanten leise sind (-46 dB kurz
                      davor), frisst die 24-ms-Blende 26 mal den ersten
                      Schlag. Gemessen, gehoert, verworfen.
  Neu synthetisieren  Sinus und gefiltertes Rauschen klingen nach Roboter,
                      weil es einer ist. Ebenfalls verworfen — zweimal.

Der dritte Weg aendert die ZEITACHSE gar nicht. Jeder Sample bleibt an seiner
Stelle und bleibt der Original-Sample; veraendert wird nur, WIE LAUT und WIE
HELL er zu hoeren ist. Es wird nichts geschnitten, nichts umgestellt, nichts
erzeugt. Deshalb gibt es auch keine Naht, an der etwas kaputtgehen koennte.

WIE „WENIGER INSTRUMENTE" ENTSTEHT, OHNE SPUREN ZU HABEN

Eine fertige Mischung laesst sich nicht in ihre Instrumente zerlegen. Aber in
dieser Aufnahme sitzen die Elemente in verschiedenen Baendern: die Bassdrum
unter 250 Hz (gemessen 78% der Energie), Fell und Rim in der Mitte, Stoecke und
Teppich ueber 4.5 kHz. Blendet man kontinuierlich zwischen der vollen Fassung
und zwei tiefpassgefilterten Kopien, verschwinden zuerst die hellen Anschlaege,
dann die Mitten — es klingt, als spiele die Band ausgeduennt weiter, nicht als
drehe jemand am Lautstaerkeregler. Drei Kopien, kontinuierlich ueberblendet,
keine schaltenden Filter: zeitvariable Filter zerren, Ueberblendungen nicht.

DER BOGEN KOMMT AUS DEM FILM, NICHT AUS DEM GESCHMACK

Die Abschnitte unten sind an timing.json abgelesen: jede Grenze ist der Beginn
einer Szene, in Takten bei 118.00 BPM. Die Rueckzuege liegen auf den Szenen,
die im Drehbuch ohnehin ein Innehalten sind — „Moment. Nein.", „(das ist der
Trick)", „NEIN.", „(auch nicht im UI)". Der Hochpunkt liegt auf „Hundert
Prozent verbunden" bis „Sehen es alle. Sofort."
"""
import json, os, shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
SR = 48000
BPM = 118.0
BAR = 240.0 / BPM          # 2.0339 s
QUELLE = OUT / "music.wav"

# (ab Takt, Energie 0..1, Name) — Energie 1.0 ist der Loop unveraendert.
# Die Takte sind aus timing.json: start / BAR, auf die naechste Taktkante.
BOGEN = [
    ( 0, 0.40, "Anfang — wir sind Raphael und Christian"),
    ( 4, 0.62, "das Versprechen"),
    ( 7, 0.22, "Moment. Nein."),
    ( 9, 0.66, "Arbeite so, wie du willst"),
    (11, 0.30, "(ja, auch du in der Buchhaltung)"),
    (12, 0.72, "die Wege — Sprints, Phasen, Tickets"),
    (16, 0.80, "Softwareteam. Baustelle. Betrieb."),
    (19, 0.86, "die Flut der Begriffe"),
    (22, 0.78, "die vier Rollen"),
    (26, 0.16, "(das ist der Trick)"),
    (27, 0.70, "Vier Sichtweisen. Ein Chaos?"),
    (29, 0.06, "NEIN."),
    (30, 0.68, "das Modell — oben Sprache, unten Standard"),
    (35, 0.74, "vom Projekt in den Betrieb"),
    (40, 0.88, "hunderte von Tickets"),
    (42, 1.00, "Hundert Prozent verbunden"),
    (46, 1.00, "Sehen es alle. Sofort."),
    (48, 0.52, "Transparenz ist kein Bericht"),
    (50, 0.44, "Struktur allein ist keine Uebersicht"),
    (51, 0.72, "die Tabelle, der Stapel"),
    (57, 0.34, "Bei uns gibt es keine."),
    (59, 0.10, "(auch nicht im UI)"),
    (60, 0.80, "Du siehst, was du brauchst"),
    (62, 0.90, "Also arbeite, wie du willst"),
    (65, 1.00, "NEXPT ist dein Partner"),
]


def laden(pfad):
    roh = subprocess.run([FFMPEG, "-v", "quiet", "-i", str(pfad), "-ac", "2",
                          "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(roh, "<f4").astype(np.float64).reshape(-1, 2)


def tiefpass(x, hz):
    """Nullphasiger Tiefpass ueber die FFT — keine Gruppenlaufzeit, also
    bleibt jeder Anschlag genau dort, wo er im Original liegt. Genau darum
    geht es hier; ein IIR-Filter wuerde die Schlaege um Millisekunden
    verschieben und der Bogen wuerde das Raster antasten."""
    n = len(x)
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    # Weiche Flanke ueber eine Oktave, sonst klingelt die Kante hoerbar.
    H = 1.0 / np.sqrt(1.0 + (f / hz) ** 6)
    return np.fft.irfft(X * H[:, None], n, axis=0)


def kurve(n_takte, n_samples):
    """Energie je Sample: zwischen den Abschnitten mit einer Cosinus-Rampe,
    die genau eine Taktkante lang ist. Kein Sprung, kein Rechteck."""
    e_takt = np.empty(n_takte)
    for i, (ab, energie, _) in enumerate(BOGEN):
        bis = BOGEN[i + 1][0] if i + 1 < len(BOGEN) else n_takte
        e_takt[ab:min(bis, n_takte)] = energie
    # Rampe ueber einen halben Takt um jede Abschnittsgrenze.
    e = np.repeat(e_takt, int(round(BAR * SR)))[:n_samples]
    if len(e) < n_samples:
        e = np.concatenate([e, np.full(n_samples - len(e), e_takt[-1])])
    F = int(round(BAR * SR / 2))
    kern = (1 - np.cos(np.linspace(0, np.pi, F))) / 2
    kern /= kern.sum()
    return np.convolve(e, kern, mode="same"), e_takt


def main():
    if not QUELLE.exists():
        print(f"{QUELLE} fehlt — zuerst `python3 render/musik.py`."); sys.exit(1)
    y = laden(QUELLE)
    n = len(y)
    n_takte = int(round(n / SR / BAR))
    e, e_takt = kurve(n_takte, n)

    if "--bericht" in sys.argv:
        print(f"{QUELLE.name}: {n/SR:.2f}s = {n_takte} Takte")
        print(f"{'Takt':>5}{'Zeit':>9}{'Energie':>9}  Szene")
        for ab, energie, name in BOGEN:
            print(f"{ab:5d}{ab*BAR:8.2f}s{energie:9.2f}  {name}")
        return

    # Drei Fassungen desselben Materials. Nicht drei Klaenge — dieselbe
    # Aufnahme, nur unterschiedlich weit geoeffnet.
    voll  = y
    mitte = tiefpass(y, 2000.0)
    tief  = tiefpass(y, 600.0)

    # Ueberblendung: unter 0.35 zwischen tief und mitte, darueber zwischen
    # mitte und voll. So verschwinden erst die Stoecke, dann die Mitten.
    u = np.clip(e, 0.0, 1.0)[:, None]
    unten = np.clip(u / 0.35, 0, 1)
    oben  = np.clip((u - 0.35) / 0.65, 0, 1)
    klang = tief + (mitte - tief) * unten + (voll - mitte) * oben

    # Pegel: nicht linear mit der Energie, sonst wird leise gleich weg.
    # 0.0 -> -18 dB, 1.0 -> 0 dB, dazwischen mit Exponent 0.6 gestaucht.
    pegel = 10 ** ((-18.0 * (1.0 - u ** 0.6)) / 20.0)
    aus = klang * pegel

    spitze = np.max(np.abs(aus)) or 1.0
    aus = aus / spitze * (np.max(np.abs(y)) or 1.0)

    ziel = OUT / "music-bogen.wav"
    with wave.open(str(ziel), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(aus, -1, 1) * 32767).astype("<i2").tobytes())

    # Belegen, dass wirklich nur geformt und nichts verschoben wurde: die
    # Anschlagszeitpunkte muessen identisch bleiben.
    def anschlaege(x):
        m = x.mean(1)
        F = int(0.005 * SR)
        h = np.sqrt(np.convolve(m ** 2, np.ones(F) / F, mode="same"))
        s = np.percentile(h, 96)
        idx = [i for i in range(1, len(h) - 1)
               if h[i] > s and h[i] >= h[i - 1] and h[i] > h[i + 1]]
        t = []
        for i in idx:
            if t and i / SR - t[-1] < 0.06: continue
            t.append(i / SR)
        return np.array(t)

    a1, a2 = anschlaege(y), anschlaege(aus)
    paare = [min(abs(a1 - t)) for t in a2] if len(a1) and len(a2) else []
    versatz = float(np.median(paare) * 1000) if paare else 0.0

    print(f"{ziel} — {n/SR:.1f}s, {n_takte} Takte, {len(BOGEN)} Abschnitte")
    print(f"  Energie {e_takt.min():.2f} bis {e_takt.max():.2f}, "
          f"Median {np.median(e_takt):.2f}")
    print(f"  Anschlaege: {len(a1)} im Original, {len(a2)} danach, "
          f"Versatz im Median {versatz:.1f} ms")
    if versatz > 5.0:
        print("  ACHTUNG: die Schlaege haben sich verschoben — das darf nicht sein.")


if __name__ == "__main__":
    main()
