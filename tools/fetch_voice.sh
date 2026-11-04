#!/usr/bin/env bash
# Piper ses modelini indirir (~120 MB). Repoya KOYMUYORUZ: GitHub'in 100 MB
# dosya siniri ve git gecmisinin sisme problemi. Actions'ta cache'leniyor.
set -euo pipefail

VOICE="${1:-en-us-ryan-high}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/voices"
BASE="https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-${VOICE}.tar.gz"

mkdir -p "$DIR"
if [ -f "$DIR/${VOICE}.onnx" ]; then
  echo "zaten var: $DIR/${VOICE}.onnx"
  exit 0
fi

echo "indiriliyor: $VOICE"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$BASE" -o "$tmp/v.tar.gz"
tar -xzf "$tmp/v.tar.gz" -C "$tmp"

# Arsiv duzeni surumden surume degisiyor; dosyayi adiyla bul.
find "$tmp" -name '*.onnx'      -exec cp {} "$DIR/${VOICE}.onnx" \;
find "$tmp" -name '*.onnx.json' -exec cp {} "$DIR/${VOICE}.onnx.json" \;

test -f "$DIR/${VOICE}.onnx" || { echo "model cikmadi" >&2; exit 1; }
ls -la "$DIR"
