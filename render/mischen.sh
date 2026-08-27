#!/bin/sh
# Endmischung. Ein Filtergraph, drei Schalter:
#
#     sh render/mischen.sh                  Stimme + Musik + Effekte
#     sh render/mischen.sh --ohne-stimme    nur Musik + Effekte (Standloop)
#     sh render/mischen.sh --drums          zusaetzlich die eigene Percussion
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
# PERCUSSION ist deshalb standardmaessig AUS. Der Track ist selbst ein
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

V_STIMME=1.0; V_DRUMS=0.0; ZIEL=out/ton-final.wav
# Mit Stimme fuellen die Woerter die Luecken, die Mischung darf also atmen.
# Ohne Stimme steht die Musik allein und wird in der Halle sonst zu weit —
# gemessen 6.7 LU gegen 4.3 mit Stimme. Die Standfassung wird deshalb
# haerter gefahren.
KOMP=2.5; LRA=7
# Die 175-Hz-Senke raeumt die Grundtoene der Sprecherstimme frei. Ohne Stimme
# wuerde sie der Trommel den Bauch wegnehmen, also faellt sie dann weg.
G175=-3.5
for a in "$@"; do
  case "$a" in
    --ohne-stimme) V_STIMME=0.0; G175=0; KOMP=4; LRA=5
                   ZIEL=out/ton-final-ohne-stimme.wav ;;
    --drums)       V_DRUMS=0.55 ;;
  esac
done

for f in out/scratch-vo.wav out/music.wav out/sfx.wav out/drums.wav; do
  [ -f "$f" ] || { echo "$f fehlt — sounddesign.py und musik.py laufen lassen."; exit 1; }
done

"$FF" -hide_banner -loglevel error -y \
  -i out/scratch-vo.wav -i out/music.wav -i out/sfx.wav -i out/drums.wav \
  -filter_complex "\
    [0:a]aresample=48000,volume=$V_STIMME,asplit=2[vo][vk]; \
    [1:a]aresample=48000,volume=0.38[mu]; \
    [2:a]aresample=48000,volume=0.34[fx]; \
    [3:a]aresample=48000,volume=$V_DRUMS[dr]; \
    [mu][vk]sidechaincompress=threshold=0.05:ratio=6:attack=8:release=260[mud]; \
    [mud][fx][dr][vo]amix=inputs=4:normalize=0, \
      equalizer=f=45:t=q:w=0.8:g=3.5, \
      equalizer=f=175:t=q:w=1.2:g=$G175, \
      treble=f=7000:g=2.5, \
      acompressor=threshold=-20dB:ratio=$KOMP:attack=6:release=180:makeup=3, \
      loudnorm=I=-17:TP=-1.9:LRA=$LRA,alimiter=limit=0.94[out]" \
  -map "[out]" -c:a pcm_s16le -ar 48000 -ac 2 "$ZIEL"

echo "$ZIEL"
"$FF" -hide_banner -i "$ZIEL" -af ebur128=peak=true -f null - 2>&1 \
  | grep -A1 -E "Integrated|Loudness range" | grep -E "I:|LRA:"
