#!/usr/bin/env bash
# Videoyu herkese acik bir adrese koyar. Instagram videoyu bir URL'den ceker
# (dosya yukletmiyor), o URL'nin dogrudan indirilebilir ve herkese acik
# olmasi gerekiyor. GitHub Release adresleri baska bir host'a yonleniyor;
# Meta'nin bunu izleyip izlemedigi belgelenmemis. GitHub Pages ise videoyu
# dogrudan, video/mp4 olarak sunuyor.
#
# Nasil: `media` dali (Pages bu dali yayinliyor). Her kosuda TEK commit'e
# ezilip force push edilir, son MEDIA_KEEP (8) video kalir: repo sismez.
#
#   GH_TOKEN=... GITHUB_REPOSITORY=sahip/depo bash tools/host_video.sh out/<id>
#   bash tools/host_video.sh --init        # bos `media` dalini kurar (bir kere)
#
# Son satira (stdout) adresi yazar; mesajlar stderr'e gider.
set -euo pipefail

repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY yok}"
: "${GH_TOKEN:?GH_TOKEN yok}"
owner="${repo%%/*}"; name="${repo##*/}"
base="https://$(printf '%s' "$owner" | tr 'A-Z' 'a-z').github.io/${name}"
keep="${MEDIA_KEEP:-8}"
src="${1:?kullanim: host_video.sh out/<id> | --init}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
here="$(pwd)"

git init -q "$work"
cd "$work"
git remote add origin "https://x-access-token:${GH_TOKEN}@github.com/${repo}.git"
if git fetch -q --depth 1 origin media 2>/dev/null; then
  git checkout -q -b media FETCH_HEAD
else
  git checkout -q --orphan media
fi
touch .nojekyll
[ -f index.html ] || echo '<!doctype html><title>BYTE media</title><p>BYTE media</p>' > index.html

if [ "$src" != "--init" ]; then
  id="$(basename "$src")"
  mp4="${here}/${src}/${id}.mp4"
  [ -f "$mp4" ] || { echo "video yok: $mp4" >&2; exit 1; }
  cp "$mp4" "./${id}.mp4"
  # adlar tarihle basliyor: siralayip en yenilerden $keep tanesini tut
  ls -1 ./*.mp4 | sort | head -n "-${keep}" | xargs -r rm -f
fi

git add -A
git checkout -q --orphan flat
git -c user.name=byte-bot -c user.email=byte-bot@users.noreply.github.com \
    commit -q -m "media: ${src##*/}"
git push -q -f origin flat:media
echo "media dali guncellendi" >&2

if [ "$src" = "--init" ]; then
  echo "tamam: simdi Settings > Pages > Source: Deploy from a branch > media / (root)" >&2
  exit 0
fi

url="${base}/${id}.mp4"
echo "Pages'in yayinlamasi bekleniyor: $url" >&2
for i in $(seq 1 45); do
  code="$(curl -s -L -D "$work/h" -o /dev/null -w '%{http_code}' "$url" || true)"
  ct="$(grep -i '^content-type:' "$work/h" 2>/dev/null | tail -1 | tr -d '\r' || true)"
  if [ "$code" = "200" ] && printf '%s' "$ct" | grep -qi 'video'; then
    echo "hazir (${i}. deneme)" >&2
    echo "$url"
    exit 0
  fi
  sleep 10
done
echo "adres 450 sn icinde gelmedi (son HTTP $code). Settings > Pages kaynagi 'media' dali mi?" >&2
exit 1
