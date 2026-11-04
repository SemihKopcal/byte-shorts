#!/usr/bin/env python3
"""
Canli sinyal: su an AI araclari dunyasinda ne konusuluyor.

Neden gerekli: Gemini konuyu egitim verisinden buluyor, yani eski. 30-40
video sonra kendini tekrar etmeye baslar. Bu dosya ona "bu hafta ne oldu"
diye bir liste veriyor.

UC KAYNAK, uc farkli soruya cevap:
  YouTube   son 72 saatte AI konusunda hangi Shorts patladi  -> NE TUTUYOR
  HackerNews son 48 saatte ne konusuldu                      -> NE YENI
  GitHub    son 7 gunde hizli yildiz toplayan AI repolari    -> NE KULLANILIYOR

TikTok ve Twitter neden yok: TikTok'un herkese acik trend API'si yok
(Creative Center'i kazimak kullanim sartlarina aykiri ve her arayuz
degisiminde kirilir). X'in trend ucu artik aylik ucretli. Ikisi de 100 gun
donecek bir hatta konulamaz.

YouTube icin YOUTUBE_API_KEY gerekiyor (OAuth degil, duz API anahtari).
Yoksa o kaynak sessizce atlaniyor -- diger ikisi anahtarsiz calisiyor.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "byte-shorts/1.0 (+https://semihkopcal.github.io/byte/)"
TIMEOUT = 25

# Nis icinde kal: genel gundem degil, AI araclari. Nis disina cikmak kanalin
# tek ayirt edici ozelligini (olculmus AI verisi) yok ediyor.
YT_QUERIES = ["ai tools", "llm pricing", "ai video generation", "local llm"]
HN_QUERY = "AI OR LLM OR GPT OR model OR inference OR pricing"
GH_QUERY = "llm OR inference OR agent OR diffusion"


def _get(url: str, headers=None) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError) as e:
        # Tek bir kaynagin cokmesi tum hatti durdurmamali.
        print(f"  [atlandi] {url.split('?')[0]}: {e}", file=sys.stderr)
        return None


def youtube(days=3, per=6) -> list[dict]:
    """Yayin yaptigimiz platformun kendi sinyali -- en degerlisi bu."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("  [atlandi] YOUTUBE_API_KEY yok", file=sys.stderr)
        return []
    after = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                          time.gmtime(time.time() - days * 86400))
    out = []
    for q in YT_QUERIES:
        p = urllib.parse.urlencode({
            "part": "snippet", "q": q, "type": "video",
            "videoDuration": "short", "order": "viewCount",
            "publishedAfter": after, "maxResults": per,
            "relevanceLanguage": "en", "key": key})
        d = _get(f"https://www.googleapis.com/youtube/v3/search?{p}")
        for it in (d or {}).get("items", []):
            sn = it["snippet"]
            out.append({
                "src": "youtube",
                "title": sn["title"],
                "url": f"https://youtu.be/{it['id']['videoId']}",
                "note": f"{sn['channelTitle']}, {sn['publishedAt'][:10]}"})
    return out


def hackernews(hours=48, limit=18) -> list[dict]:
    """Algolia API: anahtarsiz, kota yok. AI haberleri once burada kiriliyor."""
    since = int(time.time()) - hours * 3600
    p = urllib.parse.urlencode({
        "query": HN_QUERY, "tags": "story",
        "numericFilters": f"created_at_i>{since},points>25",
        "hitsPerPage": limit})
    d = _get(f"https://hn.algolia.com/api/v1/search?{p}")
    return [{
        "src": "hn",
        "title": h.get("title") or "",
        "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
        "note": f"{h.get('points', 0)} puan, {h.get('num_comments', 0)} yorum",
    } for h in (d or {}).get("hits", []) if h.get("title")]


def github(days=7, limit=12) -> list[dict]:
    """Duyuru degil BENIMSENME sinyali: son bir haftada acilip hizla yildiz
    toplayan depolar."""
    after = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    p = urllib.parse.urlencode({
        "q": f"{GH_QUERY} created:>{after} stars:>120",
        "sort": "stars", "order": "desc", "per_page": limit})
    h = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):      # Actions icinde zaten var, kota artiyor
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    d = _get(f"https://api.github.com/search/repositories?{p}", h)
    return [{
        "src": "github",
        "title": f"{r['full_name']} — {(r.get('description') or '')[:110]}",
        "url": r["html_url"],
        "note": f"{r['stargazers_count']} yildiz, {r['created_at'][:10]}",
    } for r in (d or {}).get("items", [])]


def collect() -> list[dict]:
    items = []
    for fn in (youtube, hackernews, github):
        try:
            items += fn()
        except Exception as e:                      # noqa: BLE001
            print(f"  [atlandi] {fn.__name__}: {e}", file=sys.stderr)
    # ayni url iki kaynaktan gelebilir
    seen, out = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
    return out


def as_prompt(items: list[dict], limit=40) -> str:
    """Gemini'ye verilecek dusuk gurultulu metin."""
    if not items:
        return "(no live signal available — pick an evergreen measurable topic)"
    lines = []
    for it in items[:limit]:
        lines.append(f"- [{it['src']}] {it['title']}  ({it['note']})\n  {it['url']}")
    return "\n".join(lines)


if __name__ == "__main__":
    got = collect()
    print(as_prompt(got))
    print(f"\n{len(got)} aday", file=sys.stderr)
