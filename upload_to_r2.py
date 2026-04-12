#!/usr/bin/env python3
"""
upload_to_r2.py — Stream any file (image or video) from a URL to Cloudflare R2.

Uses chunked streaming so large files (videos) are never fully buffered in memory.

Usage:
    python3 upload_to_r2.py \
        --url "https://example.com/video.mp4" \
        --key "videos/video.mp4"

    python3 upload_to_r2.py \
        --url "https://example.com/image.jpg" \
        --key "images/poster.jpg"

All R2 credentials are read from .env (CF_R2_ACCOUNT_ID, CF_R2_ACCESS_KEY_ID,
CF_R2_SECRET_ACCESS_KEY, CF_R2_BUCKET, CF_R2_PUBLIC_URL_BASE).
"""

import argparse
import os
import sys
import tempfile
from typing import Optional

import boto3
import requests
from dotenv import load_dotenv

load_dotenv()

# Chunk size for streaming download: 8 MB
CHUNK_SIZE = 8 * 1024 * 1024


def parse_args():
    p = argparse.ArgumentParser(description="Upload an image or video URL to Cloudflare R2")
    p.add_argument("--url",    required=True, help="File URL to download and upload (image or video)")
    p.add_argument("--key",    required=True, help="Destination object key in R2 bucket, e.g. videos/clip.mp4")
    p.add_argument("--bucket", default=None,  help="R2 bucket name (overrides CF_R2_BUCKET env var)")
    return p.parse_args()


def _r2_client(account_id: str, access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def upload_to_r2(file_url: str, object_key: str, bucket: Optional[str] = None) -> str:
    """
    Streams `file_url` directly to Cloudflare R2 without loading the full file
    into memory. Works for both images and large videos.
    Returns the public URL of the uploaded object.
    """
    account_id  = os.environ.get("CF_R2_ACCOUNT_ID", "").strip()
    access_key  = os.environ.get("CF_R2_ACCESS_KEY_ID", "").strip()
    secret_key  = os.environ.get("CF_R2_SECRET_ACCESS_KEY", "").strip()
    bucket      = bucket or os.environ.get("CF_R2_BUCKET", "").strip()
    public_base = os.environ.get("CF_R2_PUBLIC_URL_BASE", "").strip().rstrip("/")

    missing = [k for k, v in {
        "CF_R2_ACCOUNT_ID":        account_id,
        "CF_R2_ACCESS_KEY_ID":     access_key,
        "CF_R2_SECRET_ACCESS_KEY": secret_key,
        "CF_R2_BUCKET":            bucket,
    }.items() if not v]
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    # ── Stream download → temp file ───────────────────────────────────────────
    # Streaming to a temp file lets boto3 use multipart upload (requires seekable
    # stream), which is required for files > 5 GB and much faster for large files.
    with requests.get(file_url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        content_type   = resp.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
        content_length = resp.headers.get("Content-Length")

        suffix = os.path.splitext(object_key)[1] or ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path     = tmp.name
            downloaded   = 0
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    tmp.write(chunk)
                    downloaded += len(chunk)
                    if content_length:
                        pct = downloaded / int(content_length) * 100
                        # print(f"\r  downloading ... {pct:5.1f}%", end="", flush=True)
            if content_length:
                print()  # newline after progress

    # ── Upload temp file to R2 ────────────────────────────────────────────────
    try:
        client = _r2_client(account_id, access_key, secret_key)
        client.upload_file(
            tmp_path,
            bucket,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )
    finally:
        os.unlink(tmp_path)

    # ── Build public URL ──────────────────────────────────────────────────────
    if public_base:
        return f"{public_base}/{object_key}"
    return f"https://{bucket}.{account_id}.r2.cloudflarestorage.com/{object_key}"


def main():
    args       = parse_args()
    public_url = upload_to_r2(args.url, args.key, args.bucket)
    print(public_url)


if __name__ == "__main__":
    main()