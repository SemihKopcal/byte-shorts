#!/usr/bin/env python3
"""
Uc degeri GitHub'a koymadan ONCE dogrular.

Neden: publish adimi once videoyu yeniden uretiyor (~6 dakika), token hatasi
ancak ondan sonra ortaya cikiyor. Her deneme 6 dakika. Bu script ayni
kontrolu 2 saniyede yapiyor.

    python tools/check_token.py

Degerleri yapistirinca ne oldugunu soyluyor; hangi kanala bagli oldugunu da
gosteriyor ki yanlis kanala baglanmis bir token'i fark edebilesin.
"""
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
CHAN_URL = ("https://www.googleapis.com/youtube/v3/channels"
            "?part=snippet,status&mine=true")

TIPS = {
    "invalid_grant": [
        "Token bu client_id/client_secret ciftiyle UYUSMUYOR olabilir:",
        "  token'i hangi client ile aldiysan, secrets'ta da o client olmali.",
        "Token iptal edilmis olabilir (sifre degisikligi, ya da",
        "  myaccount.google.com/permissions uzerinden erisim kaldirilmasi).",
        "Onay ekrani 'Testing' modunda kaldiysa token 7 gunde bir oluyor.",
    ],
    "invalid_client": [
        "client_id ya da client_secret yanlis.",
        "console.cloud.google.com/apis/credentials -> OAuth 2.0 Client IDs",
    ],
    "unauthorized_client": [
        "Client turu yanlis olabilir: 'Desktop app' olmali.",
    ],
}


def _clean(s: str, name: str) -> str:
    """Yapistirma kazalarini yakala: bosluk, satir sonu, tirnak."""
    raw = s
    s = s.strip().strip('"').strip("'").strip()
    if s != raw.strip("\n"):
        print(f"  not: {name} icinde fazladan bosluk/tirnak vardi, temizlendi")
    if not s:
        sys.exit(f"{name} bos")
    return s


def refresh(cid: str, sec: str, tok: str) -> str:
    data = urllib.parse.urlencode({
        "client_id": cid, "client_secret": sec,
        "refresh_token": tok, "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body).get("error", "")
        except json.JSONDecodeError:
            err = ""
        print(f"\n  BASARISIZ  [{e.code}] {err}")
        print(f"  {body[:200]}")
        for line in TIPS.get(err, ["Beklenmeyen hata."]):
            print("  -", line)
        sys.exit(1)
    except urllib.error.URLError as e:
        sys.exit(f"\n  Google'a ulasilamadi: {e.reason}\n"
                 "  Bu token hatasi DEGIL -- ag/proxy sorunu. Tekrar dene.")


def channel(access: str) -> None:
    req = urllib.request.Request(
        CHAN_URL, headers={"Authorization": f"Bearer {access}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"\n  Token calisiyor ama kanal okunamadi [{e.code}].")
        print("  youtube.upload kapsami kanal okumaya izin vermiyor olabilir;")
        print("  yukleme yine de calisir. Devam et.")
        return
    items = d.get("items") or []
    if not items:
        print("\n  UYARI: token hicbir kanala bagli degil.")
        print("  Onay ekraninda marka hesabini degil kisisel hesabi secmis")
        print("  olabilirsin. Yukleme calisir ama video yanlis yere gider.")
        return
    sn = items[0]["snippet"]
    print(f"\n  Bagli kanal: {sn['title']}")
    print(f"  Kanal id   : {items[0]['id']}")
    print("  Videolar BURAYA yuklenecek. Yanlissa token'i yeniden al.")


def main() -> None:
    print("Degerleri yapistir (girdiler gizli degil ki yanlis yapistirmayi "
          "gorebilesin).\n")
    cid = _clean(input("YOUTUBE_CLIENT_ID     : "), "client_id")
    sec = _clean(getpass.getpass("YOUTUBE_CLIENT_SECRET : (gizli) "),
                 "client_secret")
    tok = _clean(input("YOUTUBE_REFRESH_TOKEN : "), "refresh_token")

    if not cid.endswith(".apps.googleusercontent.com"):
        print("\n  not: client_id genelde '.apps.googleusercontent.com' ile "
              "biter. Yanlis deger yapistirmis olabilirsin.")
    if not tok.startswith("1//"):
        print("\n  not: refresh_token genelde '1//' ile baslar. Access token "
              "('ya29...') yapistirmis olabilirsin -- o kisa omurlu, ise yaramaz.")

    print("\nGoogle'a soruluyor...")
    access = refresh(cid, sec, tok)
    print("  TAMAM  token gecerli, access token alindi.")
    channel(access)
    print("\nBu uc deger GitHub secrets'a aynen girilebilir.")


if __name__ == "__main__":
    main()
