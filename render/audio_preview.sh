#!/bin/sh
# Hoermix aus den unabhaengigen Original-Stems bauen.
# Bild, Szenenlaengen und Animation werden nicht veraendert.
set -eu

cd "$(dirname "$0")/.."
FF=${FFMPEG:-ffmpeg}

MUSIC=${MUSIC:-out/music-original.wav}
SFX=${SFX:-out/sfx-original.wav}
WAV=${PREVIEW_WAV:-out/audio-rework-preview.wav}
M4A=${PREVIEW_M4A:-out/audio-rework-preview.m4a}
VIDEO_IN=${PREVIEW_VIDEO_IN:-out/NEXPT-Keynote-ANIMATIC-OHNE-STIMME.mp4}
VIDEO_OUT=${PREVIEW_VIDEO:-out/NEXPT-AUDIO-REWORK-PREVIEW.mp4}

for file in "$MUSIC" "$SFX"; do
  [ -f "$file" ] || { echo "$file fehlt" >&2; exit 1; }
done

# SFX oeffnen bei einem Akzent kurz Platz in der Musik. Die Stems selbst
# bleiben unveraendert; Ducking und Loudness gelten nur fuer diesen Hoermix.
"$FF" -hide_banner -loglevel error -y \
  -i "$MUSIC" -i "$SFX" \
  -filter_complex "\
    [1:a]asplit=2[effects][key]; \
    [0:a][key]sidechaincompress=threshold=0.025:ratio=3.0:attack=6:release=180[ducked]; \
    [ducked][effects]amix=inputs=2:normalize=0,\
      highpass=f=28,alimiter=limit=0.96:level=false,\
      loudnorm=I=-16:TP=-1.0:LRA=9,alimiter=limit=0.84:level=false[out]" \
  -map "[out]" -ar 48000 -ac 2 -c:a pcm_s24le "$WAV"

"$FF" -hide_banner -loglevel error -y -i "$WAV" \
  -c:a aac -b:a 256k "$M4A"

if [ -f "$VIDEO_IN" ]; then
  "$FF" -hide_banner -loglevel error -y -i "$VIDEO_IN" -i "$WAV" \
    -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 256k -shortest "$VIDEO_OUT"
  echo "$VIDEO_OUT"
fi

echo "$WAV"
echo "$M4A"
"$FF" -hide_banner -nostats -i "$WAV" -af ebur128=peak=true -f null - 2>&1 \
  | tail -n 15
