#!/usr/bin/env bash
# Uretilen videoyu GitHub Release'e koyar.
#
# Neden: Actions artifact'i 2 gun yasiyor ve telefondan indirmesi zor. Release
# ise kalici bir adres: videoyu telefondan indirir, aciklamalari release notundan
# kopyalar, Instagram/TikTok'a elle yuklersin. Ileride Instagram API'nin
# ihtiyac duydugu PUBLIC video adresi de bu olacak (Meta videoyu bir URL'den
# ceker).
#
# Kullanim: GH_TOKEN=... bash tools/release.sh out/<id>
set -euo pipefail

dir="${1:?kullanim: release.sh out/<id>}"
id="$(basename "$dir")"
tag="v-${id}"
mp4="${dir}/${id}.mp4"

[ -f "$mp4" ] || { echo "video yok: $mp4" >&2; exit 1; }
title="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["title"])' "${dir}/manifest.json")"

# Ayni kosu yeniden calisirsa etiket zaten vardir
gh release delete "$tag" --cleanup-tag --yes >/dev/null 2>&1 || true
gh release create "$tag" "$mp4" "${dir}/captions.md" \
  --title "$title" --notes-file "${dir}/captions.md" --latest
echo "release: $tag"

# 14 gunden eski v-* release'lerini sil: sinirsiz birikmesin
cutoff="$(date -u -d '14 days ago' +%Y-%m-%dT%H:%M:%SZ)"
gh release list --limit 200 --json tagName,createdAt \
  --jq ".[] | select((.tagName | startswith(\"v-\")) and .createdAt < \"${cutoff}\") | .tagName" |
while read -r old; do
  [ -n "$old" ] && gh release delete "$old" --cleanup-tag --yes || true
done
