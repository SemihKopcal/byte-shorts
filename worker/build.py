"""
Uctan uca uretim: script -> ses -> kare -> video -> QC -> manifest.

Kullanim:
    python -m worker.build content/scripts/2026-10-27-cost-of-alphabets.json

Kare cizimi CPU'ya bagli ve tek cekirdekte donuyor. Cok cekirdekli bir makinede
PARALLEL=1 ile kareler surece dagitilir (GitHub runner 2 cekirdek oldugu icin
varsayilan kapali; i7'de ~6 kat hizlaniyor).
"""
import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import draw as D
from .byte import draw_byte_badge, MINT as B_MINT
from .qc import check
from .synth import synthesize

ROOT = Path(__file__).resolve().parent.parent
VOICE = Path(os.environ.get("PIPER_VOICE", ROOT / "voices/en-us-ryan-high.onnx"))


def _stages(series_mod, S, duration, spec):
    """Sahne penceresi listesi.

    Iki bicim destekleniyor:
      * series_g gibi SENARYODAN okuyanlar -> stages(spec, S, duration)
      * series_a/b gibi elle yazilmis olanlar -> STAGES = [('b1','b2',fn)]
    """
    if hasattr(series_mod, "stages"):
        return series_mod.stages(spec, S, duration)
    out = []
    for a, b, fn in series_mod.STAGES:
        t0 = S[a][0]
        t1 = duration if b is None else S[b][1] + 0.30
        out.append((t0, t1, fn))
    return out


def _recent_themes(n=3):
    log = ROOT / "content/published.json"
    if not log.exists():
        return []
    try:
        return [x.get("theme", "") for x in json.loads(log.read_text())][-n:]
    except Exception:
        return []


def render(spec, tl, series_mod, out_path: Path, parallel: bool = False) -> None:
    # Tema EN BASTA secilir: D.INK, D.TONE gibi degerler buradan sonra
    # okunuyor, sonra degistirmek yarisi eski yarisi yeni renkte bir video
    # verirdi.
    from . import themes as T
    theme = D.use_theme(T.pick(spec, _recent_themes()))
    spec["_theme"] = theme
    print(f"  tema: {theme}")

    beats = tl["beats"]
    duration = tl["duration"]
    S = {b["id"]: (b["start"], b["end"]) for b in beats}
    chunks = D.build_captions(beats)
    badge_font = D.F_SEMI(26)
    stages = _stages(series_mod, S, duration, spec)
    # kapanista baslik zaten ekranda metin; altyazi onun uzerine binmesin
    close_t0 = stages[-1][0] if stages else duration

    bg = D.build_bg()
    grain = D.build_grain()
    nframes = int(duration * D.FPS)

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{D.W}x{D.H}", "-r", str(D.FPS), "-i", "pipe:0",
         "-i", str(out_path.parent / "voice.wav"),
         "-c:v", "libx264", "-preset", "slow", "-crf", "23",
         "-x264-params", "aq-mode=3:psy-rd=1.0:deblock=-1,-1",
         "-profile:v", "high", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", str(out_path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for i in range(nframes):
        t = i / D.FPS
        img = bg.copy()
        d = ImageDraw.Draw(img)
        push = 0.0
        for t0, t1, fn in stages:
            if t0 - 0.25 <= t <= t1:
                fn(d, t, S, spec)
                push = D.PUSH * D.clamp01((t - t0) / max(0.1, t1 - t0))

        # push-in SADECE sahne katmanina; altyazi/chrome ustte, olceksiz.
        if push > 0.0005:
            k = 1 + push
            cw, ch = int(D.W / k), int(D.H / k)
            img = img.crop(((D.W - cw) // 2, (D.H - ch) // 2,
                            (D.W - cw) // 2 + cw, (D.H - ch) // 2 + ch)) \
                     .resize((D.W, D.H), Image.BILINEAR)
            d = ImageDraw.Draw(img)

        # kapanista baslik zaten metin; altyazi tekrar olurdu
        if t < close_t0 - 0.1:
            D.draw_caption(d, t, chunks)
        D.draw_chrome(d, t, duration, badge_font)

        arr = np.asarray(img, dtype=np.int16) + grain[i % len(grain)]
        enc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
        if i % 200 == 0:
            print(f"  kare {i}/{nframes}", flush=True)

    enc.stdin.close()
    err = enc.stderr.read().decode()[-1500:]
    if enc.wait() != 0:
        sys.exit("ffmpeg basarisiz:\n" + err)


def manifest(spec, tl, video: Path) -> dict:
    """Yayin adiminin okuyacagi metadata. Baslik/aciklama burada uretiliyor ki
    panel ve YouTube ayni metni gorsun."""
    brand = json.loads((ROOT / "brand.json").read_text())
    tags = brand["tags_base"] + spec.get("tags", [])
    src = "\n".join(f"- {s}" for s in spec.get("sources", []))
    desc = (f"{spec.get('summary', spec['title'])}\n\n"
            f"Sources / method:\n{src}\n\n"
            f"{brand['description_footer']}")
    return {
        "id": spec["id"],
        "series": spec["series"],
        "title": spec["title"],
        "description": desc,
        "tags": tags[:15],
        "duration": tl["duration"],
        "video": str(video.name),
        "theme": spec.get("_theme", ""),
        "privacy": "private",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--out", default="out")
    ap.add_argument("--skip-synth", action="store_true")
    args = ap.parse_args()

    spec = json.loads(Path(args.script).read_text())
    out_dir = ROOT / args.out / spec["id"]
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_synth and (out_dir / "timeline.json").exists():
        tl = json.loads((out_dir / "timeline.json").read_text())
    else:
        if not VOICE.exists():
            sys.exit(f"Ses modeli yok: {VOICE}\n  tools/fetch_voice.sh calistir")
        print("seslendirme...")
        tl = synthesize(spec, out_dir, VOICE)
    print(f"  sure: {tl['duration']:.2f}s")

    series_mod = importlib.import_module(f".series_{spec['series'].lower()}", __package__)
    video = out_dir / f"{spec['id']}.mp4"
    print("kare cizimi...")
    render(spec, tl, series_mod, video)

    m = manifest(spec, tl, video)
    (out_dir / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))

    problems = check(video, tl, spec, ROOT / "content/published.json")
    if problems:
        print("\nQC BASARISIZ:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print(f"\nQC temiz -> {video}")


if __name__ == "__main__":
    main()
