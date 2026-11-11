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
from . import cartoon as TOON
from . import cta as CTA
from . import fx as FX
from . import style as STYLE
from . import voiceover as CLONE
from .qc import check
from .synth import synthesize

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from publish.manifest import (build_manifest, captions_markdown,   # noqa: E402
                              load_brand)

VOICE = Path(os.environ.get("PIPER_VOICE", ROOT / "voices/en-us-ryan-high.onnx"))
SAFE_SECONDS = 56.0      # QC sinirinin (59) altinda pay; tempo bunu asarsa varsayilana doner


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


def style_layer(img, t, i, stages, cams, sty, theme_colors):
    """Sahne katmanina kamera hareketi + gecis efekti (altyazi/rozet bundan SONRA, olceksiz).

    Kamera sahnenin KENDI penceresinde (t0'dan itibaren) calisir; sahne baslamadan once onceki
    sahnenin son durumunda kalir (aradaki ani ziplama olmaz). Efekt sahne degisiminde
    TRANSITION_DELAY'den sonra TRANSITION_SECONDS surer; ilk sahnede efekt yoktur."""
    if not stages:
        return img
    si = 0
    for k, (t0, _t1, _f) in enumerate(stages):
        if t0 <= t:
            si = k
    t0, t1, _f = stages[si]
    p = D.clamp01((t - t0) / max(0.1, t1 - t0))
    scale, dx, dy = FX.camera_state(cams[si]["mode"], p, cams[si]["amp"], img.width, img.height)
    img = FX.apply_camera(img, scale, dx, dy)
    u = (t - t0 - FX.TRANSITION_DELAY) / FX.TRANSITION_SECONDS
    if si >= 1 and 0 <= u < 1:
        img = FX.transition(img, STYLE.transition_for(sty, si), u, theme_colors, seed=i)
    return img


def _classic_frame(t, i, bg, stages, S, spec, sty, cams, theme_colors, chunks, close_t0, duration,
                   badge_font, corner, corner_text):
    """Eski (koyu tema) kare: sahne katmani + kamera/gecis + altyazi + chrome + CTA kose etiketi."""
    img = bg.copy()
    d = ImageDraw.Draw(img)
    push = 0.0
    for t0, t1, fn in stages:
        if t0 - 0.25 <= t <= t1:
            fn(d, t, S, spec)
            push = D.PUSH * D.clamp01((t - t0) / max(0.1, t1 - t0))

    if sty:
        img = style_layer(img, t, i, stages, cams, sty, theme_colors)
        d = ImageDraw.Draw(img)
    # push-in SADECE sahne katmanina; altyazi/chrome ustte, olceksiz.
    elif push > 0.0005:
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
    if corner:
        D.draw_cta_corner(d, t, corner, corner_text)
    return img


def render(spec, tl, series_mod, out_path: Path, parallel: bool = False) -> None:
    # Tema EN BASTA secilir: D.INK, D.TONE gibi degerler buradan sonra
    # okunuyor, sonra degistirmek yarisi eski yarisi yeni renkte bir video
    # verirdi.
    from . import themes as T
    toon_on = TOON.active(spec) and hasattr(series_mod, "_group")      # karton stili: yalniz senaryodan okuyan seri
    if toon_on:
        theme = D.use_theme(TOON.stage_themes(spec["_cartoon"], 1)[0])  # sahne basina tema Toon icinde degisir
    else:
        theme = D.use_theme(T.pick(spec, _recent_themes()))
    spec["_theme"] = theme
    sty = spec.get("_style") if STYLE.active(spec) and not toon_on else None
    if sty:                                           # videoya ozgu doku (temanin kendisi ya da baska)
        D.TEXTURE = STYLE.texture_for(sty, D.TEXTURE)
    print(f"  tema: {theme}" + (f"  stil: fx={'+'.join(sty['fx'])} doku={D.TEXTURE}" if sty else ""))

    beats = tl["beats"]
    duration = tl["duration"]
    S = {b["id"]: (b["start"], b["end"]) for b in beats}
    chunks = D.build_captions(beats)
    badge_font = D.F_SEMI(26)
    stages = _stages(series_mod, S, duration, spec)
    # kapanista baslik zaten ekranda metin; altyazi onun uzerine binmesin
    close_t0 = stages[-1][0] if stages else duration

    # CTA kose etiketi (yalniz CTA'li videolarda; kapanis kartiyla cakisirsa hic cikmaz)
    corner, corner_text = None, ""
    if CTA.active(spec):
        cc = spec["_cta"]["corner"]
        corner = CTA.corner_window(duration, close_t0, cc)
        corner_text = cc.get("text", "")

    cams = STYLE.cameras(STYLE.sid_of(spec), len(stages)) if sty else None
    theme_colors = T.colors(theme)
    toon = None
    if toon_on:
        toon = TOON.Toon(spec, stages, S, duration, tl, chunks,
                         TOON.plan(spec, series_mod._group(spec["beats"])),
                         corner, corner_text, out_path.parent / "voice.wav", close_t0)
        print(f"  karton stili: tema={'+'.join(dict.fromkeys(toon.themes))}"
              f" kelime={sum(1 for p in toon.plan if p['kw'])}/{len(toon.plan)} sahne")
    bg = D.build_bg() if not toon else None
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
        if toon:
            img = toon.frame(i)
        else:
            img = _classic_frame(t, i, bg, stages, S, spec, sty, cams, theme_colors, chunks, close_t0,
                                 duration, badge_font, corner, corner_text)
        arr = np.asarray(img, dtype=np.int16) + grain[i % len(grain)]
        enc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
        if i % 200 == 0:
            print(f"  kare {i}/{nframes}", flush=True)

    enc.stdin.close()
    err = enc.stderr.read().decode()[-1500:]
    if enc.wait() != 0:
        sys.exit("ffmpeg basarisiz:\n" + err)


