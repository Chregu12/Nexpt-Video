#!/bin/sh
# Baut das Download-Paket: Film, Timeline, Tonspur, Standbilder, Quellen.
# Ohne die ProRes-Master (495 MB), die Stimmmodelle (200 MB) und die
# Whisper-Modelle (800 MB) — alle drei reproduzierbar mit render.py,
# voices/get-voices.sh bzw. asr/get-modelle.sh. Das Whisper-Modell hat hier
# einmal gefehlt und das Paket auf 674 MB aufgeblasen.
cd "$(dirname "$0")/.." || exit 1
rm -f out/NEXPT-Keynote-Paket.zip
zip -q -r out/NEXPT-Keynote-Paket.zip \
  out/NEXPT-Keynote-ANIMATIC-SCRATCH.mp4 out/NEXPT-Keynote-ANIMATIC.mp4 \
  out/NEXPT-Keynote.fcpxml out/scratch-vo.wav out/stills \
  render KEYNOTE-FILM-KONZEPT.md README.md \
  -x "render/voices/*.onnx" "render/fonts/*" "render/asr/whisper-*/*"
ls -lh out/NEXPT-Keynote-Paket.zip
