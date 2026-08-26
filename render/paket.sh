#!/bin/sh
# Baut das Download-Paket: Film, Timeline, Tonspur, Standbilder, Quellen.
# Ohne die ProRes-Master (495 MB) und die Stimmmodelle (200 MB) — beide
# reproduzierbar mit render.py bzw. voices/get-voices.sh.
cd "$(dirname "$0")/.." || exit 1
rm -f out/NEXPT-Keynote-Paket.zip
zip -q -r out/NEXPT-Keynote-Paket.zip \
  out/NEXPT-Keynote-ANIMATIC-SCRATCH.mp4 out/NEXPT-Keynote-ANIMATIC.mp4 \
  out/NEXPT-Keynote.fcpxml out/scratch-vo.wav out/stills \
  render KEYNOTE-FILM-KONZEPT.md README.md \
  -x "render/voices/*.onnx" "render/fonts/*"
ls -lh out/NEXPT-Keynote-Paket.zip
