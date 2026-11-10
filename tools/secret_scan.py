#!/usr/bin/env python3
"""
Depoda sir (token, anahtar, parola) var mi?

Depo PUBLIC: bir kez commit'lenen sir silinse bile gecmiste kalir ve herkes okur.
Bu arac iki sey yapar:

  python tools/secret_scan.py             git'in izledigi dosyalari tarar (CI'da her push'ta)
  python tools/secret_scan.py --history   TUM commit gecmisinde eklenen satirlari tarar
                                          (haftalik audit'te ve elle)

Neyi bulur: saglayici bicimi belli olanlar (GitHub, Google, Slack, AWS, Meta/Instagram,
Cloudflare tunel token'i, JWT, ozel anahtar bloklari) ve `token = "..."` gibi atamalarda
yuksek entropili uzun degerler.

Bulunan DEGERI ASLA yazdirmaz: yalniz dosya, satir ve tur. (CI gunlugu da public.)

Yanlis alarm: satira `secret-scan: allow` yorumu ekle. Ornek/yer tutucu degerler
(example, dummy, changeme, your, xxx ...) kendiliginden atlanir. `tests/` altinda yalniz
saglayici desenleri aranir (sahte token'lar parca parca birlestirilerek yazilir).

Cikis kodu: 0 temiz, 1 bulundu, 2 kullanim hatasi.
"""
from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Saglayici bicimleri: yuksek guven.
PROVIDER = [
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("Google API anahtari", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Google OAuth istemci sirri", re.compile(r"\bGOCSPX-[0-9A-Za-z_\-]{20,}")),
    ("Google yenileme token'i", re.compile(r"\b1//0[0-9A-Za-z_\-]{40,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,}")),
    ("AWS erisim anahtari", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Meta/Instagram token", re.compile(r"\b(?:EAA|IGAA|IGQ)[A-Za-z0-9]{40,}")),
    ("JWT / Cloudflare tunel token'i", re.compile(r"\beyJ[A-Za-z0-9_\-=]{60,}")),
    ("Ozel anahtar blogu", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
]

# `token = "uzun_deger"` gibi atamalar
ASSIGN = re.compile(
    r"""(?ix)\b(?:secret|token|passw(?:or)?d|passwd|api[_-]?key|client[_-]?secret|private[_-]?key|access[_-]?key)
        \w*\s*[:=]\s*["']([A-Za-z0-9/+_\-=.]{24,})["']""")

PLACEHOLDER = re.compile(
    r"(?i)example|dummy|changeme|change-me|placeholder|your[_-]|xxxx|redacted|sample|fake|"
    r"ci-dummy|<.*>|\$\{|%s|\{\{|HESAP|TAKIM|ACCESS_UYG")
ALLOW = "secret-scan: allow"

SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp4", ".wav", ".mp3", ".onnx",
               ".otf", ".ttf", ".woff", ".woff2", ".zip", ".gz", ".xz", ".pdf", ".db", ".sqlite"}
SKIP_DIRS = {".git", "out", "node_modules", "__pycache__", ".venv", "venv", "voices"}
MAX_BYTES = 1_500_000
MIN_ENTROPY = 3.6                      # base64/hex rastgele dizgiler ~4+; kelimeler ~3


def entropy(s: str) -> float:
    if not s:
        return 0.0
    return -sum((s.count(c) / len(s)) * math.log2(s.count(c) / len(s)) for c in set(s))


def scan_line(line: str, generic: bool = True) -> list[str]:
    """Bu satirda bulunan sir TURLERI (deger donmez)."""
    if ALLOW in line:
        return []
    found = []
    for kind, rx in PROVIDER:
        for m in rx.finditer(line):
            if not PLACEHOLDER.search(m.group(0)):
                found.append(kind)
    if generic:
        for m in ASSIGN.finditer(line):
            v = m.group(1)
            if PLACEHOLDER.search(v) or PLACEHOLDER.search(line):
                continue
            if entropy(v) >= MIN_ENTROPY and re.search(r"\d", v) and re.search(r"[A-Za-z]", v):
                found.append("yuksek entropili atama")
    return found


def tracked_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                             capture_output=True, check=True).stdout
        return [root / p for p in out.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for p in root.rglob("*"):
            if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS):
                files.append(p)
        return files


def scan_tree(root: Path = ROOT) -> list[tuple[str, int, str]]:
    findings = []
    for p in tracked_files(root):
        rel = p.relative_to(root)
        if p.suffix.lower() in SKIP_SUFFIX or set(rel.parts) & SKIP_DIRS:
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        generic = rel.parts[0] != "tests"
        for n, line in enumerate(text.splitlines(), 1):
            for kind in scan_line(line, generic):
                findings.append((str(rel), n, kind))
    return findings


def scan_history(root: Path = ROOT) -> list[tuple[str, int, str]]:
    """Tum dallarin tum commit'lerinde EKLENEN satirlar. (dosya@commit, satir, tur)"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "--all", "-p", "-U0", "--no-color",
             "--format=commit:%H"],
            capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"git gecmisi okunamadi: {e}")
    findings, seen = [], set()
    commit, path, lineno = "", "", 0
    for raw in proc.stdout.decode("utf-8", "replace").splitlines():
        if raw.startswith("commit:"):
            commit = raw[7:19]
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
            lineno = 0
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) - 1 if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            lineno += 1
            suffix = Path(path).suffix.lower()
            if suffix in SKIP_SUFFIX or Path(path).parts[:1] == ("out",):
                continue
            generic = Path(path).parts[:1] != ("tests",)
            for kind in scan_line(raw[1:], generic):
                key = (path, kind, commit)
                if key not in seen:
                    seen.add(key)
                    findings.append((f"{path}@{commit}", lineno, kind))
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--history", action="store_true", help="tum commit gecmisini tara")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = Path(args.root)
    findings = scan_history(root) if args.history else scan_tree(root)
    what = "commit gecmisi" if args.history else "izlenen dosyalar"
    if not findings:
        print(f"secret taramasi temiz ({what})")
        return 0
    print(f"SIR OLABILECEK {len(findings)} bulgu ({what}); degerler gizlendi:")
    for where, n, kind in findings:
        print(f"  {where}:{n}  {kind}")
    print("\nGercekse: sirri HEMEN iptal et/yenile (silmek yetmez, gecmiste kalir), sonra dosyadan cikar."
          "\nYanlis alarmsa: satira  # secret-scan: allow  ekle.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
