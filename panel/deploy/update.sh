#!/usr/bin/env bash
# BYTE panelini SUNUCUDA guvenle guncelle.
#
#   cd /srv/www/byte/app/panel/deploy && ./update.sh        # onay sorar
#   ./update.sh -y                                          # onay sormaz (cron/otomasyon)
#
# Ne yapar (sirayla; biri bozulursa durur):
#   1. Yerel degisiklik yok, dal dogru mu, GitHub'daki surum bizimkinin DEVAMI mi (force-push
#      ya da ayrismis tarih varsa REDDEDER).
#   2. Ne degisecegini gosterir. `panel/` degismediyse (yalniz icerik/workflow) yeniden
#      derleme YAPMAZ: yalniz kodu ilerletir.
#   3. Panel veritabaninin yedegini alir (calisan konteynerde bytepanel.backup).
#   4. Calisan imaji `byte-panel:prev` olarak saklar, kodu ilerletir (yalniz fast-forward).
#   5. Derler, baslatir, konteynerin SAGLIKLI olmasini bekler.
#   6. Saglikli olmazsa kendiliginden GERI ALIR: eski commit + eski imaj.
#
# Sirlara (.env, secrets/) dokunmaz. Sunucuya DISARIDAN baglanti gerekmez: cekmeyi sen
# (ya da sunucudaki zamanlayici) baslatir.
#
# Ortam degiskenleri (hepsi istege bagli):
#   BYTE_BRANCH=main  BYTE_REMOTE=origin  BYTE_HEALTH_WAIT=90 (sn)  BYTE_POLL=3 (sn)
#   BYTE_PULL=1       derlerken taban imaji da cek (guvenlik yamalari icin ayda bir)
#   BYTE_SKIP_BACKUP=1  yedeksiz devam (onerilmez)
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(git -C "$DEPLOY_DIR" rev-parse --show-toplevel)"
BRANCH="${BYTE_BRANCH:-main}"
REMOTE="${BYTE_REMOTE:-origin}"
WAIT="${BYTE_HEALTH_WAIT:-90}"
POLL="${BYTE_POLL:-3}"
IMAGE="byte-panel:local"
PREV="byte-panel:prev"

YES=0
case "${1:-}" in
  -y|--yes) YES=1 ;;
  "") ;;
  *) echo "kullanim: $0 [-y]" >&2; exit 2 ;;
esac

say() { printf '%s\n' "$*"; }
die() { printf 'HATA: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null || die "git yok"
command -v docker >/dev/null || die "docker yok"
cd "$APP_DIR"

# ── 1. on kosullar ────────────────────────────────────────────────────────────
cur="$(git symbolic-ref --short -q HEAD || true)"
[[ "$cur" == "$BRANCH" ]] || die "su an '$cur' dalindasin, '$BRANCH' olmali (git switch $BRANCH)"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] \
  || die "sunucudaki kodda yerel degisiklik var; once bak: git -C $APP_DIR status"

git fetch --quiet "$REMOTE" "$BRANCH"
OLD="$(git rev-parse HEAD)"
NEW="$(git rev-parse "$REMOTE/$BRANCH")"
if [[ "$OLD" == "$NEW" ]]; then say "Zaten guncel ($(git rev-parse --short HEAD))."; exit 0; fi
git merge-base --is-ancestor "$OLD" "$NEW" \
  || die "GitHub'daki tarih bizimkinin devami degil (force-push ya da ayrisma). Elle incele, otomatik gecmiyorum."

# ── 2. ne degisiyor ───────────────────────────────────────────────────────────
say "Degisecek commit'ler ($(git rev-parse --short "$OLD") -> $(git rev-parse --short "$NEW")):"
git log --oneline "$OLD..$NEW" | head -30
if git diff --quiet "$OLD" "$NEW" -- panel; then
  git merge --ff-only --quiet "$NEW"
  say "panel/ degismedi: yeniden derleme gerekmiyor. Kod ilerletildi, panel oldugu gibi calisiyor."
  exit 0
fi
say; say "panel/ icinde degisenler:"
git diff --stat "$OLD" "$NEW" -- panel | tail -15

if [[ $YES -ne 1 ]]; then
  [[ -t 0 ]] || die "etkilesimsiz calisiyor; onay icin -y ver"
  read -r -p "Panel yeniden derlenip baslatilsin mi? [e/H] " ans
  [[ "$ans" == "e" || "$ans" == "E" ]] || { say "Iptal edildi."; exit 0; }
fi

cd "$DEPLOY_DIR"
dc() { docker compose "$@"; }

# ── 3. yedek ─────────────────────────────────────────────────────────────────
if [[ "${BYTE_SKIP_BACKUP:-0}" == "1" ]]; then
  say "Yedek atlandi (BYTE_SKIP_BACKUP=1)."
elif [[ -z "$(dc ps -q panel 2>/dev/null || true)" ]]; then
  say "Panel calismiyor; yedek alinacak bir sey yok."
else
  say "Veritabani yedegi aliniyor..."
  dc exec -T panel python -m bytepanel.backup || die "yedek alinamadi; hicbir sey degistirilmedi"
fi

# ── 4. eski imaji sakla, kodu ilerlet ─────────────────────────────────────────
HAVE_PREV=0
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker tag "$IMAGE" "$PREV"
  HAVE_PREV=1
fi
git -C "$APP_DIR" merge --ff-only --quiet "$NEW"

rollback() {
  say; say "GERI ALINIYOR: kod -> $(git -C "$APP_DIR" rev-parse --short "$OLD")"
  git -C "$APP_DIR" reset --hard --quiet "$OLD"
  if [[ $HAVE_PREV -eq 1 ]]; then
    docker tag "$PREV" "$IMAGE"
    dc up -d --no-build --force-recreate panel
    if wait_healthy; then say "Geri alma tamam: eski surum calisiyor."
    else say "UYARI: eski surum de saglikli gorunmuyor; 'docker compose logs panel' ile bak."; fi
  else
    say "Eski imaj yoktu (ilk kurulum); yalniz kod geri alindi."
  fi
}

wait_healthy() {
  local start=$SECONDS cid st
  while :; do
    cid="$(dc ps -q panel 2>/dev/null || true)"
    st="none"
    if [[ -n "$cid" ]]; then
      st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
    fi
    [[ "$st" == "healthy" ]] && return 0
    [[ "$st" == "unhealthy" ]] && return 1
    (( SECONDS - start >= WAIT )) && return 1
    sleep "$POLL"
  done
}

# ── 5. derle, baslat, bekle ──────────────────────────────────────────────────
build_args=(build)
[[ "${BYTE_PULL:-0}" == "1" ]] && build_args+=(--pull)
say; say "Derleniyor..."
if ! dc "${build_args[@]}"; then
  say "Derleme basarisiz; calisan panele dokunulmadi."
  git -C "$APP_DIR" reset --hard --quiet "$OLD"
  exit 1
fi

say "Baslatiliyor..."
dc up -d
say "Saglik bekleniyor (en cok ${WAIT} sn)..."
if wait_healthy; then
  docker image prune -f >/dev/null 2>&1 || true
  say; say "TAMAM: panel $(git -C "$APP_DIR" rev-parse --short "$NEW") surumunde, saglikli."
  say "Sorun cikarsa geri donmek icin:  git -C $APP_DIR reset --hard $(git -C "$APP_DIR" rev-parse --short "$OLD") && docker tag $PREV $IMAGE && docker compose up -d --no-build --force-recreate panel"
  exit 0
fi

say "Panel saglikli olmadi."
rollback
exit 1
