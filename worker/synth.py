"""
Seslendirme + zaman cizelgesi.

Her beat AYRI sentezleniyor. Sebebi: boylece her cumlenin baslangic ve bitis
saniyesi TAM olarak biliniyor ve gorsel kesmeler bu zamanlara oturuyor. Tek
parca sentezleyip sonradan hizalamaya calismak (forced alignment) hem fazladan
model indirmek hem de hata payi demek.

Altyazi metni seslendirme metninden AYRI (`cap` vs `say`): TTS'e "three dollars"
yazmak zorundayiz ki rakami dogru okusun, ama ekranda "$3" gorunmeli.
"""
import json
import re
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

GAP = 0.18           # beat'ler arasi nefes payi (sn)
END_PAD = 0.45       # son kelimeden sonra video + ses bu kadar sessiz surer (son kelime kesilmesin)
SR = 22050
MAX_SECONDS = 59     # Shorts tavani degil, bizim QC esigimiz


def _syllables(w: str) -> int:
    w = re.sub(r"[^a-z]", "", w.lower())
    if not w:
        return 1
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def _run(cmd, **kw):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, **kw)


# ── ritim ────────────────────────────────────────────────────────────────────
# Robotluk hissinin yarisi sesin kendisinden degil, DURAKLARDAN geliyordu:
# her cumleden sonra ayni 0.18 sn. Insan noktadan sonra uzun, virgulden sonra
# kisa duruyor. Asagidaki tablo o farki geri koyuyor.
GAP_END = 0.30        # nokta
GAP_ASK = 0.34        # soru/unlem -- cevap beklenen bosluk
GAP_MID = 0.13        # virgul ya da noktalama yok: cumle devam ediyor
GAP_SCENE = 0.12      # sahne degisiyorsa ustune eklenen pay

# Piper varsayilanlari her cumleyi ayni kalipta okuyor. length-scale biraz
# yavaslatiyor (gencler icin degil, ANLASILIRLIK icin: ekranda ayni anda
# rakam var), noise-w fonem sureleri arasinda varyasyon birakiyor.
LENGTH_SCALE = 1.06
NOISE_SCALE = 0.68
NOISE_W = 0.90
# Ardisik cumleler birebir ayni tempoda olmasin diye beat sirasina gore
# minik bir sapma. RASTGELE DEGIL -- publish adimi videoyu yeniden uretiyor,
# iki render birebir ayni cikmali.
JITTER = (0.0, 0.03, -0.02, 0.015, -0.03, 0.02)


def _gap_after(beat: dict, nxt: dict | None) -> float:
    if nxt is None:
        return 0.0
    s = (beat.get("say") or "").rstrip()
    if s.endswith(("?", "!")):
        g = GAP_ASK
    elif s.endswith((".", ":", "—")):
        g = GAP_END
    else:
        g = GAP_MID
    if nxt.get("scene") and nxt.get("scene") != beat.get("scene"):
        g += GAP_SCENE
    return round(g, 3)


@lru_cache(maxsize=1)
def _piper_flags() -> tuple:
    """Piper surumleri bayrak adlarini degistiriyor: 1.2'de --noise_w,
    sonrakilerde --noise-w-scale. Sabit yazmak yerine --help'e soruyoruz,
    yoksa surum degisince hat sessizce degil ama gurultulu sekilde oluyor."""
    try:
        h = subprocess.run(["piper", "--help"], capture_output=True,
                           text=True, timeout=20).stdout
    except Exception:
        return ()
    out = []
    # her ayar icin kabul edilen yazimlar, tercih sirasiyla
    for spellings in (("--length-scale", "--length_scale"),
                      ("--noise-scale", "--noise_scale"),
                      ("--noise-w-scale", "--noise_w_scale", "--noise-w",
                       "--noise_w")):
        for name in spellings:
            if name in h:
                out.append(name)
                break
    return tuple(out)


