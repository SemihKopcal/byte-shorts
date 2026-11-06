"""
Platform API'leri icin tek HTTP kapisi (yalniz standart kutuphane).

request() hic hata FIRLATMAZ: (durum, govde) doner. Ag hatasi durum 0.
Testler bunun yerine sahte bir fonksiyon verir; ag gerekmiyor.
"""
import json
import urllib.error
import urllib.parse
import urllib.request


def request(method, url, *, headers=None, form=None, json_body=None, data=None,
            timeout=60):
    hdrs = dict(headers or {})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json; charset=UTF-8")
    elif form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif data is not None:
        body = data
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"error": {"message": str(e)}}
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:
        return status, {"raw": raw[:300].decode("utf-8", "replace")}


def err_text(body) -> str:
    """Platformlarin farkli hata govdelerinden okunur tek satir."""
    if not isinstance(body, dict):
        return str(body)[:200]
    e = body.get("error")
    if isinstance(e, dict):
        parts = [str(e.get(k)) for k in ("code", "type", "message", "error_user_msg")
                 if e.get(k)]
        return " | ".join(parts)[:300] or json.dumps(e)[:300]
    if e:
        return f"{e}: {body.get('error_description', '')}"[:300]
    return (body.get("raw") or json.dumps(body))[:300]
