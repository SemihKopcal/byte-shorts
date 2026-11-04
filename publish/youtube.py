"""
YouTube'a yukleme.

Varsayilan PRIVATE. Sebebi: hat her gece calisiyor, sen sabah bakiyorsun.
Yanlis bir sayi veya bozuk bir kare dogrudan yayina cikarsa geri almak
izlenme gecmisini de goturuyor. Once private yukle, panelden onayla, sonra
--publish ile public'e cek.

Kota notu: videos.insert "Video Uploads" kovasindan 1 birim yiyor ve gunde
100 cagri ile sinirli. Gunde 2 video icin fazlasiyla yeterli; tekrar denemeler
de bu kovadan dustugu icin sonsuz retry yazmiyoruz.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parent.parent
TOKEN_URI = "https://oauth2.googleapis.com/token"


def service():
    missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
                           "YOUTUBE_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit("eksik secret: " + ", ".join(missing))
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(man_path: Path, privacy: str) -> str:
    man = json.loads(man_path.read_text())
    video = man_path.parent / man["video"]
    if not video.exists():
        sys.exit(f"video yok: {video}")

    body = {
        "snippet": {
            "title": man["title"][:100],
            "description": man["description"][:5000],
            "tags": man["tags"][:15],
            "categoryId": "28",          # Science & Technology
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            # Kanal icerigi tamamen sentetik ses + kodla cizilmis gorsel.
            # YouTube 2026 kurallari bunun beyan edilmesini istiyor; beyan
            # etmemek "yaniltici icerik" tarafina dusuyor.
            "containsSyntheticMedia": True,
        },
    }

    media = MediaFileUpload(str(video), chunksize=4 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    req = service().videos().insert(part="snippet,status", body=body,
                                    media_body=media)
    resp = None
    while resp is None:
        try:
            status, resp = req.next_chunk()
        except HttpError as e:
            # 5xx gecici; 4xx kalici (kota, yetki, gecersiz alan) -- tekrar
            # denemek kotayi bosa harcar.
            if e.resp.status in (500, 502, 503, 504):
                print("gecici hata, tekrar:", e.resp.status)
                continue
            sys.exit(f"yukleme basarisiz [{e.resp.status}]: {e}")
        if status:
            print(f"  %{int(status.progress() * 100)}")

    vid = resp["id"]
    man["youtube_id"] = vid
    man["privacy"] = privacy
    man_path.write_text(json.dumps(man, indent=1, ensure_ascii=False))

    log = ROOT / "content/published.json"
    prev = json.loads(log.read_text()) if log.exists() else []
    prev.append({"id": man["id"], "series": man["series"],
                 "title": man["title"], "youtube_id": vid})
    log.write_text(json.dumps(prev, indent=1, ensure_ascii=False))

    print(f"https://youtube.com/watch?v={vid}  ({privacy})")
    return vid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--publish", action="store_true",
                    help="private yerine public yukle (onaylandiktan sonra)")
    a = ap.parse_args()
    upload(Path(a.manifest), "public" if a.publish else "private")


if __name__ == "__main__":
    main()
