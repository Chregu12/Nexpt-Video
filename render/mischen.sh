#!/bin/sh
# Endmischung: Stimme fuehrt, Musik und Effekte darunter.
# Pegel wie im Referenzfilm: -17 LUFS integriert, stark komprimiert (LRA ~4).
# Auf der Messe gegen Hallenlaerm - Dynamik ist hier keine Tugend.
cd "$(dirname "$0")/.." || exit 1
FF=${FFMPEG:-ffmpeg}
"$FF" -hide_banner -loglevel error -y \
  -i out/scratch-vo.wav -i out/music.wav -i out/sfx.wav \
  -filter_complex "\
    [0:a]aresample=48000,volume=1.0,asplit=2[vo][vk]; \
    [1:a]aresample=48000,volume=0.30[mu]; \
    [2:a]aresample=48000,volume=0.85[fx]; \
    [mu][vk]sidechaincompress=threshold=0.05:ratio=6:attack=8:release=260[mud]; \
    [mud][fx][vo]amix=inputs=3:normalize=0, \
      loudnorm=I=-17:TP=-1.9:LRA=5,alimiter=limit=0.94[out]" \
  -map "[out]" -c:a pcm_s16le -ar 48000 -ac 2 out/ton-final.wav
"$FF" -hide_banner -i out/ton-final.wav -af ebur128=peak=true -f null - 2>&1 \
  | grep -A1 -E "Integrated|Loudness range" | grep -E "I:|LRA:"
