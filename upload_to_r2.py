#!/usr/bin/env python3
"""
upload_to_r2.py — Download an image from a URL and upload it to Cloudflare R2.

Usage:
    python3 upload_to_r2.py \
        --url   "https://example.com/image.jpg" \
        --key   "folder/image.jpg"

All R2 credentials are read from .env (CF_R2_ACCOUNT_ID, CF_R2_ACCESS_KEY_ID,
CF_R2_SECRET_ACCESS_KEY, CF_R2_BUCKET, CF_R2_PUBLIC_URL_BASE).
"""

import argparse
import os
import sys
from io import BytesIO

import boto3
import requests
from dotenv import load_dotenv

load_dotenv()


def parse_args():
    p = argparse.ArgumentParser(description="Upload an image URL to Cloudflare R2")
    p.add_argument("--url",    required=True, help="Image URL to download and upload")
    p.add_argument("--key",    required=True, help="Destination object key in R2 bucket, e.g. folder/image.jpg")
    p.add_argument("--bucket", default=None,  help="R2 bucket name (overrides CF_R2_BUCKET env var)")
    return p.parse_args()


def upload_to_r2(image_url: str, object_key: str, bucket: str | None = None) -> str:
    """
    Downloads `image_url` into memory and uploads it to Cloudflare R2.
    Returns the public URL of the uploaded object.
    """
    account_id  = os.environ.get("CF_R2_ACCOUNT_ID", "").strip()
    access_key  = os.environ.get("CF_R2_ACCESS_KEY_ID", "").strip()
    secret_key  = os.environ.get("CF_R2_SECRET_ACCESS_KEY", "").strip()
    bucket      = bucket or os.environ.get("CF_R2_BUCKET", "").strip()
    public_base = os.environ.get("CF_R2_PUBLIC_URL_BASE", "").strip().rstrip("/")

    missing = [k for k, v in {
        "CF_R2_ACCOUNT_ID":       account_id,
        "CF_R2_ACCESS_KEY_ID":    access_key,
        "CF_R2_SECRET_ACCESS_KEY": secret_key,
        "CF_R2_BUCKET":           bucket,
    }.items() if not v]
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    # ── Download image into memory ────────────────────────────────────────────
    # print(f"[upload_to_r2] Downloading {image_url} ...")
    resp = requests.get(image_url, timeout=30)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    image_data   = BytesIO(resp.content)

    # ── Upload to R2 ─────────────────────────────────────────────────────────
    # print(f"[upload_to_r2] Uploading to R2 bucket '{bucket}' at key '{object_key}' ...")
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.upload_fileobj(
        image_data,
        bucket,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )

    # ── Build public URL ──────────────────────────────────────────────────────
    if public_base:
        public_url = f"{public_base}/{object_key}"
    else:
        public_url = f"https://{bucket}.{account_id}.r2.cloudflarestorage.com/{object_key}"

    return public_url


def main():
    args       = parse_args()
    public_url = upload_to_r2(args.url, args.key, args.bucket)
    print(public_url)


if __name__ == "__main__":
    main()
