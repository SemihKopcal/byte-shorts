#!/usr/bin/env python3
"""
Refresh token'i BIR KEZ alir. Kendi makinende calistir, sunucuda degil.

    pip install google-auth-oauthlib
    python tools/get_refresh_token.py

Cikan token'i GitHub'da YOUTUBE_REFRESH_TOKEN secret'ina yapistir.
Bana yazma: sohbete yapistirilan anahtar sohbetin saklandigi her yerde kalir.

ONEMLI: OAuth onay ekrani "Testing" modundaysa Google bu token'i 7 gunde bir
gecersiz kiliyor. Once consent screen'i "In production" yap, sonra burayi
calistir -- yoksa sekizinci gun yuklemeler sessizce durur.
"""
import getpass
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit("once: pip install google-auth-oauthlib")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    cid = input("client_id: ").strip()
    # getpass: terminal gecmisine ve omuz ustune dusmesin
    sec = getpass.getpass("client_secret (girdi gizli): ").strip()
    if not cid or not sec:
        sys.exit("bos birakma")

    cfg = {"installed": {
        "client_id": cid,
        "client_secret": sec,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}

    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    # access_type=offline + prompt=consent: refresh_token'in DONMESINI garanti
    # eder. Daha once onay verdiysen Google bunu ikinci kez gondermiyor.
    creds = flow.run_local_server(port=0, access_type="offline",
                                  prompt="consent")

    if not creds.refresh_token:
        sys.exit("refresh_token donmedi. myaccount.google.com/permissions "
                 "adresinden uygulamanin erisimini kaldirip tekrar dene.")

    print("\n" + "=" * 58)
    print("YOUTUBE_REFRESH_TOKEN =")
    print(creds.refresh_token)
    print("=" * 58)
    print("\nGitHub -> repo -> Settings -> Secrets and variables -> Actions")
    print("Bu satiri baska hicbir yere yapistirma.")


if __name__ == "__main__":
    main()
