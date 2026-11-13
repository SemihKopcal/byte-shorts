"""
Instagram Reels'e otomatik yayin. Iki token turu desteklenir:

  * Instagram kullanici token'i ("IGAA...", Instagram Login, 60 gun): graph.instagram.com
  * Facebook-tarzi token ("EAA...", Meta'nin yeni uygulamalarda verdigi "Unified login" /
    sistem-kullanici token'i): graph.facebook.com. Sureli olmayabilir; yenilenmez.

Tur token'in basindan anlasilir (IG_HOST=instagram|facebook ile zorlanir).

    python publish/instagram.py out/<id>/manifest.json --video-url https://...
    python publish/instagram.py --check              # token calisiyor mu
    python publish/instagram.py --refresh --out f    # IGAA token'i 60 gun daha uzat
                                                     # (EAA token: cikis kodu 3, yapilacak is yok)

Akis (resmi dokuman): 1) REELS container olustur (video_url PUBLIC olmali,
Meta videoyu oradan ceker) 2) status_code FINISHED olana kadar bekle
3) media_publish. Kendi hesabin icin uygulama incelemesi gerekmiyor
(Standard Access yeterli); hesap PROFESYONEL (Creator/Business) olmali.

Gerekli ortam: INSTAGRAM_USER_ID, INSTAGRAM_TOKEN. IGAA token'ini haftalik `tokens`
workflow'u yeniliyor. API surumu bos birakilirsa
Meta'nin en eski desteklenen surumu kullanilir (IG_API_VERSION ile sabitlenir).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from publish import ledger, net            # noqa: E402

HOST = "https://graph.instagram.com"
HOST_FB = "https://graph.facebook.com"
VERSION = os.environ.get("IG_API_VERSION", "").strip().strip("/")
MAX_CAPTION = 2200


class IGError(Exception):
    pass


class NoRefresh(IGError):
    """Bu token turu yenilenmez (Facebook-tarzi / sistem-kullanici token'i)."""


def is_fb_token(token: str) -> bool:
    """Facebook-tarzi token ("EAA...") graph.facebook.com ister; Instagram kullanici
    token'i ("IGAA...") graph.instagram.com. IG_HOST=facebook|instagram ile zorlanir."""
    forced = os.environ.get("IG_HOST", "").strip().lower()
    if forced in ("facebook", "instagram"):
        return forced == "facebook"
    return str(token).startswith("EAA")


def _url(path: str, token: str = "") -> str:
    host = HOST_FB if is_fb_token(token) else HOST
    return f"{host}/{VERSION + '/' if VERSION else ''}{path}"


def check(token: str, http=net.request, *, user_id: str = "") -> dict:
    """{'user_id','username'} ya da IGError. Facebook-tarzi token'da INSTAGRAM_USER_ID gerekir
    (orada /me Instagram hesabini degil token sahibini dondurur); ayrica yayin izni okunarak
    sinanir (hicbir sey yayinlanmaz). Izin sorgusu cevap vermezse 'publish_note' doner."""
    if not is_fb_token(token):
        st, out = http("GET", _url("me", token) + f"?fields=user_id,username&access_token={token}")
        if st != 200 or "username" not in out:
            raise IGError(f"token gecersiz (HTTP {st}): {net.err_text(out)}")
        return out
    if not user_id:
        raise IGError("Facebook-tarzi token icin INSTAGRAM_USER_ID gerekli")
    st, out = http("GET", _url(user_id, token) + f"?fields=username&access_token={token}")
    if st != 200 or not isinstance(out, dict) or "username" not in out:
        raise IGError(f"token gecersiz (HTTP {st}): {net.err_text(out)}")
    res = {"user_id": out.get("id", user_id), "username": out["username"]}
    st, out = http("GET", _url(f"{user_id}/content_publishing_limit", token)
                   + f"?fields=quota_usage,config&access_token={token}")
    if st != 200:
        res["publish_note"] = (f"yayin izni dogrulanamadi (HTTP {st}): {net.err_text(out)}; "
                               "token'da instagram_content_publish var mi?")
    return res


def publish_reel(video_url: str, caption: str, *, user_id: str, token: str,
                 http=net.request, sleep=time.sleep, poll_every: float = 15,
                 max_wait: float = 600, log=print) -> dict:
    """Reels'i yayinlar. {'media_id','permalink'} doner; sorunda IGError."""
    if len(caption) > MAX_CAPTION:
        raise IGError(f"aciklama {len(caption)} karakter; en fazla {MAX_CAPTION}")
    st, out = http("POST", _url(f"{user_id}/media", token), form={
        "media_type": "REELS", "video_url": video_url, "caption": caption,
        "share_to_feed": "true", "access_token": token})
    cid = out.get("id") if isinstance(out, dict) else None
    if st != 200 or not cid:
        raise IGError(f"container olusmadi (HTTP {st}): {net.err_text(out)}")
    log(f"  instagram: container {cid}, Meta videoyu indiriyor...")

    waited = 0.0
    while True:
        st, out = http("GET", _url(cid, token) + f"?fields=status_code,status&access_token={token}")
        code = out.get("status_code") if isinstance(out, dict) else None
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise IGError(f"Meta videoyu isleyemedi ({code}): "
                          f"{out.get('status', '')}. video_url herkese acik ve "
                          f"dogrudan indirilebilir mi? {video_url}")
        if st not in (200, 0) and st < 500:
            raise IGError(f"durum sorgusu basarisiz (HTTP {st}): {net.err_text(out)}")
        if waited >= max_wait:
            raise IGError(f"{max_wait:.0f} sn icinde hazir olmadi (son durum: {code})")
        sleep(poll_every)
        waited += poll_every

    st, out = http("POST", _url(f"{user_id}/media_publish", token),
                   form={"creation_id": cid, "access_token": token})
    mid = out.get("id") if isinstance(out, dict) else None
    if st != 200 or not mid:
        raise IGError(f"yayinlanamadi (HTTP {st}): {net.err_text(out)}")
    permalink = ""
    st, out = http("GET", _url(mid, token) + f"?fields=permalink&access_token={token}")
    if st == 200 and isinstance(out, dict):
        permalink = out.get("permalink", "")
    return {"media_id": mid, "permalink": permalink}


def refresh(token: str, http=net.request) -> tuple[str, int]:
    """(yeni_token, saniye). Token en az 24 saat eski ve suresi dolmamis olmali.
    Facebook-tarzi token yenilenmez: NoRefresh."""
    if is_fb_token(token):
        raise NoRefresh("bu token turu (EAA...) yenilenmez; sureli degilse yapilacak is yok")
    st, out = http("GET", f"{HOST}/refresh_access_token?grant_type=ig_refresh_token"
                          f"&access_token={token}")
    new = out.get("access_token") if isinstance(out, dict) else None
    if st != 200 or not new:
        raise IGError(f"token yenilenemedi (HTTP {st}): {net.err_text(out)}")
    return new, int(out.get("expires_in", 0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", nargs="?")
    ap.add_argument("--video-url", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default="", help="--refresh: yeni token bu dosyaya yazilir")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    token = os.environ.get("INSTAGRAM_TOKEN", "").strip()
    user_id = os.environ.get("INSTAGRAM_USER_ID", "").strip()
    if not token:
        print("INSTAGRAM_TOKEN yok", file=sys.stderr)
        return 2
    try:
        if a.check:
            me = check(token, user_id=user_id)
            print(f"instagram tamam: @{me['username']} (id {me.get('user_id')})")
            if me.get("publish_note"):
                print(f"UYARI: {me['publish_note']}", file=sys.stderr)
            return 0
        if a.refresh:
            try:
                new, secs = refresh(token)
            except NoRefresh as e:
                print(f"instagram: {e}")
                return 3
            if a.out:
                p = Path(a.out)
                p.write_text(new)
                p.chmod(0o600)
            print(f"instagram token yenilendi, {secs // 86400} gun gecerli")
            return 0
        if not (a.manifest and a.video_url and user_id):
            print("kullanim: instagram.py manifest.json --video-url URL "
                  "(INSTAGRAM_USER_ID de gerekli)", file=sys.stderr)
            return 2
        man = json.loads(Path(a.manifest).read_text())
        vid = man["id"]
        caption = (man.get("captions") or {}).get("instagram", "")
        if not caption:
            raise IGError("manifest'te instagram aciklamasi yok")
        if ledger.done(vid, "instagram"):
            print(f"{vid} zaten Instagram'a gonderilmis; atlandi")
            return 0
        if a.dry_run:
            print(f"[dry-run] {vid}\n{caption}\n{a.video_url}")
            return 0
        res = publish_reel(a.video_url, caption, user_id=user_id, token=token)
        ledger.record(vid, "instagram", res)
        print(f"instagram yayinlandi: {res['permalink'] or res['media_id']}")
        return 0
    except IGError as e:
        print(f"INSTAGRAM HATASI: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
