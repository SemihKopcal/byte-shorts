"""
Nesne deposu (Cloudflare R2, S3 uyumlu).

Arayuz kucuk tutuldu: panel yalniz bunlari yapabilir. Testler MemoryStorage ile
calisir; gercek R2'ye hicbir test dokunmaz.
"""
from __future__ import annotations

from typing import Protocol


class StorageError(RuntimeError):
    pass


class TooLarge(StorageError):
    pass


class Storage(Protocol):
    def list_keys(self, prefix: str, limit: int = 1000) -> list[str]: ...
    def get_bytes(self, key: str, max_bytes: int) -> bytes: ...
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/json") -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def move(self, src: str, dst: str) -> None: ...
    def presign_get(self, key: str, expires: int = 300) -> str: ...
    def ping(self) -> None: ...


class MemoryStorage:
    """Test ve yerel deneme icin."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail_ping = False

    def list_keys(self, prefix, limit=1000):
        return sorted(k for k in self.objects if k.startswith(prefix))[:limit]

    def get_bytes(self, key, max_bytes):
        data = self.objects[key]
        if len(data) > max_bytes:
            raise TooLarge(f"{key}: {len(data)} bayt > {max_bytes}")
        return data

    def put_bytes(self, key, data, content_type="application/json"):
        self.objects[key] = bytes(data)

    def exists(self, key):
        return key in self.objects

    def delete(self, key):
        self.objects.pop(key, None)

    def move(self, src, dst):
        self.objects[dst] = self.objects.pop(src)

    def presign_get(self, key, expires=300):
        return f"https://store.test/{key}?exp={expires}"

    def ping(self):
        if self.fail_ping:
            raise StorageError("ulasilamiyor")


class S3Storage:
    """boto3 istemcisi ile R2. Istemci disaridan verilir (test edilebilir)."""

    def __init__(self, client, bucket: str):
        self.c = client
        self.bucket = bucket

    def list_keys(self, prefix, limit=1000):
        out: list[str] = []
        token = None
        while len(out) < limit:
            kw = {"Bucket": self.bucket, "Prefix": prefix,
                  "MaxKeys": min(1000, limit - len(out))}
            if token:
                kw["ContinuationToken"] = token
            r = self.c.list_objects_v2(**kw)
            out += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                break
            token = r.get("NextContinuationToken")
        return out

    def get_bytes(self, key, max_bytes):
        r = self.c.get_object(Bucket=self.bucket, Key=key)
        n = int(r.get("ContentLength", 0))
        if n > max_bytes:
            raise TooLarge(f"{key}: {n} bayt > {max_bytes}")
        data = r["Body"].read(max_bytes + 1)
        if len(data) > max_bytes:
            raise TooLarge(f"{key}: > {max_bytes} bayt")
        return data

    def put_bytes(self, key, data, content_type="application/json"):
        self.c.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def exists(self, key):
        try:
            self.c.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:                    # botocore.ClientError 404
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise StorageError(f"head_object: {code or e}") from None

    def delete(self, key):
        self.c.delete_object(Bucket=self.bucket, Key=key)

    def move(self, src, dst):
        self.c.copy_object(Bucket=self.bucket, Key=dst,
                           CopySource={"Bucket": self.bucket, "Key": src})
        self.c.delete_object(Bucket=self.bucket, Key=src)

    def presign_get(self, key, expires=300):
        return self.c.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires)

    def ping(self):
        try:
            self.c.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            raise StorageError(code or type(e).__name__) from None


def make_s3(cfg) -> S3Storage:
    import boto3
    from botocore.config import Config as BotoConfig
    client = boto3.client(
        "s3", endpoint_url=cfg.r2_endpoint, region_name="auto",
        aws_access_key_id=cfg.r2_access_key_id,
        aws_secret_access_key=cfg.r2_secret_access_key,
        config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"},
                          connect_timeout=5, read_timeout=20))
    return S3Storage(client, cfg.r2_bucket)
