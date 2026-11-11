"""
Hazir seslendirme: kullanicinin KENDI sesinin klonu (Chatterbox, Colab'da toplu uretilir).

Piper her render'da CPU'da cumle cumle ses uretir. Klon ses GPU ister; o yuzden Actions'ta
uretilmez: Colab'da (tools/voice_lines.py'nin verdigi cumlelerle) onceden uretilip private R2'ye
konur, daily render'dan once indirir (tools/r2_voice.py), burasi yalniz KULLANIR.

Sozlesme -- senaryo basina bir dizin (varsayilan voices/clone/<senaryo-id>/, kok BYTE_CLONE_DIR):

    manifest.json   {"v": 1, "voice": "semih", "beats": {"b1": {"sha": "..."}, ..., "cta": {...}}}
    <beat-id>.wav   o beat'in `say` metninin sesi (tek cumle)

`sha` = say metninin ozeti. Metin sonradan degistiyse (senaryo ya da brand.json'daki CTA cumlesi)
eski ses yanlis cumleyi okur; bu yuzden ESLESMEZSE o senaryo icin klon KULLANILMAZ (Piper'a doner,
ya da brand.json > voice_clone > require ise render durur). Yarim klon yok: bir videoda iki ses olmaz.

Hicbir sey rastgele degil: ayni dosyalar -> ayni video (publish.yml videoyu yeniden uretiyor).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

VERSION = 1
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")     # senaryo ve beat kimlikleri (dosya adi olur)
MIN_SECONDS = 0.15                                              # bundan kisa ses = bos/bozuk dosya
TEMPO_RANGE = (0.85, 1.15)                                      # style.py temposu bunun disina cikmaz


def settings(brand: dict) -> dict:
    raw = brand.get("voice_clone") if isinstance(brand.get("voice_clone"), dict) else {}
    return {"enabled": raw.get("enabled") is not False, "require": raw.get("require") is True}


def root(repo_root: Path) -> Path:
    env = os.environ.get("BYTE_CLONE_DIR", "").strip()
    return Path(env) if env else Path(repo_root) / "voices" / "clone"


def say_sha(say: str) -> str:
    """Bosluk farklari sayilmasin; metin degisince ozet degissin."""
    return hashlib.sha1(" ".join(str(say).split()).encode()).hexdigest()[:16]


def lines(spec: dict) -> list[dict]:
    """Seslendirilecek cumleler, build'in synth'e verdigi sirayla (CTA cumlesi dahil)."""
    return [{"id": b["id"], "say": b["say"]} for b in spec.get("beats", [])]


def make_manifest(spec: dict, voice: str = "") -> dict:
    return {"v": VERSION, "voice": voice,
            "beats": {b["id"]: {"sha": say_sha(b["say"])} for b in lines(spec)}}


def check(spec: dict, d: Path) -> str:
    """'' = dizin bu senaryo icin kullanilabilir; degilse nedeni (tek satir)."""
    try:
        man = json.loads((Path(d) / "manifest.json").read_text())
    except (OSError, ValueError):
        return "manifest.json okunamadi"
    if not isinstance(man, dict) or man.get("v") != VERSION or not isinstance(man.get("beats"), dict):
        return "manifest surumu/bicimi tanimsiz"
    for b in lines(spec):
        if not SAFE_ID.match(str(b["id"])):
            return f"gecersiz beat kimligi: {b['id']!r}"
        rec = man["beats"].get(b["id"])
        if not isinstance(rec, dict):
            return f"{b['id']}: manifest'te yok"
        if rec.get("sha") != say_sha(b["say"]):
            return f"{b['id']}: cumle degismis (ses eski metne ait)"
        if not (Path(d) / f"{b['id']}.wav").is_file():
            return f"{b['id']}.wav yok"
    return ""


def find(spec: dict, brand: dict, repo_root: Path) -> tuple[Path | None, str]:
    """(dizin, not). dizin None ise Piper kullanilir. not bos degilse kullaniciya soylenmeli."""
    cfg = settings(brand)
    if not cfg["enabled"]:
        return None, ""
    sid = str(spec.get("id", ""))
    d = root(repo_root) / sid
    if not SAFE_ID.match(sid) or not (d / "manifest.json").is_file():
        return None, ("klon ses yok" if sid else "")
    why = check(spec, d)
    if why:
        return None, f"klon ses kullanilamiyor: {why}"
    return d, ""


def tempo_for(shift: float, length_scale: float) -> float:
    """Piper'in length_scale kaymasinin (style.pace) klon ses karsiligi: atempo carpani."""
    if not shift:
        return 1.0
    return max(TEMPO_RANGE[0], min(TEMPO_RANGE[1], length_scale / (length_scale + shift)))


def prepare(src: Path, dst: Path, sr: int, tempo: float = 1.0) -> float:
    """Klon sesi synth'in bekledigi bicime getirir (mono, `sr` Hz, 16 bit), bastaki/sondaki sessizligi
    keser (uretici bazen yarim saniye bosluk birakiyor; duraklari synth kendi koyar), tempoyu uygular.
    Doner: sure (sn). Bozuk/bos dosyada ValueError."""
    trim = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.04,areverse,"
            "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.06,areverse")
    af = trim + (f",atempo={tempo:.4f}" if abs(tempo - 1.0) > 1e-3 else "")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", af,
                        "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise ValueError(f"{Path(src).name}: ses dosyasi okunamadi") from e
    import wave
    try:
        with wave.open(str(dst)) as w:
            dur = w.getnframes() / w.getframerate()
    except (wave.Error, EOFError) as e:
        raise ValueError(f"{Path(src).name}: ses dosyasi bos") from e
    if dur < MIN_SECONDS:
        raise ValueError(f"{Path(src).name}: ses {dur:.2f} sn, bos gibi")
    return dur
