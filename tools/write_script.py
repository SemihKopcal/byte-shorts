#!/usr/bin/env python3
"""Eski giris noktasi. Konu motoru artik editorial/ paketinde:

    python -m editorial [--topic "..."] [--dry-run]

Bu dosya yalnizca eski komutlar ve notlar kirilmasin diye duruyor.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from editorial.pipeline import main  # noqa: E402

if __name__ == "__main__":
    main()
