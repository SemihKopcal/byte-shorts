"""
Cloudflare R2 (S3 uyumlu) istemcisi, CI tarafi. boto3 YALNIZ burada, kullanilirken
import edilir: testler boto3 olmadan sahte istemciyle calisir.

Ortam: R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
(GitHub Secrets; CI token'i yalniz bu bucket'a Object Read & Write).
"""
import os
import re

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}\Z")
NEED = ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


def client_from_env(env=None):
    env = os.environ if env is None else env
    missing = [k for k in NEED if not env.get(k, "").strip()]
    if missing:
        raise SystemExit("R2 ayari eksik: " + ", ".join(missing))
    endpoint = env["R2_ENDPOINT"].strip()
    if not endpoint.startswith("https://"):
        raise SystemExit("R2_ENDPOINT https:// ile baslamali")
    import boto3
    from botocore.config import Config
    client = boto3.client(
        "s3", endpoint_url=endpoint, region_name="auto",
        aws_access_key_id=env["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"].strip(),
        config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=120,
                      retries={"max_attempts": 4, "mode": "standard"}))
    return client, env["R2_BUCKET"].strip()