def _inject_brand(spec: dict, brand: dict) -> None:
    """Kapanis kartina GERCEK handle'i marka dosyasindan koy. Gemini handle
    yazmiyor (uyduruyor); elle yazilmis senaryolardaki eskimis handle de
    boylece brand.json degisince kendiliginden guncelleniyor."""
    handle = brand.get("handle", "")
    if not handle:
        return
    for b in spec.get("beats", []):
        if b.get("scene") == "close":
            b.setdefault("data", {})["handle"] = handle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--out", default="out")
    ap.add_argument("--skip-synth", action="store_true")
    args = ap.parse_args()

    spec = json.loads(Path(args.script).read_text())
    brand = load_brand(ROOT)
    _inject_brand(spec, brand)
    if CTA.apply(spec, brand, ROOT):
        print("  CTA: begen/takip cumlesi + kapanis chip'leri eklendi")
    STYLE.apply(spec, brand)                      # kamera/gecis/doku/tempo: senaryo kimliginden
    if TOON.apply(spec, brand):                   # karton/cizgi film stili (brand.json "cartoon")
        print("  karton stili: acik (kagit/lacivert, BYTE sunucu, fosforlu kelime, iris)")
    out_dir = ROOT / args.out / spec["id"]
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_synth and (out_dir / "timeline.json").exists():
        tl = json.loads((out_dir / "timeline.json").read_text())
    else:
        # Klon ses (kendi sesin) varsa Piper hic calismaz; yoksa/bozuksa Piper (brand.json > voice_clone > require
        # true ise durur: kanalin sesi sessizce degismesin).
        clone, note = CLONE.find(spec, brand, ROOT)
        need = CLONE.settings(brand)["require"]
        if clone is None and need:
            sys.exit(f"klon ses zorunlu (brand.json > voice_clone > require) ama {note or 'klon ses yok'}: "
                     f"{CLONE.root(ROOT) / spec['id']}")
        if note and clone is None:
            print(f"  {note}")
        if clone is None and not VOICE.exists():
            sys.exit(f"Ses modeli yok: {VOICE}\n  tools/fetch_voice.sh calistir")
        print("seslendirme" + (" (klon ses)..." if clone else "..."))
        tl = synthesize(spec, out_dir, VOICE, clone, need)
        # Yavas tempo videoyu QC sinirina (59 sn) yaklastirirsa varsayilan tempoya don.
        if tl["duration"] > SAFE_SECONDS and STYLE.pace(spec) != STYLE.NEUTRAL_PACE:
            print(f"  sure {tl['duration']:.1f}s > {SAFE_SECONDS:.0f}s: tempo varsayilana donuyor")
            spec["_style"]["pace"] = dict(STYLE.NEUTRAL_PACE)
            tl = synthesize(spec, out_dir, VOICE, clone, need)
    print(f"  sure: {tl['duration']:.2f}s  ses: {tl.get('voice', 'piper')}")

    series_mod = importlib.import_module(f".series_{spec['series'].lower()}", __package__)
    video = out_dir / f"{spec['id']}.mp4"
    print("kare cizimi...")
    render(spec, tl, series_mod, video)

    m = build_manifest(spec, tl, video, ROOT)
    (out_dir / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    # Instagram/TikTok'a elle yuklerken kopyalanacak metinler; release notu
    (out_dir / "captions.md").write_text(captions_markdown(m))

    problems = check(video, tl, spec, ROOT / "content/published.json")
    if problems:
        print("\nQC BASARISIZ:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print(f"\nQC temiz -> {video}")


if __name__ == "__main__":
    main()
