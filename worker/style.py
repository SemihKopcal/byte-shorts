"""
Video stil profili: kamera, gecis efekti, doku ve anlatim temposu.

SORUN: tema rengi degisiyordu ama geri kalan her sey ayniydi: ayni yavas yakinlasma, ayni gecis,
ayni tempo. Izleyici renk degisse bile "ayni video" hissi aliyordu.

COZUM: her videoya kendi "el yazisi" veriliyor. Hepsi SENARYO KIMLIGINDEN turetiliyor (sha256),
rastgele DEGIL: publish.yml bazi akislarda videoyu yeniden uretiyor ve iki render birebir ayni
cikmali. Ayni senaryo hep ayni profili alir; farkli senaryolar farkli profil alir.

  * kamera      : sahne basina yakinlas / uzaklas / saga kay / sola kay / yukari kay
                  (art arda iki sahne ayni hareketi yapmaz)
  * gecis efekti: videonun iki "imza" efekti var (flas, kayma, titresim, odak, zipla);
                  sahne degisimlerinde sirayla kullanilir
  * doku        : temanin kendi dokusu ya da baska bir doku
  * tempo       : bicime gore (hikaye yavas, olcum capcanli) + videoya ozgu kucuk sapma

Bu modul SAF mantik (cizim worker/fx.py'de, ses worker/synth.py'de). brand.json "style" blogu
kapatmak ya da sinirlamak icin: {"enabled": false} -> eski gorunum (yakinlasma + gecis yok).
"""
from __future__ import annotations

import hashlib

VERSION = 1

CAMERAS = ("push", "pull", "drift_l", "drift_r", "rise")
FX = ("flash", "slide", "glitch", "blur", "zoom")
TEXTURES = ("none", "grid", "dots", "scan", "contour")

# Tempo sinirlari: kapi (editorial.authored 52 sn) + CTA (~3 sn) + son pay (0.45) QC'nin 59 sn
# sinirinin altinda kalmali. Yavaslatma kucuk tutuluyor; yine de uzarsa build.py tempoyu
# varsayilana dondurur.
LENGTH_MIN, LENGTH_MAX = -0.03, 0.035
GAP_MIN, GAP_MAX = 0.90, 1.12
NEUTRAL_PACE = {"length_delta": 0.0, "gap_scale": 1.0}

# bicime gore taban: (length_scale farki, bosluk carpani)
FORMAT_PACE = {
    "story": (0.025, 1.08),        # hikaye: biraz yavas, daha cok nefes
    "explain": (0.010, 1.02),
    "measured": (-0.015, 0.94),    # olcum: capcanli
}

DEFAULTS = {"enabled": True}


def _u(sid: str, key: str) -> float:
    """sid + key'ten 0..1 arasi deterministik sayi (surumler/islemler arasi sabit)."""
    h = hashlib.sha256(f"{sid}|{key}|v{VERSION}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def _pick(sid: str, key: str, options, exclude=()):
    opts = [o for o in options if o not in exclude] or list(options)
    return opts[min(len(opts) - 1, int(_u(sid, key) * len(opts)))]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def settings(brand: dict) -> dict:
    raw = brand.get("style") if isinstance(brand.get("style"), dict) else {}
    return {"enabled": raw.get("enabled", True) is not False}


def sid_of(spec: dict) -> str:
    return str(spec.get("id") or spec.get("title") or "x")


def pace_for(spec: dict) -> dict:
    sid = sid_of(spec)
    base_len, base_gap = FORMAT_PACE.get(spec.get("format"), (0.0, 1.0))
    delta = base_len + (_u(sid, "pace_len") - 0.5) * 0.024          # +-0.012
    gap = base_gap + (_u(sid, "pace_gap") - 0.5) * 0.10              # +-0.05
    return {"length_delta": round(_clamp(delta, LENGTH_MIN, LENGTH_MAX), 4),
            "gap_scale": round(_clamp(gap, GAP_MIN, GAP_MAX), 3)}


def profile(spec: dict) -> dict:
    """Senaryodan stil profili. Yalniz id ve format'a bakar."""
    sid = sid_of(spec)
    fx_a = _pick(sid, "fx_a", FX)
    fx_b = _pick(sid, "fx_b", FX, exclude=(fx_a,))
    return {
        "v": VERSION,
        "fx": [fx_a, fx_b],
        "fx_start": int(_u(sid, "fx_start") * 2),                   # hangi imza efektle baslasin
        "texture_own": _u(sid, "tex") < 0.5,                        # True: temanin kendi dokusu
        "texture_alt": _pick(sid, "tex_alt", TEXTURES),
        "pace": pace_for(spec),
    }


def cameras(sid: str, n: int) -> list[dict]:
    """n sahnenin kamera hareketleri. Art arda ayni hareket olmaz."""
    out, prev = [], None
    for i in range(max(0, n)):
        mode = _pick(sid, f"cam{i}", CAMERAS, exclude=(prev,) if prev else ())
        amp = 0.030 + 0.025 * _u(sid, f"amp{i}")                     # 0.030 .. 0.055
        if mode.startswith("drift") or mode == "rise":
            amp = max(amp, 0.045)                                    # kaymak icin kenarlarda pay lazim
        out.append({"mode": mode, "amp": round(amp, 4)})
        prev = mode
    return out


def transition_for(prof: dict, boundary: int) -> str | None:
    """boundary = kacinci sahne degisimi (1'den baslar). Ilk sahnenin gecisi yok."""
    if boundary < 1:
        return None
    fx = prof.get("fx") or []
    if not fx:
        return None
    return fx[(boundary + int(prof.get("fx_start", 0))) % len(fx)]


def texture_for(prof: dict, theme_texture: str) -> str:
    return theme_texture if prof.get("texture_own", True) else prof.get("texture_alt", theme_texture)


def apply(spec: dict, brand: dict) -> bool:
    """Profili senaryoya (bellekte) koyar. Kapaliysa False ve spec'e dokunmaz."""
    if not settings(brand)["enabled"] or spec.get("_style"):
        return False
    spec["_style"] = profile(spec)
    return True


def active(spec: dict) -> bool:
    return bool(spec.get("_style"))


def pace(spec: dict) -> dict:
    return (spec.get("_style") or {}).get("pace") or dict(NEUTRAL_PACE)
