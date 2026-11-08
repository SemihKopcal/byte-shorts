#!/usr/bin/env bash
# BYTE paneli: sunucu kurulumu. SUNUCUDA calistirilir (kendi bilgisayarinda degil).
#
# Yerlesim:
#   /srv/www/byte/
#     app/       git deposu (kod). .env ve secrets/ panel/deploy icinde durur, git'e girmez.
#     backups/   panel yedeklerinin kopyalari
#
# Kullanim:
#   sudo mkdir -p /srv/www/byte && sudo chown "$USER": /srv/www/byte && sudo chmod 700 /srv/www/byte
#   git clone https://github.com/SemihKopcal/byte-shorts.git /srv/www/byte/app
#   bash /srv/www/byte/app/panel/deploy/server-setup.sh
#
# Tekrar calistirmak guvenli: var olan .env ve secret dosyalarina dokunmaz, eksikleri sorar.
# Sirlar yalniz terminalden, ekranda gorunmeden alinir ve dogrudan dosyaya yazilir;
# ekrana, komut gecmisine ya da log'a dusmez. Bu script sirri hicbir yere yazdirmaz.
set -euo pipefail
umask 077

say() { printf '%s\n' "$*"; }
die() { printf 'HATA: %s\n' "$*" >&2; exit 1; }

DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_DIR=$(cd "$DEPLOY_DIR/../.." && pwd)
BASE_DIR=$(dirname "$APP_DIR")
SECRETS=$DEPLOY_DIR/secrets
ENV_FILE=$DEPLOY_DIR/.env

[[ -f $DEPLOY_DIR/docker-compose.yml && -f $DEPLOY_DIR/.env.example ]] \
  || die "docker-compose.yml / .env.example bulunamadi: bu script panel/deploy icinde olmali"
for c in git openssl docker; do
  command -v "$c" >/dev/null 2>&1 || die "'$c' kurulu degil"
done

if [[ $EUID -eq 0 ]]; then SUDO=(); else SUDO=(sudo); fi
DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  "${SUDO[@]}" docker info >/dev/null 2>&1 || die "docker calismiyor (servis kapali ya da yetki yok)"
  DOCKER=("${SUDO[@]}" docker)
fi
"${DOCKER[@]}" compose version >/dev/null 2>&1 || die "Docker Compose v2 gerekli ('docker compose version' calismiyor)"

