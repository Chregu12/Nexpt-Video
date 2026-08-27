#!/bin/sh
# Endmischung. Zwei Fassungen, ein Schalter:
#
#     sh render/mischen.sh                  Stimme + Percussion + Effekte
#     sh render/mischen.sh --ohne-stimme    nur Percussion + Effekte
#
# Die Fassung ohne Stimme ist keine Notloesung, sondern die Standloop-Fassung:
# am Messestand laeuft der Film stumm mit Untertiteln, und dort stoert eine
# Scratchstimme mehr, als sie hilft. Sie ist ausserdem der ehrlichere Blick
# auf die Percussion — ohne Sprache davor hoert man, was die Trommeln tun.
#
# Pegel wie im Referenzfilm: -17 LUFS integriert, stark komprimiert (LRA ~4).
# Auf der Messe gegen Hallenlaerm ist Dynamik keine Tugend.
#
# Die Musikspur ist raus. Sie war eine getragene Flaeche und hat den Mix auf
# 147 BPM gezogen, obwohl die Percussion auf 118 laeuft — gemessen, nicht
# vermutet. Jetzt traegt die Percussion allein, und out/music.wav ist still.
# Was vorher die Flaeche im Bass gefuellt hat, macht jetzt die Marschtrommel.
cd "$(dirname "$0")/.." || exit 1
FF=${FFMPEG:-ffmpeg}

OHNE=0
for a in "$@"; do [ "$a" = "--ohne-stimme" ] && OHNE=1; done

if [ "$OHNE" = "1" ]; then
  # Ohne Stimme faellt zweierlei weg: das Ducking, weil nichts mehr duckt,
  # und die 175-Hz-Senke — die stand nur da, um die Grundtoene der Stimme
  # freizuraeumen. Ohne Stimme wuerde sie der Trommel den Bauch wegnehmen.
  # Die Percussion darf dafuer lauter stehen, sie traegt jetzt allein.
  ZIEL=out/ton-final-ohne-stimme.wav
  "$FF" -hide_banner -loglevel error -y \
    -i out/sfx.wav -i out/drums.wav \
    -filter_complex "\
      [0:a]aresample=48000,volume=0.40[fx]; \
      [1:a]aresample=48000,volume=1.0[dr]; \
      [dr][fx]amix=inputs=2:normalize=0, \
        equalizer=f=45:t=q:w=0.8:g=3.5, \
        treble=f=7000:g=2.5, \
        acompressor=threshold=-24dB:ratio=4:attack=6:release=180:makeup=3, \
        loudnorm=I=-17:TP=-1.9:LRA=5,alimiter=limit=0.94[out]" \
    -map "[out]" -c:a pcm_s16le -ar 48000 -ac 2 "$ZIEL"
else
  # Das Ducking sitzt auf dem Schlagzeug (frueher auf der Flaeche) und ist
  # milder gehalten (Ratio 3 statt 6): die Schlaege sollen die Schnitte
  # weiter treffen, nur leiser, wenn gesprochen wird.
  # Die 175-Hz-Senke naehert die Frequenzneigung an die gemessene des
  # Referenzfilms an. Bewusst moderat: Apple hat Sub und Bass gleichauf, bei
  # uns liegt der Bass hoeher, weil die Sprecherstimme ihre Grundtoene bei
  # 100-250 Hz hat.
  ZIEL=out/ton-final.wav
  "$FF" -hide_banner -loglevel error -y \
    -i out/scratch-vo.wav -i out/sfx.wav -i out/drums.wav \
    -filter_complex "\
      [0:a]aresample=48000,volume=1.0,asplit=2[vo][vk]; \
      [1:a]aresample=48000,volume=0.34[fx]; \
      [2:a]aresample=48000,volume=0.72[dr]; \
      [dr][vk]sidechaincompress=threshold=0.06:ratio=3:attack=12:release=300[drd]; \
      [drd][fx][vo]amix=inputs=3:normalize=0, \
        equalizer=f=45:t=q:w=0.8:g=3.5, \
        equalizer=f=175:t=q:w=1.2:g=-3.5, \
        treble=f=7000:g=2.5, \
        acompressor=threshold=-24dB:ratio=4:attack=6:release=180:makeup=3, \
        loudnorm=I=-17:TP=-1.9:LRA=5,alimiter=limit=0.94[out]" \
    -map "[out]" -c:a pcm_s16le -ar 48000 -ac 2 "$ZIEL"
fi

echo "$ZIEL"
"$FF" -hide_banner -i "$ZIEL" -af ebur128=peak=true -f null - 2>&1 \
  | grep -A1 -E "Integrated|Loudness range" | grep -E "I:|LRA:"
