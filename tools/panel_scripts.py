"""
Panelden gelen SENARYO islemlerini uygular (panel-scripts workflow'u calistirir).

Panel (byte.semihkopcal.com) depoya yazamaz; kolay formu R2'ye koyar ve bu workflow'u tetikler.
Asil is burada: form -> senaryo (editorial.formscript), AYNI kapi (editorial.authored.problems),
dosyayi yazma, kuyruk sirasi. Panelin kendi on kontrolu yalniz hizli geri bildirim icindir;
yetkili olan bu kapidir.

Girdi YALNIZ ortam degiskenlerinden (workflow girdileri kabuga gomulmez): ACTION, SCRIPT_ID, REQUEST_ID.

    python tools/panel_scripts.py apply    dosyalari degistirir, sonucu yerel dosyaya yazar
    python tools/panel_scripts.py report   sonucu R2'ye (scripts-out/<istek>.json) yazar

Iki adim, arada workflow commit + push yapar: "eklendi" sonucu push GERCEKTEN basarili olunca gider.

Eylemler:
  ingest      R2 scripts-in/<istek>.json (kolay form) -> content/scripts/pNNN-slug.json + order.json sonuna
  move_first  kuyruktaki bir senaryoyu order.json'un basina al (yapilmamis olmali)
  remove      kuyruktaki bir senaryoyu sil (yapilmamis ve bir deneyin kolunda olmamali)

Ortak sozlesme (panel/bytepanel/scripts.py ile): R2 anahtarlari scripts-in/ ve scripts-out/. `inbox/`
KULLANILMAZ: panelin video kutusu orayi okuyup bilinmeyen kayitlari karantinaya aliyor.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r2 import client_from_env  # noqa: E402

REQ = re.compile(r"^[a-f0-9]{32}\Z")
SID = re.compile(r"^p\d{3}-[a-z0-9-]{1,72}\Z")
ACTIONS = ("ingest", "move_first", "remove")
IN_PREFIX, OUT_PREFIX = "scripts-in/", "scripts-out/"
MAX_IN = 64 * 1024
MAX_PROBLEMS, MAX_LINE = 20, 300
RESULT_FILE = ROOT / "out" / "panel_scripts_result.json"


class Refused(Exception):
    """Isleme izin verilmeyen durum (kullaniciya gosterilir)."""


# ── dosya yardimcilari ───────────────────────────────────────────────────
def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def script_ids(root: Path) -> set[str]:
    return {p.stem for p in (root / "content" / "scripts").glob("*.json")}


def done_ids(root: Path) -> set[str]:
    out: set[str] = set()
    for name in ("built.json", "published.json"):
        for x in _json(root / "content" / name, []):
            out.add(x if isinstance(x, str) else str(x.get("id", "")) if isinstance(x, dict) else "")
    return out


def order_ids(root: Path) -> list[str]:
    d = _json(root / "content" / "order.json", [])
    return [x for x in d if isinstance(x, str)] if isinstance(d, list) else []


def write_order(root: Path, ids: list[str]) -> None:
    (root / "content" / "order.json").write_text(json.dumps(ids, indent=2) + "\n", encoding="utf-8")


def experiment_ids(root: Path) -> set[str]:
    out: set[str] = set()
    for e in (_json(root / "content" / "experiments.json", {}) or {}).values():
        for ids in (e.get("arms") or {}).values() if isinstance(e, dict) else []:
            out |= {x for x in ids if isinstance(x, str)}
    return out


def next_number(root: Path) -> int:
    nums = [int(m.group(1)) for sid in script_ids(root) | done_ids(root) | set(order_ids(root))
            if (m := re.match(r"^p(\d{3})-", sid))]
    return max(nums, default=0) + 1


def titles(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted((root / "content" / "scripts").glob("*.json")):
        t = str((_json(p, {}) or {}).get("title", "")).strip().lower()
        if t:
            out.setdefault(t, p.stem)
    return out


# ── eylemler ─────────────────────────────────────────────────────────────
def do_ingest(root: Path, form_rec, now: datetime, scene_names, brand: dict, draw_check: bool) -> dict:
    from editorial import authored, formscript

    if not isinstance(form_rec, dict) or form_rec.get("v") != 1 or form_rec.get("action") != "new":
        raise Refused("gecersiz kayit (v=1, action=new degil)")
    spec, probs = formscript.compile_form(form_rec.get("form"), next_number(root), f"{now:%Y-%m-%d}")
    if probs or spec is None:
        return {"status": "rejected", "problems": probs, "message": "Form senaryoya cevrilemedi."}
    sid = spec["id"]
    probs = authored.problems(spec, scene_names, brand, f"{sid}.json")
    if (root / "content" / "scripts" / f"{sid}.json").exists():
        probs.append(f"{sid} zaten var")
    clash = titles(root).get(spec["title"].strip().lower())
    if clash:
        probs.append(f"ayni baslik {clash} icinde var")
    if not probs and draw_check:
        probs += draw_problems(spec)
    if probs:
        return {"status": "rejected", "problems": probs, "message": "Kapidan gecmedi, senaryo eklenmedi."}
    (root / "content" / "scripts" / f"{sid}.json").write_text(formscript.dumps(spec), encoding="utf-8")
    write_order(root, [x for x in order_ids(root) if x != sid] + [sid])
    return {"status": "ok", "script_id": sid, "title": spec["title"], "changed": True,
            "message": f"{sid} eklendi, kuyrugun sonunda."}


def draw_problems(spec: dict) -> list[str]:
    """Kareleri sessizce ciz: font/bagimlilik yoksa atla (baska yerde yakalanir), varsa bos/patlayan sahneyi yakala."""
    try:
        from tests import test_scripts_draw as T
    except Exception:           # noqa: BLE001
        return []
    if not getattr(T, "_OK", False):
        return []
    try:
        _, _, blank = T.draw_script(json.loads(json.dumps(spec)))
    except Exception as e:      # noqa: BLE001
        return [f"kare cizimi patladi: {type(e).__name__}: {str(e)[:150]}"]
    return [f"bos kalan sahne: {', '.join(blank)}"] if blank else []


def check_queued(root: Path, sid: str) -> None:
    if not SID.match(sid):
        raise Refused("senaryo kimligi gecersiz")
    if sid not in script_ids(root):
        raise Refused(f"{sid} depoda yok")
    if sid in done_ids(root):
        raise Refused(f"{sid} zaten uretilmis/yayinlanmis: kuyrukta degil")


def do_move_first(root: Path, sid: str) -> dict:
    check_queued(root, sid)
    old = order_ids(root)
    new = [sid] + [x for x in old if x != sid]
    if new == old:
        return {"status": "ok", "script_id": sid, "changed": False, "message": f"{sid} zaten ilk sirada."}
    write_order(root, new)
    return {"status": "ok", "script_id": sid, "changed": True, "message": f"{sid} sirada one alindi."}


def do_remove(root: Path, sid: str) -> dict:
    check_queued(root, sid)
    if sid in experiment_ids(root):
        raise Refused(f"{sid} bir A/B deneyinin kolunda: silinirse deney bozulur")
    (root / "content" / "scripts" / f"{sid}.json").unlink()
    write_order(root, [x for x in order_ids(root) if x != sid])
    return {"status": "ok", "script_id": sid, "changed": True,
            "message": f"{sid} silindi (git gecmisinde duruyor, geri alinabilir)."}


# ── giris noktalari ──────────────────────────────────────────────────────
def parse_inputs(env) -> dict:
    action, sid, rid = env.get("ACTION", ""), env.get("SCRIPT_ID", ""), env.get("REQUEST_ID", "")
    if action not in ACTIONS:
        raise Refused("ACTION gecersiz")
    if not REQ.match(rid):
        raise Refused("REQUEST_ID gecersiz")
    if action != "ingest" and not SID.match(sid):
        raise Refused("SCRIPT_ID gecersiz")
    return {"action": action, "sid": sid, "rid": rid}


def read_input(client, bucket: str, rid: str):
    try:
        body = client.get_object(Bucket=bucket, Key=f"{IN_PREFIX}{rid}.json")["Body"].read(MAX_IN + 1)
    except Exception as e:      # noqa: BLE001
        raise Refused(f"istek kaydi okunamadi ({type(e).__name__})") from None
    if len(body) > MAX_IN:
        raise Refused("istek kaydi cok buyuk")
    try:
        return json.loads(body)
    except ValueError:
        raise Refused("istek kaydi JSON degil") from None


def apply(env, client, bucket: str, root: Path = ROOT, now: datetime | None = None,
          scene_names=None, brand: dict | None = None) -> dict:
    """Eylemi uygular ve sonucu YEREL dosyaya yazar. Donus: sonuc sozlugu."""
    now = now or datetime.now(timezone.utc)
    res = {"status": "error", "message": "", "problems": [], "changed": False,
           "action": "", "script_id": "", "request_id": ""}
    try:
        inp = parse_inputs(env)
        res.update(action=inp["action"], script_id=inp["sid"], request_id=inp["rid"])
        if inp["action"] == "ingest":
            if scene_names is None:
                from worker.scenes import NAMES as scene_names     # noqa: N811
            if brand is None:
                from publish import manifest as M
                brand = M.load_brand(root)
            part = do_ingest(root, read_input(client, bucket, inp["rid"]), now, scene_names, brand,
                             draw_check=env.get("DRAW_CHECK") == "1")
        elif inp["action"] == "move_first":
            part = do_move_first(root, inp["sid"])
        else:
            part = do_remove(root, inp["sid"])
        res.update(part)
    except Refused as e:
        res.update(status="rejected", message=str(e), problems=[str(e)])
    except Exception as e:      # noqa: BLE001
        res.update(status="error", message=f"beklenmeyen hata: {type(e).__name__}: {str(e)[:200]}")
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(res), encoding="utf-8")
    return res


def _line(x) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(x))[:MAX_LINE]


def report(env, client, bucket: str, now: datetime | None = None, result_file: Path | None = None) -> dict:
    """Sonucu panele (R2 scripts-out/) yazar. Degisiklik varsa ama push olmadiysa 'error' bildirir."""
    now = now or datetime.now(timezone.utc)
    rid = env.get("REQUEST_ID", "")
    if not REQ.match(rid):
        raise SystemExit("REQUEST_ID gecersiz")
    res = _json(result_file or RESULT_FILE, None)
    if not isinstance(res, dict):
        res = {"status": "error", "message": "uygulama adimi sonuc uretmedi (apply calismadi)",
               "problems": [], "changed": False, "action": env.get("ACTION", ""), "script_id": ""}
    if res.get("changed") and env.get("PUSH_OK") != "true":
        res.update(status="error", message="Degisiklik depoya yazilamadi (push basarisiz); sonra tekrar dene.")
    payload = {"v": 1, "request_id": rid, "action": str(res.get("action", ""))[:20],
               "status": res.get("status") if res.get("status") in ("ok", "rejected", "error") else "error",
               "script_id": str(res.get("script_id", ""))[:80], "title": _line(res.get("title", ""))[:120],
               "message": _line(res.get("message", "")),
               "problems": [_line(x) for x in (res.get("problems") or [])][:MAX_PROBLEMS],
               "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    client.put_object(Bucket=bucket, Key=f"{OUT_PREFIX}{rid}.json",
                      Body=json.dumps(payload).encode(), ContentType="application/json")
    if payload["action"] == "ingest":
        try:
            client.delete_object(Bucket=bucket, Key=f"{IN_PREFIX}{rid}.json")
        except Exception:       # noqa: BLE001
            pass                # form kaydi kalirsa zararsiz; panel bir daha okumaz
    return payload


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ("apply", "report"):
        print(__doc__)
        return 2
    client, bucket = client_from_env()
    if args[0] == "apply":
        res = apply(os.environ, client, bucket)
        print(f"{res['status']}: {res['message']}")
        for p in res["problems"][:MAX_PROBLEMS]:
            print(f"  - {_line(p)}")
        return 0
    payload = report(os.environ, client, bucket)
    print(f"panele bildirildi: {payload['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
