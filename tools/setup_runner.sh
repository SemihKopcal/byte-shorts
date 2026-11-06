#!/usr/bin/env bash
# Runner'i hazirla: ffmpeg + ffprobe + Inter fontlari.
#
# NEDEN apt DEGIL: ubuntu-latest runner'inin apt aynasi (azure.archive.
# ubuntu.com) bazi gunler 50 KB/s'ye dusuyor. ffmpeg + 89 bagimliligi
# 129 MB ve bir kosu 40 dakikalik zaman asimina takilip iptal oldu.
# Ayni dosyalar GitHub release'lerinden 15 saniyede geliyor -- GitHub'dan
# GitHub'a indirme hem hizli hem de ucuncu bir servise bagimli degil.
#
# apt sadece CJK fontu icin kaliyor, o da sadece Japonca/Cince glif
# iceren senaryolarda.
#
# Idempotent: ikili zaten varsa indirmiyor, yani actions/cache ile birlikte
# ikinci kosudan itibaren hic indirme olmuyor.
set -euo pipefail

# GitHub runner'i x86_64; Apple Silicon uzerindeki Linux VM'i arm64. Mimariyi
# sabit yazmak "cannot execute binary file" ile bitiyor, o yuzden soruyoruz.
case "$(uname -m)" in
  x86_64|amd64) FF_ARCH="linux64" ;;
  aarch64|arm64) FF_ARCH="linuxarm64" ;;
  *) echo "desteklenmeyen mimari: $(uname -m)" >&2; exit 1 ;;
esac
FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-${FF_ARCH}-gpl.tar.xz"
INTER_URL="https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip"

BIN="${RUNNER_BIN:-$HOME/.local/bin}"
FONTS="${RUNNER_FONTS:-$HOME/.local/share/fonts/inter}"
mkdir -p "$BIN" "$FONTS"

# ── ffmpeg / ffprobe ──
if [ -x "$BIN/ffmpeg" ] && [ -x "$BIN/ffprobe" ]; then
  echo "ffmpeg zaten var, atlaniyor"
else
  echo "ffmpeg indiriliyor..."
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  curl -fsSL --retry 3 --retry-delay 2 "$FFMPEG_URL" -o "$tmp/f.tar.xz"
  tar -xJf "$tmp/f.tar.xz" -C "$tmp"
  # Arsiv kokundeki dizin adi surume gore degisiyor; adiyla bul.
  find "$tmp" -type f -name ffmpeg  -perm -u+x -exec cp {} "$BIN/ffmpeg"  \;
  find "$tmp" -type f -name ffprobe -perm -u+x -exec cp {} "$BIN/ffprobe" \;
  chmod +x "$BIN/ffmpeg" "$BIN/ffprobe"
fi

# ── Inter ──
# draw.py BU bes dosyayi ariyor. Eksikse sessizce baska fonta dusmek yerine
# hata firlatiyor, o yuzden burada da eksiksiz olmasini garanti ediyoruz.
NEED="Inter-Regular.otf Inter-Medium.otf Inter-SemiBold.otf
      InterDisplay-Bold.otf InterDisplay-Black.otf"
missing=0
for f in $NEED; do [ -f "$FONTS/$f" ] || missing=1; done

if [ "$missing" = "0" ]; then
  echo "Inter zaten var, atlaniyor"
else
  echo "Inter indiriliyor..."
  tmp2="$(mktemp -d)"
  curl -fsSL --retry 3 --retry-delay 2 "$INTER_URL" -o "$tmp2/i.zip"
  unzip -qo "$tmp2/i.zip" 'extras/otf/*' -d "$tmp2"
  for f in $NEED; do cp "$tmp2/extras/otf/$f" "$FONTS/$f"; done
  rm -rf "$tmp2"
fi

# ── Japonca (CJK) ──
# apt'taki fonts-noto-cjk hem 60 MB hem de dosya adi surume gore degisiyor;
# Ubuntu 24.04'te adi degisince "CJK fontu yok" diye patlamistik. Bu tek
# dosya 9.6 MB, adi sabit, 7 saniyede iniyor.
CJK="${RUNNER_CJK:-$HOME/.local/share/fonts/cjk}"
mkdir -p "$CJK"
if [ -f "$CJK/NotoSansJP.ttf" ]; then
  echo "CJK fontu zaten var, atlaniyor"
else
  echo "CJK fontu indiriliyor..."
  curl -fsSL --retry 3 --retry-delay 2 \
    "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf" \
    -o "$CJK/NotoSansJP.ttf"
fi

fc-cache -f "$FONTS" "$CJK" >/dev/null 2>&1 || true

# ── dogrula ──
echo "PATH'e ekleniyor: $BIN"
[ -n "${GITHUB_PATH:-}" ] && echo "$BIN" >> "$GITHUB_PATH"
export PATH="$BIN:$PATH"

"$BIN/ffmpeg"  -version | head -1
"$BIN/ffprobe" -version | head -1
for f in $NEED; do
  [ -f "$FONTS/$f" ] || { echo "EKSIK FONT: $f" >&2; exit 1; }
done
[ -f "$CJK/NotoSansJP.ttf" ] || { echo "EKSIK: CJK fontu" >&2; exit 1; }
echo "fontlar tamam ($(ls "$FONTS" | wc -l) Inter + CJK)"
