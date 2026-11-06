"""
TikTok'a bir kereye mahsus giris: refresh token'i alir (365 gun gecerli).

    python tools/tiktok_login.py

Once TikTok geliştirici portalinda (developers.tiktok.com) uygulamanda:
  * platform: Desktop
  * Redirect URI olarak TAM OLARAK sunu kaydet:  http://127.0.0.1:8765/callback/
  * Content Posting API urunu + video.upload izni (Login Kit ile birlikte)
  * Sandbox kullaniyorsan kendi hesabini "Target User" olarak ekle

Client key/secret terminalde sorulur (ekranda gorunmez); sohbete YAZMA.
Sonunda token ~/.byte-tiktok-refresh-token dosyasina yazilir (sadece sen
okursun) ve GitHub secret'ina nasil yapistiracagin soylenir.
"""
import base64
import getpass
import hashlib
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from publish import net                     # noqa: E402

PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/callback/"
SCOPES = "user.info.basic,video.upload"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    # TikTok: code_challenge = SHA-256'nin HEX hali (RFC'deki base64url DEGIL)
    return verifier, hashlib.sha256(verifier.encode()).hexdigest()


def auth_url(client_key: str, state: str, challenge: str) -> str:
    q = urllib.parse.urlencode({
        "client_key": client_key, "scope": SCOPES, "response_type": "code",
        "redirect_uri": REDIRECT, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    return f"https://www.tiktok.com/v2/auth/authorize/?{q}"


def main() -> int:
    key = os.environ.get("TIKTOK_CLIENT_KEY") or getpass.getpass("Client key: ").strip()
    secret = os.environ.get("TIKTOK_CLIENT_SECRET") or getpass.getpass("Client secret: ").strip()
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(16)
    got: dict = {}
    done = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h3>Tamam, bu sekmeyi kapatabilirsin.</h3>")
            done.set()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = auth_url(key, state, challenge)
    print("Tarayici aciliyor; TikTok'ta BYTE hesabinla giris yapip izin ver...")
    print(f"Acilmazsa bu adresi tarayiciya yapistir:\n{url}\n")
    webbrowser.open(url)
    if not done.wait(300):
        print("5 dakika icinde donus gelmedi", file=sys.stderr)
        return 1
    srv.shutdown()
    if got.get("state") != state or "code" not in got:
        print(f"yetkilendirme basarisiz: {got}", file=sys.stderr)
        return 1

    st, out = net.request("POST", "https://open.tiktokapis.com/v2/oauth/token/", form={
        "client_key": key, "client_secret": secret,
        "code": urllib.parse.unquote(got["code"]), "grant_type": "authorization_code",
        "redirect_uri": REDIRECT, "code_verifier": verifier})
    if st != 200 or "refresh_token" not in out:
        print(f"token alinamadi (HTTP {st}): {net.err_text(out)}", file=sys.stderr)
        return 1
    if "video.upload" not in str(out.get("scope", "")):
        print(f"UYARI: video.upload izni verilmemis (kapsam: {out.get('scope')})",
              file=sys.stderr)
    f = Path.home() / ".byte-tiktok-refresh-token"
    f.write_text(out["refresh_token"])
    f.chmod(0o600)
    print(f"\nTamam. Refresh token {f} dosyasina yazildi "
          f"(~{int(out.get('refresh_expires_in', 0)) // 86400} gun gecerli).")
    print("GitHub > Settings > Secrets and variables > Actions > New secret:")
    print("  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET ve TIKTOK_REFRESH_TOKEN")
    print("Refresh token'i panoya almak icin (ekranda gostermeden):")
    print(f"  pbcopy < {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
