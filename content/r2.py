"""Cloudflare R2 storage — S3-compatible via boto3."""

from __future__ import annotations

import json
from typing import Optional

import boto3
from botocore.config import Config

from settings import load_settings


def _get_r2_client():
    """Create a boto3 S3 client configured for Cloudflare R2."""
    s = load_settings()
    if not s.r2_account_id or not s.r2_access_key or not s.r2_secret_key:
        raise RuntimeError("R2 credentials not configured. Set them in Settings.")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=s.r2_access_key,
        aws_secret_access_key=s.r2_secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _bucket() -> str:
    s = load_settings()
    if not s.r2_bucket_name:
        raise RuntimeError("R2 bucket name not configured.")
    return s.r2_bucket_name


def _public_url(key: str) -> str:
    s = load_settings()
    base = (s.r2_public_url or "").rstrip("/")
    if not base:
        return key
    return f"{base}/{key}"


def upload_text(key: str, text: str) -> dict:
    """Upload text content (markdown, etc.) to R2."""
    client = _get_r2_client()
    data = text.encode("utf-8")
    client.put_object(
        Bucket=_bucket(),
        Key=key,
        Body=data,
        ContentType="text/markdown; charset=utf-8",
    )
    return {"key": key, "public_url": _public_url(key), "size_bytes": len(data)}


def upload_json(key: str, data: dict) -> dict:
    """Upload a dict as JSON to R2."""
    client = _get_r2_client()
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(
        Bucket=_bucket(),
        Key=key,
        Body=body,
        ContentType="application/json; charset=utf-8",
    )
    return {"key": key, "public_url": _public_url(key), "size_bytes": len(body)}


def upload_image(key: str, image_bytes: bytes, fmt: str = "png") -> dict:
    """Upload image bytes to R2."""
    client = _get_r2_client()
    client.put_object(
        Bucket=_bucket(),
        Key=key,
        Body=image_bytes,
        ContentType=f"image/{fmt}",
    )
    return {"key": key, "public_url": _public_url(key), "size_bytes": len(image_bytes)}


def list_objects(prefix: str, max_keys: int = 1000) -> list[dict]:
    """List objects under a prefix."""
    client = _get_r2_client()
    resp = client.list_objects_v2(Bucket=_bucket(), Prefix=prefix, MaxKeys=max_keys)
    items = []
    for obj in resp.get("Contents", []):
        items.append({
            "key": obj["Key"],
            "size": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
        })
    return items


def delete_object(key: str) -> bool:
    """Delete a single object."""
    client = _get_r2_client()
    client.delete_object(Bucket=_bucket(), Key=key)
    return True


def delete_prefix(prefix: str) -> int:
    """Delete all objects under a prefix."""
    objects = list_objects(prefix)
    if not objects:
        return 0
    client = _get_r2_client()
    delete_keys = [{"Key": obj["key"]} for obj in objects]
    client.delete_objects(Bucket=_bucket(), Delete={"Objects": delete_keys})
    return len(delete_keys)


def get_public_url(key: str) -> str:
    """Get the public URL for a key."""
    return _public_url(key)


def check_connection() -> dict:
    """Test R2 connection by calling head_bucket."""
    try:
        client = _get_r2_client()
        bucket = _bucket()
        client.head_bucket(Bucket=bucket)
        return {"connected": True, "bucket": bucket}
    except RuntimeError as e:
        return {"connected": False, "error": str(e)}
    except Exception as e:
        return {"connected": False, "error": str(e)}