def _piper(text: str, path: Path, voice: Path, i: int = 0, shift: float = 0.0) -> float:
    cmd = ["piper", "-m", str(voice), "-c", str(voice) + ".json"]
    ls = LENGTH_SCALE + JITTER[i % len(JITTER)] + shift     # shift: videoya ozgu tempo (style.py)
    for f in _piper_flags():
        k = f.lstrip("-").replace("_", "-")
        v = f"{ls:.3f}" if k.startswith("length") else \
            str(NOISE_W) if "w" in k.split("-") else str(NOISE_SCALE)
        cmd += [f, v]
    cmd += ["-f", str(path)]
    _run(cmd, input=text.encode())
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def synthesize(spec: dict, out_dir: Path, voice: Path) -> dict:
    """Beat'leri seslendirir, tek ses dosyasi + zaman cizelgesi uretir."""
    seg = out_dir / "seg"
    seg.mkdir(parents=True, exist_ok=True)

    beats = spec["beats"]
    pace = (spec.get("_style") or {}).get("pace") or {}
    shift = float(pace.get("length_delta", 0.0))
    gscale = float(pace.get("gap_scale", 1.0))
    gaps = [round(_gap_after(b, beats[i + 1] if i + 1 < len(beats) else None) * gscale, 3)
            for i, b in enumerate(beats)]

    t = 0.0
    timeline, parts = [], []
    for i, beat in enumerate(beats):
        p = seg / f"{i:02d}.wav"
        dur = _piper(beat["say"], p, voice, i, shift) if shift else _piper(beat["say"], p, voice, i)
        parts.append(p)

        words = beat.get("cap", beat["say"]).split()
        weights = [_syllables(w) for w in words]
        total = sum(weights) or 1
        wt, acc = [], 0.0
        for w, wg in zip(words, weights):
            d = dur * wg / total
            wt.append({"w": w.strip(".,"), "s": round(t + acc, 3),
                       "e": round(t + acc + d, 3)})
            acc += d

        timeline.append({"id": beat["id"], "scene": beat.get("scene", ""),
                         "say": beat["say"], "start": round(t, 3),
                         "end": round(t + dur, 3), "words": wt})
        t += dur + gaps[i]

    # Her farkli bosluk uzunlugu icin bir sessizlik dosyasi. Tek bir sabit
    # dosya yerine bunlar, cunku duraklar artik noktalamaya gore degisiyor.
    sils = {}
    for g in sorted(set(x for x in gaps if x > 0)):
        f = out_dir / f"sil_{int(g * 1000)}.wav"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono",
              "-t", str(g), "-c:a", "pcm_s16le", str(f)])
        sils[g] = f
    # concat listesinde MUTLAK yol: ffmpeg goreli yollari liste dosyasinin
    # bulundugu dizine gore cozuyor, cwd'ye gore degil.
    lines = []
    for i, p in enumerate(parts):
        lines.append(f"file '{p.resolve()}'")
        if i < len(parts) - 1 and gaps[i] > 0:
            lines.append(f"file '{sils[gaps[i]].resolve()}'")
    concat = out_dir / "concat.txt"
    concat.write_text("\n".join(lines))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
          "-c", "copy", str(out_dir / "voice_raw.wav")])
    # Video, SON KELIMEDEN END_PAD sonra biter. (Eskiden t - GAP'ti: son beat'ten sonra bosluk 0
    # oldugu icin video sesten 0.18 sn ONCE bitiyor, son kelimenin sonu kesiliyordu.)
    duration = round(timeline[-1]["end"] + END_PAD, 3)
    # -14 LUFS: Shorts'un fiili standardi. Bu adimin yoklugu amator isi
    # amator yapan seylerin basinda geliyor. apad: ses dosyasi videoyla ayni uzunlukta bitsin
    # (-shortest ile kesilmesin).
    _run(["ffmpeg", "-y", "-i", str(out_dir / "voice_raw.wav"),
          "-af", f"highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11,apad=whole_dur={duration}",
          "-ar", "48000", "-ac", "2", str(out_dir / "voice.wav")])

    tl = {"duration": duration, "beats": timeline}
    (out_dir / "timeline.json").write_text(json.dumps(tl, indent=1))
    return tl
