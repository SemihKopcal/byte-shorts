"""
Instagram Reels'e otomatik yayin ("Instagram API with Instagram Login").

    python publish/instagram.py out/<id>/manifest.json --video-url https://...
    python publish/instagram.py --check              # token calisiyor mu
    python publish/instagram.py --refresh --out f    # token'i 60 gun daha uzat

Akis (resmi dokuman): 1) REELS container olustur (video_url PUBLIC olmali,
Meta videoyu oradan ceker) 2) status_code FINISHED olana kadar bekle
3) media_publish. Kendi hesabin icin uygulama incelemesi gerekmiyor
(Standard Access yeterli); hesap PROFESYONEL (Creator/Business) olmali.

Gerekli ortam: INSTAGRAM_USER_ID, INSTAGRAM_TOKEN (uzun omurlu, 60 gun).
Token'i haftalik `tokens` workflow'u yeniliyor. API surumu bos birakilirsa
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
VERSION = os.environ.get("IG_API_VERSION", "").strip().strip("/")
MAX_CAPTION = 2200


class IGError(Exception):
    pass


def _url(path: str) -> str:
    return f"{HOST}/{VERSION + '/' if VERSION else ''}{path}"


def check(token: str, http=net.request) -> dict:
    """{'user_id','username'} ya da IGError."""
    st, out = http("GET", _url("me") + f"?fields=user_id,username&access_token={token}")
    if st != 200 or "username" not in out:
        raise IGError(f"token gecersiz (HTTP {st}): {net.err_text(out)}")
    return out


def publish_reel(video_url: str, caption: str, *, user_id: str, token: str,
                 http=net.request, sleep=time.sleep, poll_every: float = 15,
                 max_wait: float = 600, log=print) -> dict:
    """Reels'i yayinlar. {'media_id','permalink'} doner; sorunda IGError."""
    if len(caption) > MAX_CAPTION:
        raise IGError(f"aciklama {len(caption)} karakter; en fazla {MAX_CAPTION}")
    st, out = http("POST", _url(f"{user_id}/media"), form={
        "media_type": "REELS", "video_url": video_url, "caption": caption,
        "share_to_feed": "true", "access_token": token})
    cid = out.get("id") if isinstance(out, dict) else None
    if st != 200 or not cid:
        raise IGError(f"container olusmadi (HTTP {st}): {net.err_text(out)}")
    log(f"  instagram: container {cid}, Meta videoyu indiriyor...")

    waited = 0.0
    while True:
        st, out = http("GET", _url(cid) + f"?fields=status_code,status&access_token={token}")
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

    st, out = http("POST", _url(f"{user_id}/media_publish"),
                   form={"creation_id": cid, "access_token": token})
    mid = out.get("id") if isinstance(out, dict) else None
    if st != 200 or not mid:
        raise IGError(f"yayinlanamadi (HTTP {st}): {net.err_text(out)}")
    permalink = ""
    st, out = http("GET", _url(mid) + f"?fields=permalink&access_token={token}")
    if st == 200 and isinstance(out, dict):
        permalink = out.get("permalink", "")
    return {"media_id": mid, "permalink": permalink}


def refresh(token: str, http=net.request) -> tuple[str, int]:
    """(yeni_token, saniye). Token en az 24 saat eski ve suresi dolmamis olmali."""
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
            me = check(token)
            print(f"instagram tamam: @{me['username']} (id {me.get('user_id')})")
            return 0
        if a.refresh:
            new, secs = refresh(token)
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
