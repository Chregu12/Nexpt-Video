#!/bin/sh
# Baut das Download-Paket: Film, Timeline, Tonspur, Standbilder, Quellen.
# Ohne die ProRes-Master (495 MB), die Stimmmodelle (200 MB) und die
# Whisper-Modelle (800 MB) — alle drei reproduzierbar mit render.py,
# voices/get-voices.sh bzw. asr/get-modelle.sh. Das Whisper-Modell hat hier
# einmal gefehlt und das Paket auf 674 MB aufgeblasen.
cd "$(dirname "$0")/.." || exit 1

# Sind Audio-Stems vorhanden, muessen alle sieben vollständig und valide sein.
# Ein partieller Handoff wird nicht stillschweigend als fertiges Paket ausgegeben.
audio_count=0
for audio_file in \
  out/music-reference-low.wav out/music-reference-body.wav \
  out/music-reference-tonal.wav out/music-reference-detail.wav \
  out/sfx-impacts.wav out/sfx-motion.wav out/sfx-ui.wav
do
  [ -f "$audio_file" ] && audio_count=$((audio_count + 1))
done

if [ "$audio_count" -eq 0 ]; then
  python3 render/fcpxml.py || exit 1
elif [ "$audio_count" -eq 7 ]; then
  python3 render/fcpxml.py --audio-config render/final-cut-audio.json || exit 1
else
  echo "Audio-Handoff unvollständig: $audio_count von 7 Stems vorhanden." >&2
  exit 1
fi

set -- \
  out/NEXPT-Keynote-ANIMATIC-SCRATCH.mp4 out/NEXPT-Keynote-ANIMATIC.mp4 \
  out/NEXPT-Keynote-ANIMATIC-OHNE-STIMME.mp4 out/NEXPT-Keynote-ANIMATIC-OHNE-EFFEKTE.mp4 \
  out/analysis out/NEXPT-Keynote.fcpxml out/NEXPT-Keynote.fcpxml.manifest.json \
  out/scratch-vo.wav out/stills

if [ "$audio_count" -eq 7 ]; then
  set -- "$@" \
    out/music-reference-low.wav out/music-reference-body.wav \
    out/music-reference-tonal.wav out/music-reference-detail.wav \
    out/sfx-impacts.wav out/sfx-motion.wav out/sfx-ui.wav
fi

set -- "$@" render KEYNOTE-FILM-KONZEPT.md README.md
rm -f out/NEXPT-Keynote-Paket.zip
zip -q -r out/NEXPT-Keynote-Paket.zip "$@" \
  -x "render/voices/*.onnx" "render/fonts/*" "render/asr/whisper-*/*"
ls -lh out/NEXPT-Keynote-Paket.zip
