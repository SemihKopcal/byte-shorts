"""
TikTok'a TASLAK olarak yukleme ("Content Posting API > Upload", video.upload).

    python publish/tiktok.py out/<id>/manifest.json
    python publish/tiktok.py --check          # refresh token calisiyor mu

Ne yapar: videoyu TikTok'a yukler; TikTok uygulamasinda bildirim kutusunda
TASLAK olarak bekler. Sen acip aciklamayi yapistirip "Paylas"a basarsin
(aciklamayi API taslaga yazdirmiyor; metin captions.md / release notunda).
Neden taslak: dogrudan yayin (Direct Post) TikTok'un uygulama denetimini
(basvuru, demo videosu, haftalar) gerektiriyor.

Gerekli ortam: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
(365 gun). Erisim token'i 24 saat yasiyor; her kosuda refresh token'dan
uretiliyor. TikTok yenilemede YENI refresh token dondurebiliyor: o durumda
TIKTOK_NEW_REFRESH_FILE ile verilen dosyaya yazilir, workflow secret'i
guncellemeye calisir.
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

API = "https://open.tiktokapis.com"
MB = 1024 * 1024
MIN_CHUNK, MAX_CHUNK, CHUNK = 5 * MB, 64 * MB, 32 * MB


class TikTokError(Exception):
    pass


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count). <=64 MB tek parca; daha buyugu 32 MB
    parcalara bolunur, kalan SON parcaya eklenir (TikTok kurali: parca sayisi
    tam bolumden gelir)."""
    if size <= MAX_CHUNK:
        return size, 1
    return CHUNK, size // CHUNK


def refresh(client_key: str, client_secret: str, refresh_token: str,
            http=net.request) -> dict:
    st, out = http("POST", f"{API}/v2/oauth/token/", form={
        "client_key": client_key, "client_secret": client_secret,
        "grant_type": "refresh_token", "refresh_token": refresh_token})
    if st != 200 or not isinstance(out, dict) or "access_token" not in out:
        raise TikTokError(f"token yenilenemedi (HTTP {st}): {net.err_text(out)}")
    return out


def upload_draft(video: Path, access_token: str, *, http=net.request,
                 sleep=time.sleep, poll_every: float = 5, max_wait: float = 180,
                 log=print) -> str:
    """Videoyu taslaga yukler, publish_id doner."""
    data = video.read_bytes()
    size = len(data)
    chunk, total = chunk_plan(size)
    st, out = http("POST", f"{API}/v2/post/publish/inbox/video/init/",
                   headers={"Authorization": f"Bearer {access_token}"},
                   json_body={"source_info": {
                       "source": "FILE_UPLOAD", "video_size": size,
                       "chunk_size": chunk, "total_chunk_count": total}})
    body = out.get("data") if isinstance(out, dict) else None
    err = (out.get("error") or {}) if isinstance(out, dict) else {}
    if st != 200 or err.get("code", "ok") != "ok" or not body \
            or not body.get("upload_url"):
        raise TikTokError(f"yukleme baslatilamadi (HTTP {st}): {net.err_text(out)}")
    pid, url = body["publish_id"], body["upload_url"]
    log(f"  tiktok: publish_id {pid}, {total} parca, {size / MB:.1f} MB")

    for i in range(total):
        a = i * chunk
        b = size - 1 if i == total - 1 else a + chunk - 1
        part = data[a:b + 1]
        st, out = http("PUT", url, headers={
            "Content-Type": "video/mp4", "Content-Length": str(len(part)),
            "Content-Range": f"bytes {a}-{b}/{size}"}, data=part, timeout=300)
        if st not in (200, 201, 206):
            raise TikTokError(f"parca {i + 1}/{total} yuklenemedi (HTTP {st}): "
                              f"{net.err_text(out)}")

    waited = 0.0
    while True:
        st, out = http("POST", f"{API}/v2/post/publish/status/fetch/",
                       headers={"Authorization": f"Bearer {access_token}"},
                       json_body={"publish_id": pid})
        d = out.get("data") if isinstance(out, dict) else None
        status = (d or {}).get("status")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return pid
        if status == "FAILED":
            raise TikTokError(f"TikTok isleyemedi: {(d or {}).get('fail_reason', '?')}")
        if waited >= max_wait:
            raise TikTokError(f"{max_wait:.0f} sn icinde taslaga dusmedi "
                              f"(son durum: {status})")
        sleep(poll_every)
        waited += poll_every


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    rt = os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()
    if not (key and secret and rt):
        print("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET / TIKTOK_REFRESH_TOKEN eksik",
              file=sys.stderr)
        return 2
    try:
        man = None
        if not a.check:
            if not a.manifest:
                print("kullanim: tiktok.py manifest.json", file=sys.stderr)
                return 2
            man = json.loads(Path(a.manifest).read_text())
            if ledger.done(man["id"], "tiktok"):
                print(f"{man['id']} zaten TikTok'a gonderilmis; atlandi")
                return 0
        tok = refresh(key, secret, rt)
        new_rt = tok.get("refresh_token")
        if new_rt and new_rt != rt:
            path = os.environ.get("TIKTOK_NEW_REFRESH_FILE")
            if path:
                Path(path).write_text(new_rt)
                Path(path).chmod(0o600)
            print("tiktok: YENI refresh token geldi (eskisi gecersiz olabilir)")
        days = int(tok.get("refresh_expires_in", 0)) // 86400
        if a.check:
            print(f"tiktok tamam: refresh token ~{days} gun gecerli, "
                  f"kapsam: {tok.get('scope')}")
            return 0
        if "video.upload" not in str(tok.get("scope", "")):
            raise TikTokError("token'da video.upload izni yok; "
                              "tools/tiktok_login.py ile yeniden yetkilendir")
        if a.dry_run:
            print(f"[dry-run] {man['id']}")
            return 0
        video = Path(a.manifest).parent / man["video"]
        pid = upload_draft(video, tok["access_token"])
        ledger.record(man["id"], "tiktok", {"publish_id": pid})
        print("tiktok: taslak hazir. TikTok uygulamasi > Gelen kutusu > bildirim; "
              "aciklamayi captions.md'den yapistir.")
        return 0
    except TikTokError as e:
        print(f"TIKTOK HATASI: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
