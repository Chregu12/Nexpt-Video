#!/bin/sh
# Deutsche / schweizerdeutsche Whisper-Modelle nach CTranslate2 wandeln.
# Nur fuer sync.py noetig — sie ERKENNEN Sprache, sie erzeugen keine.
#   sh get-modelle.sh de     whisper-large-v3-turbo-german   (~780 MB, empfohlen)
#   sh get-modelle.sh de-l   whisper-large-v3-german         (~1.5 GB, staerker)
#   sh get-modelle.sh ch     flix-swissgerman-full           (fuer Schweizerdeutsch)
cd "$(dirname "$0")" || exit 1
case "${1:-de}" in
  de)   REPO=primeline/whisper-large-v3-turbo-german; DIR=whisper-de-turbo ;;
  de-l) REPO=primeline/whisper-large-v3-german;       DIR=whisper-de-large ;;
  ch)   REPO=Flix-AI/flix-swissgerman-full;           DIR=whisper-ch ;;
  *) echo "unbekannt: $1"; exit 1 ;;
esac
[ -d "$DIR" ] && { echo "$DIR liegt schon da"; exit 0; }
ct2-transformers-converter --model "$REPO" --output_dir "$DIR" \
  --copy_files preprocessor_config.json --quantization int8 || exit 1
python3 - "$REPO" "$DIR" <<'PY'
import sys
from transformers import WhisperTokenizerFast
WhisperTokenizerFast.from_pretrained(sys.argv[1]).save_pretrained(sys.argv[2])
PY
du -sh "$DIR"
