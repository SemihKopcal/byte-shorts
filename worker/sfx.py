"""
Kucuk ses efektleri (tik, whoosh, ding, thud) -- karton modunda sahne gecislerine, fosforlu kelimelere ve
dogru/yanlis isaretlerine eslik eder.

NEDEN: ses yalniz konusmadan ibaretti; ekrandaki hareket (iris acilmasi, kelimenin belirmesi, tik cizilmesi)
sessiz kaliyordu. Aciklayici cizgi film kanallarinin "tik / vuvv / ding" dokunuslari sesi canli tutuyor.

KURALLAR (testlerle kilitli):
  * KODLA URETILIR: numpy ile sentez; ses dosyasi, ornek (sample) ya da lisansli paket yok.
  * KIMLIKTEN/ZAMANDAN SABIT: gurultu icin sabit tohum; iki render birebir ayni baytlari verir.
  * SESIN USTUNE BINMEZ: efekt, konusmanin o anki tepe degerinden kalan bosluga SIGDIRILIR
    (|ses| + |efekt| <= LIMIT); yani sesin tepe seviyesi (loudnorm TP -1.5) asla asilmaz, kirpilma olmaz.
  * DUSUK SEVIYE: efektlerin tepesi ~ -18 dBFS (GAIN_DEFAULT ile olceklenir); konusma her zaman onde.
  * HICBIR ZAMAN RENDER'I DUSURMEZ: ses dosyasi okunamazsa/uyumsuzsa mix() None doner, orijinal ses kullanilir.
Acma/kapama: brand.json "cartoon": {"sfx": true, "sfx_gain": 0.6}.
"""
from __future__ import annotations

import math
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

SR = 48000
LIMIT = 0.84                  # ~ -1.5 dBFS: voice.wav'in loudnorm tepe siniri
GAIN_DEFAULT = 0.6
GAIN_MAX = 1.5
KINDS = ("tik", "whoosh", "ding", "thud")


def _env(n: int, attack: float, tau: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / tau)


@lru_cache(maxsize=8)
def synth(kind: str) -> np.ndarray:
    """Mono float32 efekt (|x| <= ~0.2). Ayni kind her zaman ayni dizi."""
    if kind not in KINDS:
        raise ValueError(f"bilinmeyen efekt: {kind}")
    if kind == "tik":
        n = int(0.07 * SR)
        t = np.arange(n) / SR
        x = (np.sin(2 * np.pi * 1800 * t) + 0.3 * np.sin(2 * np.pi * 3600 * t)) * _env(n, 0.002, 0.012) * 0.16
    elif kind == "ding":
        n = int(0.55 * SR)
        t = np.arange(n) / SR
        x = (np.sin(2 * np.pi * 1318.5 * t) + 0.6 * np.sin(2 * np.pi * 1975.5 * t)
             + 0.2 * np.sin(2 * np.pi * 2637 * t)) * _env(n, 0.004, 0.13) * 0.09
    elif kind == "thud":
        n = int(0.22 * SR)
        t = np.arange(n) / SR
        f = 150 - 70 * np.minimum(1.0, t / 0.12)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.003, 0.07) * 0.2
    else:                                                       # whoosh: suzulen filtreli gurultu
        n = int(0.38 * SR)
        rng = np.random.default_rng(20260713)
        noise = rng.standard_normal(n).astype(np.float64)
        u = np.arange(n) / n
        a = 0.015 + 0.20 * np.sin(np.pi * u) ** 2               # alcak geciren katsayisi: acilip kapanir
        y = np.empty(n)
        acc = 0.0
        for i in range(n):
            acc += a[i] * (noise[i] - acc)
            y[i] = acc
        x = y * np.sin(np.pi * u) ** 2
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.14
    return x.astype(np.float32)


def read_voice(path):
    """voice.wav -> (float32 [n, 2], sr) ya da None (okunamadi / 16 bit degil / 48k degil)."""
    try:
        with wave.open(str(path)) as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw != 2 or sr != SR or ch not in (1, 2):
            return None
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        x = x[: len(x) // ch * ch].reshape(-1, ch)
        return (np.repeat(x, 2, axis=1) if ch == 1 else x), sr
    except Exception:                                           # noqa: BLE001 - render'i dusurme
        return None


def gain_of(v) -> float:
    try:
        g = float(v)
    except (TypeError, ValueError, OverflowError):
        return GAIN_DEFAULT
    return min(GAIN_MAX, max(0.0, g)) if g == g else GAIN_DEFAULT


def render(voice: np.ndarray, events, gain: float = GAIN_DEFAULT) -> np.ndarray:
    """voice [n, 2] float32 + events [(saniye, tur)] -> karisim [n, 2]. Efekt konusmanin altindaki bosluga sigdirilir."""
    n = len(voice)
    fx = np.zeros(n, np.float32)
    for t, kind in events:
        try:
            t = float(t)
            snd = synth(kind)
            s = int(round(t * SR)) if math.isfinite(t) else -1
        except (TypeError, ValueError, OverflowError):
            continue
        if s < 0 or s >= n:
            continue
        seg = snd[: n - s]
        fx[s:s + len(seg)] += seg
    fx *= gain
    head = np.maximum(0.0, LIMIT - np.max(np.abs(voice), axis=1))          # her ornekte kalan bosluk
    fx = np.clip(fx, -head, head)
    return voice + fx[:, None]


def mix(voice_path, events, out_path, gain=GAIN_DEFAULT):
    """voice.wav + efektler -> out_path (16 bit 48k stereo). Doner: out_path ya da None (efekt eklenemedi)."""
    if not events:
        return None
    got = read_voice(voice_path)
    if got is None:
        return None
    voice, _sr = got
    out = render(voice, events, gain_of(gain))
    pcm = np.clip(np.rint(out * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return Path(out_path)
