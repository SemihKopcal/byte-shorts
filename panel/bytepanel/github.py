"""
GitHub Actions ile konusma. Panel yalniz iki sey yapar:
  - panel-publish workflow'unu tetiklemek (workflow_dispatch)
  - son kosularin durumunu okumak (servis sagligi)

Token: tek depo, ince ayarli (fine-grained): Actions yaz/oku + Contents oku.
Baska hicbir yetki yok; platform token'lari (YouTube/Instagram/TikTok) bu
sunucuya HIC gelmez, GitHub Secrets'ta kalir.
"""
from __future__ import annotations

import json
import re

import httpx


class GitHubError(RuntimeError):
    pass


QUEUE_FILE = re.compile(r"^(p\d{3}-[a-z0-9-]+)\.json\Z")


class GitHub:
    def __init__(self, repo: str, token: str, workflow: str, ref: str, transport=None):
        self.repo, self.workflow, self.ref = repo, workflow, ref
        self._token, self._transport = token, transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url="https://api.github.com", timeout=10.0, transport=self._transport,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {self._token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "byte-panel"})

    def _get(self, path: str, **kw):
        try:
            with self._client() as c:
                r = c.get(path, **kw)
        except httpx.HTTPError as e:
            raise GitHubError(f"ulasilamadi: {type(e).__name__}") from None
        if r.status_code != 200:
            raise GitHubError(f"HTTP {r.status_code} {path}")
        return r

    def dispatch(self, inputs: dict) -> None:
        body = {"ref": self.ref, "inputs": {k: str(v) for k, v in inputs.items()}}
        try:
            with self._client() as c:
                r = c.post(f"/repos/{self.repo}/actions/workflows/{self.workflow}/dispatches",
                           json=body)
        except httpx.HTTPError as e:
            raise GitHubError(f"ulasilamadi: {type(e).__name__}") from None
        if r.status_code != 204:
            raise GitHubError(f"dispatch HTTP {r.status_code}")

    def ping(self) -> None:
        self._get(f"/repos/{self.repo}")

    def latest_run(self, workflow_file: str) -> dict | None:
        r = self._get(f"/repos/{self.repo}/actions/workflows/{workflow_file}/runs",
                      params={"per_page": 1})
        runs = r.json().get("workflow_runs", [])
        if not runs:
            return None
        x = runs[0]
        return {"status": x.get("status"), "conclusion": x.get("conclusion"),
                "created_at": x.get("created_at"), "url": x.get("html_url", "")}

    def queue_left(self) -> dict:
        """Kuyrukta (p001-...) islenmemis senaryo sayisi. Tahmin: dosya adi = id."""
        listing = self._get(f"/repos/{self.repo}/contents/content/scripts",
                            params={"ref": self.ref}).json()
        ids = {m.group(1) for it in listing
               if (m := QUEUE_FILE.match(str(it.get("name", ""))))}
        done: set[str] = set()
        for name in ("built.json", "published.json"):
            try:
                raw = self._get(f"/repos/{self.repo}/contents/content/{name}",
                                params={"ref": self.ref},
                                headers={"Accept": "application/vnd.github.raw+json"}).text
                data = json.loads(raw or "[]")
            except (GitHubError, ValueError):
                continue
            for x in data:
                done.add(x if isinstance(x, str) else str(x.get("id", "")))
        return {"total": len(ids), "left": len(ids - done)}
