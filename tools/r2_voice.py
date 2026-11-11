#!/usr/bin/env python3
"""
Klon ses dosyalari <-> R2 (private). Anahtar duzeni: voice/<senaryo-id>/<dosya>.

Depo PUBLIC; kendi sesinin ham kaydi ve uretilmis cumle dosyalari oraya GIRMEZ. R2'de private kalir,
daily render'dan once indirir (worker/voiceover.py sozlesmesi).

    python tools/r2_voice.py push <dizin>          <dizin>/<id>/manifest.json (cok senaryo) ya da <dizin>/manifest.json (tek)
    python tools/r2_voice.py pull <id> <hedef>     yoksa HATA DEGIL: cikis 0, "klon ses yok" (Piper'a doner)
    python tools/r2_voice.py list                  sesi hazir senaryolar

Ortam: R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY (tools/r2.py).
Sira: once wav'lar, manifest SON (yarim yuklenmis ses 'hazir' gorunmez).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from r2 import NEED, client_from_env             # noqa: E402
from worker.voiceover import SAFE_ID, VERSION     # noqa: E402

PREFIX = "voice/"


def _missing(e: Exception) -> bool:
    err = (getattr(e, "response", None) or {}).get("Error", {})
    return str(err.get("Code", "")) in ("404", "NoSuchKey", "NotFound")


def script_dirs(root: Path) -> list[Path]:
    if (root / "manifest.json").is_file():
        return [root]
    return sorted(d for d in root.iterdir() if d.is_dir() and (d / "manifest.json").is_file())


def _manifest(d: Path) -> dict:
    man = json.loads((d / "manifest.json").read_text())
    if not isinstance(man, dict) or man.get("v") != VERSION or not isinstance(man.get("beats"), dict):
        raise SystemExit(f"{d.name}: manifest bicimi tanimsiz")
    for bid in man["beats"]:
        if not SAFE_ID.match(str(bid)):
            raise SystemExit(f"{d.name}: gecersiz beat kimligi {bid!r}")
        if not (d / f"{bid}.wav").is_file():
            raise SystemExit(f"{d.name}: {bid}.wav yok (manifest onu listeliyor)")
    return man


def push(client, bucket: str, root: Path) -> list[str]:
    done = []
    for d in script_dirs(root):
        sid = d.name
        if not SAFE_ID.match(sid):
            raise SystemExit(f"gecersiz senaryo kimligi: {sid!r}")
        man = _manifest(d)
        for bid in man["beats"]:
            path, key = d / f"{bid}.wav", f"{PREFIX}{sid}/{bid}.wav"
            client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": "audio/wav"})
            got = int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])
            if got != path.stat().st_size:
                raise SystemExit(f"{sid}/{bid}: yukleme boyutu uyusmuyor ({got} != {path.stat().st_size})")
        client.put_object(Bucket=bucket, Key=f"{PREFIX}{sid}/manifest.json",
                          Body=(d / "manifest.json").read_bytes(), ContentType="application/json")
        done.append(sid)
    return done


def pull(client, bucket: str, sid: str, dest: Path) -> dict | None:
    """Manifest + listelenen wav'lar dest'e iner. Senaryonun sesi yoksa None."""
    if not SAFE_ID.match(sid):
        raise SystemExit(f"gecersiz senaryo kimligi: {sid!r}")
    try:
        body = client.get_object(Bucket=bucket, Key=f"{PREFIX}{sid}/manifest.json")["Body"].read()
    except Exception as e:                       # noqa: BLE001 -- boto3 ClientError'u burada import etmiyoruz
        if _missing(e):
            return None
        raise
    man = json.loads(body)
    if not isinstance(man, dict) or man.get("v") != VERSION or not isinstance(man.get("beats"), dict):
        raise SystemExit(f"{sid}: R2'deki manifest bicimi tanimsiz")
    dest.mkdir(parents=True, exist_ok=True)
    for bid in man["beats"]:
        if not SAFE_ID.match(str(bid)):
            raise SystemExit(f"{sid}: gecersiz beat kimligi {bid!r}")
        client.download_file(bucket, f"{PREFIX}{sid}/{bid}.wav", str(dest / f"{bid}.wav"))
    (dest / "manifest.json").write_bytes(body)
    return man


def listing(client, bucket: str) -> list[str]:
    out, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": PREFIX, "Delimiter": "/"}
        if token:
            kw["ContinuationToken"] = token
        r = client.list_objects_v2(**kw)
        out += [c["Prefix"][len(PREFIX):].rstrip("/") for c in r.get("CommonPrefixes", [])]
        if not r.get("IsTruncated"):
            return sorted(out)
        token = r.get("NextContinuationToken")


def _gh(level: str, title: str, msg: str) -> str:
    return f"::{level} title={title}::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"{title}: {msg}"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("push", "pull", "list"):
        print(__doc__, file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd == "pull" and not all(os.environ.get(k, "").strip() for k in NEED):
        # R2 hic kurulmamissa (klon ses kullanmayan kurulum) sessizce Piper
        print("R2 ayari yok; klon ses atlandi (Piper)")
        return 0
    client, bucket = client_from_env()
    if cmd == "push" and len(argv) == 2:
        ids = push(client, bucket, Path(argv[1]))
        print(f"R2'ye gonderildi: {len(ids)} senaryo -> " + ", ".join(ids))
        return 0 if ids else 1
    if cmd == "pull" and len(argv) == 3:
        man = pull(client, bucket, argv[1], Path(argv[2]))
        if man is None:
            print(_gh("warning", "Klon ses yok", f"{argv[1]} icin R2'de ses yok; Piper sesiyle uretilecek"))
        else:
            print(f"klon ses indirildi: {argv[1]} ({len(man['beats'])} cumle, ses: {man.get('voice') or '-'})")
        return 0
    if cmd == "list" and len(argv) == 1:
        print("\n".join(listing(client, bucket)) or "(henuz klon ses yok)")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
