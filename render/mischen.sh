#!/bin/sh
# Endmischung. Ein Filtergraph, drei Schalter:
#
#     sh render/mischen.sh                  Stimme + Musik + Effekte
#     sh render/mischen.sh --ohne-stimme    nur Musik + Effekte (Standloop)
#     sh render/mischen.sh --drums          zusaetzlich die eigene Percussion
#     sh render/mischen.sh --ohne-effekte   nur Musik und Stimme, zum Vergleich
#     sh render/mischen.sh --drumline       die eigene Partitur statt des Loops
#
# Statt vier Filtergraphen fuer vier Kombinationen gibt es einen einzigen,
# dessen Pegel die Schalter setzen. Eine stumme Spur aendert bei amix mit
# normalize=0 nichts, und ein stummer Sidechain-Key komprimiert nicht —
# die Schalter brauchen also keine eigene Verdrahtung.
#
# MUSIK ist seit dieser Fassung der lizenzierte Track, geschnitten von
# render/musik.py. Vorher stand hier eine selbstgebaute Flaeche; sie hat den
# Mix gemessen auf 147 BPM gezogen, obwohl die Percussion auf 118 lief.
#
# DIE EFFEKTE liegen auf einem eigenen Sidechain: die Musik tritt nicht nur
# unter der Stimme zurueck, sondern auch unter jedem Akzent (Ratio 8, Attack
# 4 ms, Release 180 ms). Das ist genau die „gezielte musikalische Pause, damit
# Effekte hoerbar bleiben" — nur automatisch statt von Hand geschrieben.
#
# PERCUSSION ist standardmaessig AUS. Der Track ist selbst ein
# Schlagzeug — die eigene Drumline daraufzulegen ergibt Matsch, keine
# Betonung. Sie bleibt als Schalter erhalten, falls der Track wechselt.
# Der Referenzfilm hat uebrigens gemessen KEIN Sounddesign auf den
# Bildereignissen; `--sfx none` in sounddesign.py ist seine Fassung.
#
# Pegel wie im Referenzfilm: -17 LUFS integriert, LRA 4.3 LU. Der Kompressor
# ist mit dem echten Track deutlich milder als vorher (Ratio 2.5 statt 4,
# LRA-Ziel 7 statt 5) — der Track ist bereits gemastert, und die harte
# Fassung hat die Mischung auf LRA 2.9 gequetscht. Gemessen ergibt diese
# Einstellung genau die 4.3 LU der Referenz.
# Auf der Messe gegen Hallenlaerm ist Dynamik trotzdem keine Tugend; unter
# 4 LU zu gehen bringt aber nichts mehr, es nimmt nur die Anschlaege weg.
cd "$(dirname "$0")/.." || exit 1
FF=${FFMPEG:-ffmpeg}

V_STIMME=1.0; V_DRUMS=0.0; V_SFX=0.85; ZIEL=out/ton-final.wav
# Welche Musik? Der geschnittene Loop, oder die eigene Partitur, von
# echten Trommeln gespielt (render/partitur.py -> render/drumline.py).
MUSIK=out/music.wav
# Pegel und Dynamik folgen jetzt der zweiten Referenz. Gemessen:
#   Apple    -17.7 LUFS, LRA 4.3   Musik unter dem Bild, keine Effekte
#   Samsung  -13.6 LUFS, LRA 7.7   Akzente +11 dB ueber dem laufenden Bett
# Wir liegen dazwischen und naeher an Samsung: auf der Messe traegt Lautheit,
# und die Akzente brauchen Luft nach oben, sonst sind sie keine.
ZIELPEGEL=-14.5
# Der Kompressor steht sehr mild. Mit dem lizenzierten Track brauchte die
# Standfassung noch eine haertere Einstellung (Ratio 4), weil die Musik ohne
# Stimme sonst 6.7 LU weit wurde. Der eigene Loop ist von sich aus gleich-
# maessig — gemessen kommt die Mischung damit auf 3.5 bis 4.0 LU, und haerter
# zu fahren nimmt nur noch die Anschlaege weg, ohne die Dynamik zu aendern
# (Ratio 2.5 -> 1.6 bewegt sie um 0.4 LU). Beide Fassungen laufen deshalb
# gleich.
KOMP=2; LRA=7
# Die 175-Hz-Senke raeumt die Grundtoene der Sprecherstimme frei. Ohne Stimme
# wuerde sie der Trommel den Bauch wegnehmen, also faellt sie dann weg.
G175=-3.5
for a in "$@"; do
  case "$a" in
    --ohne-stimme) V_STIMME=0.0; G175=0
                   ZIEL=out/ton-final-ohne-stimme.wav ;;
    --ohne-effekte) V_SFX=0.0; ZIEL=out/ton-ohne-effekte.wav ;;
    --drumline)     MUSIK=out/drumline.wav; ZIEL=out/ton-drumline.wav ;;
    --drums)       V_DRUMS=0.55 ;;
  esac
done

for f in out/scratch-vo.wav "$MUSIK" out/sfx.wav out/drums.wav; do
  [ -f "$f" ] || { echo "$f fehlt — sounddesign.py und musik.py laufen lassen."; exit 1; }
done

"$FF" -hide_banner -loglevel error -y \
  -i out/scratch-vo.wav -i "$MUSIK" -i out/sfx.wav -i out/drums.wav \
  -filter_complex "\
    [0:a]aresample=48000,volume=$V_STIMME,asplit=2[vo][vk]; \
    [1:a]aresample=48000,volume=0.38[mu]; \
    [2:a]aresample=48000,volume=$V_SFX,asplit=2[fx][fk]; \
    [3:a]aresample=48000,volume=$V_DRUMS[dr]; \
    [mu][vk]sidechaincompress=threshold=0.05:ratio=6:attack=8:release=260[mu1]; \
    [mu1][fk]sidechaincompress=threshold=0.03:ratio=8:attack=4:release=180[mud]; \
    [mud][fx][dr][vo]amix=inputs=4:normalize=0, \
      equalizer=f=45:t=q:w=0.8:g=3.5, \
      equalizer=f=175:t=q:w=1.2:g=$G175, \
      treble=f=7000:g=2.5, \
      acompressor=threshold=-20dB:ratio=$KOMP:attack=6:release=180:makeup=3, \
      loudnorm=I=$ZIELPEGEL:TP=-1.0:LRA=$LRA,alimiter=limit=0.97[out]" \
  -map "[out]" -c:a pcm_s16le -ar 48000 -ac 2 "$ZIEL"

echo "$ZIEL"
"$FF" -hide_banner -i "$ZIEL" -af ebur128=peak=true -f null - 2>&1 \
  | grep -A1 -E "Integrated|Loudness range" | grep -E "I:|LRA:"
