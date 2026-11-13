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

from . import plan
from .config import SLUG


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

    def dispatch(self, inputs: dict, workflow: str | None = None) -> None:
        """workflow verilmezse yayin workflow'u (panel-publish); senaryo islemleri icin panel-scripts."""
        wf = workflow or self.workflow
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.ya?ml", wf):
            raise GitHubError("workflow adi gecersiz")
        body = {"ref": self.ref, "inputs": {k: str(v) for k, v in inputs.items()}}
        try:
            with self._client() as c:
                r = c.post(f"/repos/{self.repo}/actions/workflows/{wf}/dispatches",
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

    def _content_json(self, name: str):
        """content/<name> icindeki JSON; yok/bozuksa None (cagiran 'bos' sayar)."""
        try:
            raw = self._get(f"/repos/{self.repo}/contents/content/{name}",
                            params={"ref": self.ref},
                            headers={"Accept": "application/vnd.github.raw+json"}).text
            return json.loads(raw or "null")
        except (GitHubError, ValueError):
            return None

    def _scripts_and_done(self) -> tuple[set[str], set[str]]:
        listing = self._get(f"/repos/{self.repo}/contents/content/scripts",
                            params={"ref": self.ref}).json()
        ids = {m.group(1) for it in listing
               if (m := QUEUE_FILE.match(str(it.get("name", ""))))}
        done: set[str] = set()
        for name in ("built.json", "published.json"):
            data = self._content_json(name)
            for x in data if isinstance(data, list) else []:
                done.add(x if isinstance(x, str) else str(x.get("id", "")) if isinstance(x, dict) else "")
        return ids, done

    def queue_left(self) -> dict:
        """Kuyrukta (p001-...) islenmemis senaryo sayisi. Tahmin: dosya adi = id."""
        ids, done = self._scripts_and_done()
        return {"total": len(ids), "left": len(ids - done)}

    def queue_info(self) -> dict:
        """Siradaki senaryolar, tools/pick_script.py ile AYNI sirayla (content/order.json once)."""
        ids, done = self._scripts_and_done()
        order = self._content_json("order.json")
        order = [x for x in order if isinstance(x, str)] if isinstance(order, list) else []
        return {"total": len(ids), "queue": plan.compute_queue(ids, done, order)}

    def script_titles(self, ids: list[str]) -> dict[str, dict]:
        """content/scripts/<id>.json -> {id: {title, format, words, beats}}. Okunamayan id atlanir
        (cagiran baslik yerine id'yi gosterir). Gelen veri dogrulanir; yalniz kisa metin/sayi tasinir."""
        out: dict[str, dict] = {}
        for sid in ids[:20]:
            if not QUEUE_FILE.match(f"{sid}.json"):
                continue
            d = self._content_json(f"scripts/{sid}.json")
            if not isinstance(d, dict):
                continue
            beats = d.get("beats") if isinstance(d.get("beats"), list) else []
            words = sum(len(str(b.get("say", "")).split()) for b in beats if isinstance(b, dict))
            out[sid] = {"title": re.sub(r"[\x00-\x1f\x7f]", " ", str(d.get("title", "")))[:120].strip(),
                        "format": re.sub(r"[^a-z]", "", str(d.get("format", "")))[:12],
                        "words": words, "beats": len(beats)}
        return out

    def experiments(self) -> dict:
        """content/experiments.json -> {arm_info: {script_id: {name,label,n,exp}}, legend: [...]}.
        Gelen veri dogrulanir: kol adi kisa/guvenli, id'ler SLUG, sayilar sinirli."""
        data = self._content_json("experiments.json")
        arm_info: dict[str, dict] = {}
        legend: list[dict] = []
        if not isinstance(data, dict):
            return {"arm_info": arm_info, "legend": legend}
        for ename, e in list(data.items())[:10]:
            if not isinstance(e, dict) or not isinstance(e.get("arms"), dict):
                continue
            ename = re.sub(r"[^A-Za-z0-9_-]", "", str(ename))[:40]
            arms = []
            for n, (aname, ids) in enumerate(list(e["arms"].items())[:4], start=1):
                aname = re.sub(r"[^A-Za-z0-9_-]", "", str(aname))[:20] or f"arm{n}"
                label = plan.arm_label(aname)
                arms.append({"name": aname, "label": label, "n": n})
                for sid in (ids if isinstance(ids, list) else [])[:300]:
                    if isinstance(sid, str) and SLUG.match(sid):
                        arm_info.setdefault(sid, {"name": aname, "label": label, "n": n, "exp": ename})
            title = re.sub(r"[\x00-\x1f\x7f]", " ", str(e.get("title", ename)))[:120].strip()
            legend.append({"name": ename, "title": title or ename, "arms": arms})
        return {"arm_info": arm_info, "legend": legend}
