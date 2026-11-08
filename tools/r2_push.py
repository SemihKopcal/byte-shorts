"""
Render ciktisini R2'ye koyar ve panele haber verir (PANEL_MODE=on iken daily bunu calistirir).

    python tools/r2_push.py out/<id>

Sira onemli: ONCE uc dosya (mp4, manifest, captions), SONRA `inbox/<id>.json`.
Panel yalniz inbox kaydini gorunce ice alir, yani yarim yuklenmis video panelde
gorunmez. Her dosyanin boyutu yuklemeden sonra dogrulanir.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2 import SLUG, client_from_env          # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def push(client, bucket: str, out_dir: Path, run_url: str = "", now=None) -> dict:
    man = json.loads((out_dir / "manifest.json").read_text())
    sid = man["id"]
    if not isinstance(sid, str) or not SLUG.match(sid):
        raise SystemExit(f"gecersiz video kimligi: {sid!r}")
    video = out_dir / man["video"]
    captions = out_dir / "captions.md"
    for p in (video, captions):
        if not p.is_file():
            raise SystemExit(f"dosya yok: {p}")
    keys = {"video": (video, f"videos/{sid}/{sid}.mp4", "video/mp4"),
            "manifest": (out_dir / "manifest.json", f"videos/{sid}/manifest.json", "application/json"),
            "captions": (captions, f"videos/{sid}/captions.md", "text/markdown; charset=utf-8")}
    for name, (path, key, ctype) in keys.items():
        client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": ctype})
        got = int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])
        if got != path.stat().st_size:
            raise SystemExit(f"{name}: yukleme boyutu uyusmuyor ({got} != {path.stat().st_size})")
    rec = {"v": 1, "script_id": sid, "title": man["title"], "series": man.get("series", ""),
           "duration": float(man["duration"]), "size_bytes": video.stat().st_size,
           "sha256": sha256(video),
           "rendered_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "run_url": run_url}
    client.put_object(Bucket=bucket, Key=f"inbox/{sid}.json",
                      Body=json.dumps(rec).encode(), ContentType="application/json")
    return rec


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("kullanim: r2_push.py out/<id>", file=sys.stderr)
        return 2
    client, bucket = client_from_env()
    server, repo, run = (os.environ.get(k, "") for k in
                         ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    run_url = f"{server}/{repo}/actions/runs/{run}" if server and repo and run else ""
    rec = push(client, bucket, Path(argv[0]), run_url)
    print(f"R2'ye gonderildi: {rec['script_id']} ({rec['size_bytes'] // 1024} KB), panel onayini bekliyor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