say "Kod:      $APP_DIR"
say "Ayarlar:  $DEPLOY_DIR  (.env ve secrets/ burada, git'e girmez)"
case $APP_DIR in /srv/www/*) ;; *) say "Not: kod /srv/www altinda degil; sorun degil, yerlesim yine de calisir." ;; esac
mkdir -p "$BASE_DIR/backups" "$SECRETS"
chmod 700 "$SECRETS"

# ---------------------------------------------------------------- .env (sir yok)
V=""   # ask'in sonucu
ask() {   # ask "Soru" "varsayilan" "regex" "hata mesaji"
  local q=$1 def=$2 re=$3 err=$4 v
  while true; do
    if [[ -n $def ]]; then read -r -p "$q [$def]: " v; v=${v:-$def}; else read -r -p "$q: " v; fi
    if [[ $v =~ $re ]]; then V=$v; return; fi
    say "  -> $err"
  done
}

declare -A VAL
if [[ -s $ENV_FILE ]]; then
  # Elle yazilmis ya da baska yerden kopyalanmis .env olabilir: eksiksiz ve sirsiz mi?
  chmod 600 "$ENV_FILE"
  bad=0
  while IFS= read -r line; do
    [[ $line =~ ^[[:space:]]*([A-Z0-9_]+)= ]] || continue
    key=${BASH_REMATCH[1]}
    val=$(grep -m1 "^$key=" "$ENV_FILE" | cut -d= -f2- || true)
    if [[ -z ${val//[[:space:]]/} ]]; then say "  ! .env'de $key yok ya da bos"; bad=1; fi
  done < "$DEPLOY_DIR/.env.example"
  # Sirlar .env'e girmez: compose .env'i konteynerin ortam degiskenlerine koyar (docker inspect'te gorunur).
  while IFS= read -r key; do
    say "  ! .env'de sir var: $key. Satiri sil; sirlar secrets/ dosyalarina bu script ile girilir"; bad=1
  done < <(grep -Eo '^(R2_ACCESS_KEY_ID|R2_SECRET_ACCESS_KEY|GITHUB_TOKEN|TUNNEL_TOKEN|PANEL_CSRF_SECRET)=' "$ENV_FILE" | tr -d '=' || true)
  [[ $bad -eq 0 ]] || die ".env duzeltilmeden devam edilmez ($ENV_FILE)"
  say ".env var ve eksiksiz, korundu."
else
  say ""
  say "Ayarlar (bunlar sir degil):"
  ask "R2 adresi (S3 API adresi, SONUNDA bucket adi YOK)" "" \
      '^https://[0-9a-f]{32}(\.(eu|fedramp))?\.r2\.cloudflarestorage\.com$' \
      "https://<32 haneli hesap kimligi>.r2.cloudflarestorage.com bicimi olmali; sonda /bucket-adi olmamali"
  VAL[R2_ENDPOINT]=$V
  ask "R2 bucket adi" "byte-videos" '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$' "kucuk harf, rakam ve tire"
  VAL[R2_BUCKET]=$V
  ask "Panel adresi" "https://byte.semihkopcal.com" '^https://[A-Za-z0-9.-]+$' "https://alan.adi bicimi olmali, sonda / olmadan"
  VAL[PANEL_ORIGIN]=$V
  ask "GitHub deposu" "SemihKopcal/byte-shorts" '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' "sahip/depo bicimi olmali"
  VAL[GITHUB_REPO]=$V
  ask "Cloudflare Access takim alan adi (<takim>.cloudflareaccess.com)" "" \
      '^[A-Za-z0-9-]+\.cloudflareaccess\.com$' "<takim>.cloudflareaccess.com bicimi olmali"
  VAL[CF_ACCESS_TEAM_DOMAIN]=${V,,}
  ask "Access uygulamasinin AUD etiketi" "" '^[A-Za-z0-9]{32,128}$' "Access uygulamasindaki 'Application Audience (AUD) Tag' (harf-rakam, 32+ karakter)"
  VAL[CF_ACCESS_AUD]=$V
  ask "Panele girebilecek e-posta (birden cok ise virgulle)" "" \
      '^[^@ ,]+@[^@ ,]+\.[^@ ,]+(,[^@ ,]+@[^@ ,]+\.[^@ ,]+)*$' "gecerli e-posta adresi yaz"
  VAL[PANEL_ALLOWED_EMAILS]=${V,,}
  ask "cloudflared surum etiketi (github.com/cloudflare/cloudflared/releases)" "" \
      '^[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}$' "YYYY.M.P bicimi olmali, ornek 2026.1.0"
  VAL[CLOUDFLARED_TAG]=$V

  tmp=$ENV_FILE.tmp
  {
    say "# BYTE paneli ayarlari. SIR YOK; sirlar secrets/ klasorunde. server-setup.sh yazdi."
    # Anahtar listesi .env.example'dan gelir: orada yeni anahtar eklenirse script sessizce eksik birakmaz.
    while IFS= read -r line; do
      [[ $line =~ ^[[:space:]]*([A-Z0-9_]+)= ]] || continue
      key=${BASH_REMATCH[1]}
      [[ -n ${VAL[$key]+x} ]] || { rm -f "$tmp"; die ".env.example'da '$key' var ama script bunu sormuyor; scripti guncelle"; }
      printf '%s=%s\n' "$key" "${VAL[$key]}"
    done < "$DEPLOY_DIR/.env.example"
  } > "$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  say ".env yazildi."
fi

# ---------------------------------------------------------------- sirlar
put_secret() {   # put_secret dosya "Soru" "yazim bicimi" "beklenen onek (uyari icin, bos olabilir)"
  local f=$SECRETS/$1 v prefix=$4
  if [[ -s $f ]]; then say "secrets/$1 var, korundu."; return; fi
  while true; do
    read -rs -p "$2: " v; echo
    if [[ -n $v && $v != *[[:space:]]* && ${#v} -ge 16 ]]; then break; fi
    say "  -> bos, bosluklu ya da cok kisa; tekrar yaz"
  done
  if [[ -n $prefix && $v != "$prefix"* ]]; then
    say "  ! '$prefix' ile baslamiyor; yine de kaydediyorum. Sonra hata alirsan bu anahtarin dogru olup olmadigina bak."
  fi
  # shellcheck disable=SC2059   # bicim bizim sabitimiz, sir degil
  printf "$3" "$v" > "$f"
  v=""
}

say ""
say "Sirlar (yazarken ekranda gorunmez; sohbete yapistirma):"
put_secret r2_access_key_id     "R2 Access Key ID (byte-panel token'i)"        '%s'                 ""
put_secret r2_secret_access_key "R2 Secret Access Key (byte-panel token'i)"    '%s'                 ""
put_secret github_token         "GitHub fine-grained token (panel icin)"       '%s'                 "github_pat_"
put_secret tunnel.env           "Cloudflare tunel token'i"                     'TUNNEL_TOKEN=%s\n'  "eyJ"
if [[ ! -s $SECRETS/csrf_secret ]]; then
  openssl rand -hex 32 | tr -d '\n' > "$SECRETS/csrf_secret"
  say "secrets/csrf_secret rastgele uretildi."
fi

# Panel konteyneri 10001 kullanicisiyla okur: yalniz o (ve root) okuyabilsin.
# Sira onemli: once chmod (dosya hala bizim), sonra chown.
for f in r2_access_key_id r2_secret_access_key github_token csrf_secret; do
  "${SUDO[@]}" chmod 400 "$SECRETS/$f"
  "${SUDO[@]}" chown 10001:10001 "$SECRETS/$f"
done
chmod 600 "$SECRETS/tunnel.env"

# ---------------------------------------------------------------- dogrula ve baslat
cd "$DEPLOY_DIR"
"${DOCKER[@]}" compose config -q || die "docker compose ayarlari gecersiz (yukaridaki hataya bak)"
say ""
say "Ayarlar tamam."
read -r -p "Paneli simdi baslatayim mi? [E/h]: " go
if [[ ${go:-E} =~ ^[hHnN] ]]; then
  say "Baslatmadim. Hazir oldugunda: cd $DEPLOY_DIR && docker compose up -d --build"
else
  "${DOCKER[@]}" compose up -d --build
  cid=$("${DOCKER[@]}" compose ps -q panel)
  st=""
  for _ in $(seq 1 30); do
    st=$("${DOCKER[@]}" inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)
    [[ $st == healthy ]] && break
    sleep 5
  done
  "${DOCKER[@]}" compose ps
  if [[ $st == healthy ]]; then
    say "Panel saglikli."
  else
    say "Panel 2.5 dakikada 'healthy' olmadi (durum: ${st:-bilinmiyor}). Bak: cd $DEPLOY_DIR && docker compose logs panel"
  fi
fi

cat <<EOF

Sonraki adimlar:
  1) README'deki "Dogrulama" bolumunu yap (disariya acik port yok, adres Access girisine gidiyor).
  2) Gunluk yedek icin crontab -e:
       0 3 * * * cd $DEPLOY_DIR && docker compose exec -T panel python -m bytepanel.backup
  3) Guncelleme: cd $APP_DIR && git pull --ff-only && cd panel/deploy && docker compose up -d --build
  4) Panel calisirken GitHub'da PANEL_MODE=on yap (ondan once yapma).
EOF
