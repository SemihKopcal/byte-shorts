"""
Instagram/TikTok yayin defteri: content/social.json
    {"<video-id>": {"instagram": {...}, "tiktok": {...}}}

Ayni videoyu ayni platforma IKI KEZ gondermemek icin. defteri isle adimi
content/ klasorunu commit'liyor, bu dosya da onunla gidiyor.
"""
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path(root=None) -> Path:
    return Path(root or ROOT) / "content/social.json"


def _load(root=None) -> dict:
    try:
        d = json.loads(_path(root).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def done(video_id: str, platform: str, root=None) -> bool:
    return platform in _load(root).get(video_id, {})


def record(video_id: str, platform: str, info: dict, root=None) -> None:
    d = _load(root)
    d.setdefault(video_id, {})[platform] = {
        **info, "at": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")}
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, ensure_ascii=False))
