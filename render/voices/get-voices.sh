#!/bin/sh
# Deutsche Piper-Stimmen laden (die .onnx-Modelle sind zu gross fuer git).
cd "$(dirname "$0")" || exit 1
B="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE"
for v in thorsten/high/de_DE-thorsten-high \
         eva_k/x_low/de_DE-eva_k-x_low \
         kerstin/low/de_DE-kerstin-low; do
  n=$(basename "$v")
  [ -f "$n.onnx" ] || curl -sSL -o "$n.onnx" "$B/$v.onnx"
  [ -f "$n.onnx.json" ] || curl -sSL -o "$n.onnx.json" "$B/$v.onnx.json"
  echo "  $n"
done
