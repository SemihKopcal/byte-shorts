"""
Kamera hareketi ve sahne gecis efektleri (kare uzerinde, saf Pillow/numpy).

Hepsi SADECE sahne katmanina uygulanir; altyazi, BYTE rozeti ve ilerleme cubugu uzerine
cizilir ve olceksiz kalir (build.py). Her fonksiyon ayni boyutta yeni bir RGB kare dondurur.

Kamera: alt-piksel (affine) donusumu; tam sayi kirpma yavas hareketlerde titrerdi.
Gecis: u = 0..1 (efektin ilerlemesi); u >= 1 -> girdiyi aynen dondurur.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

TRANSITION_DELAY = 0.05      # sahne baslar baslamaz degil: icerik biraz belirince efekt gorunsun
TRANSITION_SECONDS = 0.45


def _ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


# ── kamera ────────────────────────────────────────────────────────────────────
def camera_state(mode: str, p: float, amp: float, w: int, h: int) -> tuple[float, float, float]:
    """(olcek, dx, dy). p = sahne ilerlemesi 0..1. Goruntu hicbir zaman kenardan tasmaz:
    kaydirma, olcegin actigi payin icinde kalir."""
    p = max(0.0, min(1.0, p))
    if mode == "push":
        return 1 + amp * p, 0.0, 0.0
    if mode == "pull":
        return 1 + amp * (1 - p), 0.0, 0.0
    s = 1 + amp
    mx, my = (w - w / s) / 2 * 0.92, (h - h / s) / 2 * 0.92
    t = (p - 0.5) * 2                                   # -1 .. +1
    if mode == "drift_l":                               # icerik sola akar
        return s, t * mx, 0.0
    if mode == "drift_r":
        return s, -t * mx, 0.0
    if mode == "rise":                                  # icerik yukari akar
        return s, 0.0, t * my
    return 1.0, 0.0, 0.0


def apply_camera(img: Image.Image, scale: float, dx: float, dy: float) -> Image.Image:
    if abs(scale - 1) < 1e-4 and abs(dx) < 1e-3 and abs(dy) < 1e-3:
        return img
    w, h = img.size
    a = 1.0 / scale
    c = w / 2 - (w / 2) * a + dx
    f = h / 2 - (h / 2) * a + dy
    return img.transform((w, h), Image.AFFINE, (a, 0, c, 0, a, f), Image.BILINEAR)


# ── gecis efektleri ───────────────────────────────────────────────────────────
def flash(img: Image.Image, u: float, tint=(255, 255, 255), seed: int = 0) -> Image.Image:
    """Kisa, yumusak parlama (temanin parlama rengine dogru). Tek vurus: strobe degil."""
    a = 0.30 * (1 - _ease_out(u)) ** 1.3
    if a <= 0.004:
        return img
    return Image.blend(img, Image.new("RGB", img.size, tuple(int(v) for v in tint)), a)


def slide(img: Image.Image, u: float, fill=(0, 0, 0), seed: int = 0) -> Image.Image:
    """Tum kare asagidan yukari oturur (kisa mesafe)."""
    off = 90 * (1 - _ease_out(u))
    if off < 0.5:
        return img
    return img.transform(img.size, Image.AFFINE, (1, 0, 0, 0, 1, -off), Image.BILINEAR, fillcolor=fill)


def glitch(img: Image.Image, u: float, seed: int = 0) -> Image.Image:
    """Kirmizi/mavi kanal kaymasi + birkac yatay serit kaymasi; hizla sonuyor."""
    k = (1 - _ease_out(u)) ** 1.6
    if k < 0.03:
        return img
    arr = np.asarray(img).copy()
    h, w, _ = arr.shape
    sh = int(round(30 * k))
    if sh:
        arr[:, :, 0] = np.roll(arr[:, :, 0], sh, axis=1)
        arr[:, :, 2] = np.roll(arr[:, :, 2], -sh, axis=1)
    rng = np.random.default_rng(1000 + int(seed))
    for _ in range(4):
        y0 = int(rng.integers(0, h - 90))
        hh = int(rng.integers(20, 90))
        shift = int(rng.integers(-1, 2) * (80 * k) + 1)
        arr[y0:y0 + hh] = np.roll(arr[y0:y0 + hh], shift, axis=1)
    return Image.fromarray(arr)


def blur(img: Image.Image, u: float, seed: int = 0) -> Image.Image:
    """Bulanikliktan netlige."""
    r = 16.0 * (1 - _ease_out(u)) ** 1.6
    if r < 0.4:
        return img
    return img.filter(ImageFilter.GaussianBlur(r))


def zoom(img: Image.Image, u: float, seed: int = 0) -> Image.Image:
    """Hizli 'zipla': 1.09x'ten 1.0x'e oturur."""
    s = 1 + 0.09 * (1 - _ease_out(u)) ** 1.3
    return apply_camera(img, s, 0.0, 0.0)


def transition(img: Image.Image, kind: str | None, u: float, theme=None, seed: int = 0) -> Image.Image:
    """kind: style.FX'ten biri. Bilinmeyen/None/bitmis (u>=1) -> girdi aynen."""
    if not kind or u >= 1.0 or u < 0:
        return img
    if kind == "flash":
        return flash(img, u, tint=(theme or {}).get("glow", (255, 255, 255)))
    if kind == "slide":
        return slide(img, u, fill=(theme or {}).get("bg0", (0, 0, 0)))
    if kind == "glitch":
        return glitch(img, u, seed)
    if kind == "blur":
        return blur(img, u)
    if kind == "zoom":
        return zoom(img, u)
    return img
