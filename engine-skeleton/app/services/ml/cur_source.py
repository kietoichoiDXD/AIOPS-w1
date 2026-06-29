"""CUR source loader for data_source_type=S3_POINTER.

CDO daily batch flow (contract §5.1): CDO reads the S3 CUR manifest, runs an
Athena query, writes a gzipped result to
`s3://company-cdo-{account_id}-telemetry/...`, and sends the pointer. The AI Engine
fetches that object, decompresses it, and parses the rows into CUR line items —
the same shape it would have received inline via RAW_JSON.

Supported object formats (by extension):
  * `.json.gz` — JSON array  OR  JSON-lines (Athena UNLOAD format=JSON). Both handled.
  * `.csv.gz`  — gzipped CSV with CUR column headers.

Offline / test fallback:
  Set `S3_LOCAL_DIR` to read the object from `{S3_LOCAL_DIR}/{key}` instead of AWS.
  Lets the S3 path run end-to-end without real S3/boto3 (CI, local demo).

Never raises into the request path: on any failure returns [] and logs a warning,
so the engine degrades to "no anomalies from pointer" rather than a 500.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    rest = uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    return bucket, key


def _read_bytes(uri: str) -> bytes | None:
    """Fetch the object bytes — local dir first (offline), then boto3."""
    bucket, key = _parse_s3_uri(uri)

    local_dir = os.getenv("S3_LOCAL_DIR")
    if local_dir:
        path = Path(local_dir) / key
        if path.exists():
            return path.read_bytes()
        logger.warning("S3_LOCAL_DIR set but %s not found", path)
        return None

    try:
        import boto3

        client = boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION", "ap-southeast-1"))
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as e:
        logger.warning("S3 fetch failed for %s: %s", uri, e)
        return None


def _decode_json_gz(raw: bytes) -> list[dict]:
    text = gzip.decompress(raw).decode("utf-8").strip()
    if not text:
        return []
    if text[0] == "[":
        return list(json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _decode_csv_gz(raw: bytes) -> list[dict]:
    text = gzip.decompress(raw).decode("utf-8")
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def load_cur_pointer(s3_uri: str) -> list[dict]:
    """Resolve an S3 CUR pointer into a list of CUR line-item dicts. Never raises."""
    raw = _read_bytes(s3_uri)
    if raw is None:
        return []
    try:
        rows = _decode_csv_gz(raw) if s3_uri.endswith(".csv.gz") else _decode_json_gz(raw)
        logger.info("Loaded %d CUR rows from %s", len(rows), s3_uri)
        return rows
    except Exception as e:
        logger.warning("Failed to parse CUR pointer %s: %s", s3_uri, e)
        return []
