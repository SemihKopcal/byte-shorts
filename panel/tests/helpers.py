"""Test yardimcilari. Ag YOK: depo MemoryStorage, GitHub sahte, saat elle."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from bytepanel import config
from bytepanel.db import Db, iso
from bytepanel.service import Service, keys_for
from bytepanel.storage import MemoryStorage


class Clock:
    def __init__(self, y=2026, mo=11, d=8, h=15, mi=0):
        self.t = datetime(y, mo, d, h, mi, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def set(self, *a):
        self.t = datetime(*a, tzinfo=timezone.utc)


class FakeGitHub:
    def __init__(self):
        self.calls: list[dict] = []
        self.fail: Exception | None = None
        self.on_dispatch = None            # (inputs) -> None, DB durumunu denetlemek icin
        # takvim icin: siradaki senaryolar (secim sirasiyla) ve A/B kollari
        self.queue = [f"p{n:03d}-sira-{n}" for n in range(40, 49)]
        self.arm_info: dict[str, dict] = {}
        self.legend: list[dict] = []
        self.fail_queue: Exception | None = None

    def dispatch(self, inputs):
        if self.on_dispatch:
            self.on_dispatch(inputs)
        if self.fail:
            raise self.fail
        self.calls.append(dict(inputs))

    def ping(self):
        pass

    def latest_run(self, wf):
        return {"status": "completed", "conclusion": "success",
                "created_at": "2026-11-08T14:34:36Z", "url": "https://github.com/o/r/actions/runs/1"}

    def queue_left(self):
        return {"total": 10, "left": 9}

    def queue_info(self):
        if self.fail_queue:
            raise self.fail_queue
        return {"total": len(self.queue) + 3, "queue": list(self.queue)}

    def experiments(self):
        return {"arm_info": dict(self.arm_info), "legend": list(self.legend)}


def test_config(**over):
    env = {"PANEL_ENV": "test"}
    env.update(over)
    return config.load(env)


def make_service(clock=None, **cfg_over):
    clock = clock or Clock()
    db = Db(":memory:")
    storage = MemoryStorage()
    gh = FakeGitHub()
    svc = Service(db, storage, gh, test_config(**cfg_over), clock=clock)
    return svc, storage, gh, clock


def put_video(storage, sid, rendered="2026-11-08T14:37:00Z", **over):
    """R2'ye 3 dosya + inbox kaydi koyar (CI'nin yaptigi sey)."""
    for k in keys_for(sid).values():
        storage.put_bytes(k, b"x", "application/octet-stream")
    rec = {"v": 1, "script_id": sid, "title": f"Video {sid}", "series": "G",
           "duration": 37.2, "size_bytes": 1234, "sha256": "a" * 64,
           "rendered_at": rendered, "run_url": "https://github.com/o/r/actions/runs/1"}
    rec.update(over)
    storage.put_bytes(f"inbox/{sid}.json", json.dumps(rec).encode())
    return rec


def put_result(storage, sid, platform, request_id, ok=True, **over):
    rec = {"v": 1, "request_id": request_id, "script_id": sid, "platform": platform,
           "ok": ok, "remote_id": "abc123", "remote_url": "https://youtu.be/abc123",
           "error": "", "at": "2026-11-08T15:10:00Z"}
    rec.update(over)
    storage.put_bytes(f"results/{sid}.{platform}.json", json.dumps(rec).encode())
    return rec


def pubs(svc, sid):
    return {r["platform"]: dict(r) for r in svc.publications(sid)}


__all__ = ["Clock", "FakeGitHub", "make_service", "put_video", "put_result", "pubs", "iso"]
