"""
Panelden gelen yayin emrini uygular (panel-publish workflow'u calistirir).

Girdi YALNIZ ortam degiskenlerinden (workflow girdileri kabuga gomulmez; script
enjeksiyonunu onlemek icin): SCRIPT_ID, PLATFORM, PRIVACY, REQUEST_ID.

Akis: R2'den dosyalari indir -> ilgili yukleyiciyi calistir -> sonucu
`results/<id>.<platform>.json` olarak R2'ye yaz (basarisiz olsa da, panel
beklemesin). Platform token'lari yalniz GitHub Secrets'ta; panel sunucusuna gitmez.

Cift yukleme korumasi: basarili her yayindan sonra R2'ye `ledger/<id>.<platform>.json`
yazilir; ayni video ayni platforma tekrar istenirse yukleyici CALISTIRILMAZ. Depoya
commit atilmaz (paralel kosular birbirinin dosyasini ezmesin, yazma yetkisi gerekmesin).
Durumu okuyamazsak yuklemeyiz (fail-closed): iki kez yayinlamaktansa hic yayinlamamak.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2 import SLUG, client_from_env          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ("youtube", "instagram", "tiktok")
PRIVACY = ("public", "unlisted", "private")
REQ = re.compile(r"^[a-f0-9]{32}\Z")
MAX_VIDEO = 300 * 1024 * 1024
MAX_SMALL = 1024 * 1024
SECRET_VARS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
               "INSTAGRAM_TOKEN", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
               "TIKTOK_REFRESH_TOKEN", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "GH_PAT")


class Bad(Exception):
    pass


def parse_inputs(env) -> dict:
    sid, plat = env.get("SCRIPT_ID", ""), env.get("PLATFORM", "")
    priv, rid = env.get("PRIVACY", "public"), env.get("REQUEST_ID", "")
    if not SLUG.match(sid):
        raise Bad("SCRIPT_ID gecersiz")
    if plat not in PLATFORMS:
        raise Bad("PLATFORM gecersiz")
    if not REQ.match(rid):
        raise Bad("REQUEST_ID gecersiz")
    if priv not in PRIVACY:
        raise Bad("PRIVACY gecersiz")
    return {"sid": sid, "platform": plat, "privacy": priv, "rid": rid}


def scrub(text: str, env) -> str:
    for name in SECRET_VARS:
        v = env.get(name, "")
        if len(v) >= 6:
            text = text.replace(v, "***")
    return text


def download(client, bucket, key, dest: Path, max_bytes: int) -> None:
    try:
        size = int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])
    except Exception as e:                                   # noqa: BLE001
        raise Bad(f"{key} R2'den okunamadi ({type(e).__name__})") from None
    if size > max_bytes:
        raise Bad(f"{key}: {size} bayt cok buyuk")
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(dest))


def remote_info(platform: str, sid: str, out_dir: Path, root: Path) -> tuple[str, str]:
    """(remote_id, remote_url): yukleyicilerin biraktigi kayitlardan."""
    if platform == "youtube":
        yid = already_on_youtube(root, sid)
        if not yid:
            try:
                yid = str(json.loads((out_dir / "manifest.json").read_text()).get("youtube_id", ""))
            except (OSError, ValueError):
                yid = ""
        return yid, (f"https://youtu.be/{yid}" if yid else "")
    try:
        social = json.loads((root / "content/social.json").read_text())
        rec = social.get(sid, {}).get(platform, {})
    except (OSError, ValueError):
        return "", ""
    if platform == "instagram":
        return str(rec.get("media_id", "")), str(rec.get("permalink", ""))
    return str(rec.get("publish_id", "")), ""


NOT_FOUND = {"404", "NoSuchKey", "NotFound"}


def ledger_key(sid: str, plat: str) -> str:
    return f"ledger/{sid}.{plat}.json"


def read_ledger(client, bucket, sid: str, plat: str):
    """Kayit varsa dict, yoksa None. Belirsiz bir hatada firlatir (fail-closed)."""
    key = ledger_key(sid, plat)
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as e:                                   # noqa: BLE001
        code = str(((getattr(e, "response", None) or {}).get("Error") or {}).get("Code", ""))
        if code in NOT_FOUND:
            return None
        raise Bad(f"yayin kaydi okunamadi ({type(e).__name__}); cift yuklemeyi onlemek icin durdum")
    tmp = client.get_object(Bucket=bucket, Key=key)["Body"].read(MAX_SMALL + 1)
    if len(tmp) > MAX_SMALL:
        raise Bad("yayin kaydi cok buyuk")
    try:
        d = json.loads(tmp)
    except ValueError:
        raise Bad("yayin kaydi bozuk; cift yuklemeyi onlemek icin durdum") from None
    return d if isinstance(d, dict) else {}


def already_on_youtube(root: Path, sid: str) -> str:
    try:
        for e in json.loads((root / "content/published.json").read_text()):
            if e.get("id") == sid and e.get("youtube_id"):
                return e["youtube_id"]
    except (OSError, ValueError):
        pass
    return ""


def run(env, client, bucket, root: Path = ROOT, runner=subprocess.run, now=None) -> int:
    try:
        inp = parse_inputs(env)
    except Bad as e:
        print(f"GECERSIZ GIRDI: {e}", file=sys.stderr)
        return 2
    sid, plat, rid = inp["sid"], inp["platform"], inp["rid"]
    result = {"v": 1, "request_id": rid, "script_id": sid, "platform": plat, "ok": False,
              "remote_id": "", "remote_url": "", "error": "", "at": "", "run_url": ""}
    server, repo, run_id = (env.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    if server and repo and run_id:
        result["run_url"] = f"{server}/{repo}/actions/runs/{run_id}"
    out_dir = root / "out" / sid
    try:
        for name, cap in (("manifest.json", MAX_SMALL), ("captions.md", MAX_SMALL), (f"{sid}.mp4", MAX_VIDEO)):
            download(client, bucket, f"videos/{sid}/{name}", out_dir / name, cap)
        man = json.loads((out_dir / "manifest.json").read_text())
        if man.get("id") != sid:
            raise Bad("manifest kimligi istekle uyusmuyor")
        done = read_ledger(client, bucket, sid, plat)
        if done is not None:
            result.update(ok=True, remote_id=str(done.get("remote_id", ""))[:80],
                          remote_url=str(done.get("remote_url", ""))[:300],
                          error="zaten yayinlanmisti (kayit var), yeniden yuklenmedi")
        elif plat == "youtube" and (yid := already_on_youtube(root, sid)):
            result.update(ok=True, remote_id=yid, remote_url=f"https://youtu.be/{yid}",
                          error="zaten yuklenmisti (defterde var)")
        else:
            cmd = [sys.executable, str(root / "publish" / f"{plat}.py"), str(out_dir / "manifest.json")]
            if plat == "youtube":
                cmd += ["--privacy", inp["privacy"]]
            elif plat == "instagram":
                url = client.generate_presigned_url(
                    "get_object", Params={"Bucket": bucket, "Key": f"videos/{sid}/{sid}.mp4"},
                    ExpiresIn=3600)
                cmd += ["--video-url", url]
            p = runner(cmd, capture_output=True, text=True, timeout=1500, env=dict(env), cwd=str(root))
            if p.returncode != 0:
                tail = scrub((p.stderr or p.stdout or "").strip()[-300:], env)
                raise Bad(f"{plat} yukleyicisi hata verdi (cikis {p.returncode}): {tail}")
            rid_remote, url = remote_info(plat, sid, out_dir, root)
            result.update(ok=True, remote_id=rid_remote, remote_url=url)
            try:                       # yukleme OLDU; kayit yazilamazsa bile sonucu bildir
                client.put_object(Bucket=bucket, Key=ledger_key(sid, plat), ContentType="application/json",
                                  Body=json.dumps({"remote_id": rid_remote, "remote_url": url,
                                                   "at": (now or datetime.now(timezone.utc)).strftime(
                                                       "%Y-%m-%dT%H:%M:%SZ")}).encode())
            except Exception as e:                           # noqa: BLE001
                print(f"UYARI: yayin kaydi yazilamadi ({type(e).__name__}); yeniden denenirse "
                      "ayni video ikinci kez yuklenebilir", file=sys.stderr)
    except Bad as e:
        result["error"] = scrub(str(e), env)[:400]
    except Exception as e:                                   # noqa: BLE001
        result["error"] = scrub(f"{type(e).__name__}: {e}", env)[:400]
    finally:
        result["at"] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            client.put_object(Bucket=bucket, Key=f"results/{sid}.{plat}.json",
                              Body=json.dumps(result).encode(), ContentType="application/json")
        except Exception as e:                               # noqa: BLE001
            print(f"SONUC YAZILAMADI: {type(e).__name__}", file=sys.stderr)
            return 1
    print(("basarili" if result["ok"] else f"basarisiz: {result['error']}"))
    return 0 if result["ok"] else 1


def main() -> int:
    client, bucket = client_from_env()
    return run(os.environ, client, bucket)


if __name__ == "__main__":
    sys.exit(main())
