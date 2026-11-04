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
from pathlib import Path

GAP = 0.18           # beat'ler arasi nefes payi (sn)
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


def _piper(text: str, path: Path, voice: Path) -> float:
    _run(["piper", "-m", str(voice), "-c", str(voice) + ".json", "-f", str(path)],
         input=text.encode())
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def synthesize(spec: dict, out_dir: Path, voice: Path) -> dict:
    """Beat'leri seslendirir, tek ses dosyasi + zaman cizelgesi uretir."""
    seg = out_dir / "seg"
    seg.mkdir(parents=True, exist_ok=True)

    t = 0.0
    timeline, parts = [], []
    for i, beat in enumerate(spec["beats"]):
        p = seg / f"{i:02d}.wav"
        dur = _piper(beat["say"], p, voice)
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
        t += dur + GAP

    # tek parca ses
    sil = out_dir / "sil.wav"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono",
          "-t", str(GAP), "-c:a", "pcm_s16le", str(sil)])
    # concat listesinde MUTLAK yol: ffmpeg goreli yollari liste dosyasinin
    # bulundugu dizine gore cozuyor, cwd'ye gore degil.
    lines = []
    for i, p in enumerate(parts):
        lines.append(f"file '{p.resolve()}'")
        if i < len(parts) - 1:
            lines.append(f"file '{sil.resolve()}'")
    concat = out_dir / "concat.txt"
    concat.write_text("\n".join(lines))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
          "-c", "copy", str(out_dir / "voice_raw.wav")])
    # -14 LUFS: Shorts'un fiili standardi. Bu adimin yoklugu amator isi
    # amator yapan seylerin basinda geliyor.
    _run(["ffmpeg", "-y", "-i", str(out_dir / "voice_raw.wav"),
          "-af", "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11",
          "-ar", "48000", "-ac", "2", str(out_dir / "voice.wav")])

    duration = round(t - GAP, 3)
    tl = {"duration": duration, "beats": timeline}
    (out_dir / "timeline.json").write_text(json.dumps(tl, indent=1))
    return tl
