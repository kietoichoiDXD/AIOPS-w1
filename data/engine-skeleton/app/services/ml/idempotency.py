"""
IdempotencyService — DynamoDB conditional write + TTL per contract §3.2.

Hot path: DynamoDB ConditionExpression attribute_not_exists → ~5-15ms latency.
(S3 audit trail is optional/async, NOT the hot path per v3.2.0 telemetry-contract.)

Table schema:
  PK: idempotency_key  (string)
  Attrs:
    status            PENDING | IN_PROGRESS | COMPLETED
    payload_sha256    hex string of request body SHA256
    response_body     JSON string of cached DetectResponse
    ttl_expiry        Unix epoch (auto-deleted by DynamoDB TTL after 24h)
    created_at        ISO8601 UTC

State machine (contract §3.2):
  Key absent           → write IN_PROGRESS, process normally
  IN_PROGRESS          → 409 Conflict
  COMPLETED + SHA matches → 200 with cached response
  COMPLETED + SHA mismatch → 400 ERR_IDEMPOTENCY_MISMATCH

Fallback: when DYNAMODB_TABLE env var is not set (local dev / tests),
  uses an in-process dict store with TTL ignored.  Never raises in fallback mode.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_TABLE_NAME = os.getenv("DYNAMODB_TABLE", "")
_TTL_SECONDS = 86_400


class IdempotencyStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class IdempotencyConflict(Exception):
    """409 — key is currently IN_PROGRESS."""


class IdempotencyMismatch(Exception):
    """400 — key COMPLETED but SHA256 of payload differs."""


class IdempotencyCacheHit(Exception):
    """200 — key COMPLETED with matching SHA256; cached response available."""

    def __init__(self, response_body: dict) -> None:
        self.response_body = response_body



_local_store: dict[str, dict] = {}


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _now_epoch() -> int:
    return int(time.time())


def _iso_now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"




def _ddb_client():
    """Return boto3 DynamoDB client, or None if boto3 unavailable."""
    try:
        import boto3
        return boto3.client("dynamodb", region_name=os.getenv("AWS_DEFAULT_REGION", "ap-southeast-1"))
    except ImportError:
        return None


def _ddb_put_in_progress(client: Any, key: str, sha: str) -> bool:
    """
    Conditional write: only succeeds if key does not exist.
    Returns True on success, False if key already exists (conflict).
    """
    try:
        client.put_item(
            TableName=_TABLE_NAME,
            Item={
                "idempotency_key": {"S": key},
                "status":          {"S": IdempotencyStatus.IN_PROGRESS},
                "payload_sha256":  {"S": sha},
                "ttl_expiry":      {"N": str(_now_epoch() + _TTL_SECONDS)},
                "created_at":      {"S": _iso_now()},
            },
            ConditionExpression="attribute_not_exists(idempotency_key)",
        )
        return True
    except Exception as e:
        if "ConditionalCheckFailed" in type(e).__name__:
            return False
        raise


def _ddb_get(client: Any, key: str) -> dict | None:
    resp = client.get_item(
        TableName=_TABLE_NAME,
        Key={"idempotency_key": {"S": key}},
    )
    item = resp.get("Item")
    if not item:
        return None
    return {
        "status":         item.get("status", {}).get("S"),
        "payload_sha256": item.get("payload_sha256", {}).get("S", ""),
        "response_body":  item.get("response_body", {}).get("S", "{}"),
    }


def _ddb_complete(client: Any, key: str, response_body: dict) -> None:
    client.update_item(
        TableName=_TABLE_NAME,
        Key={"idempotency_key": {"S": key}},
        UpdateExpression="SET #s = :s, response_body = :r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": {"S": IdempotencyStatus.COMPLETED},
            ":r": {"S": json.dumps(response_body)},
        },
    )




def _local_check_and_set(key: str, sha: str) -> None:
    record = _local_store.get(key)
    if record is None:
        _local_store[key] = {
            "status": IdempotencyStatus.IN_PROGRESS,
            "payload_sha256": sha,
            "response_body": {},
            "expires": _now_epoch() + _TTL_SECONDS,
        }
        return


    if record["expires"] < _now_epoch():
        del _local_store[key]
        _local_store[key] = {
            "status": IdempotencyStatus.IN_PROGRESS,
            "payload_sha256": sha,
            "response_body": {},
            "expires": _now_epoch() + _TTL_SECONDS,
        }
        return

    if record["status"] == IdempotencyStatus.IN_PROGRESS:
        raise IdempotencyConflict(key)

    if record["status"] == IdempotencyStatus.COMPLETED:
        if record["payload_sha256"] == sha:
            raise IdempotencyCacheHit(record["response_body"])
        raise IdempotencyMismatch(key)


def _local_complete(key: str, response_body: dict) -> None:
    if key in _local_store:
        _local_store[key]["status"] = IdempotencyStatus.COMPLETED
        _local_store[key]["response_body"] = response_body




class IdempotencyService:
    """
    Thin façade routing to DynamoDB (prod) or in-process dict (dev/test).

    Router usage:
        try:
            idempotency.check_and_set(key, body_bytes)
        except IdempotencyCacheHit as hit:
            return hit.response_body          # 200 cached
        except IdempotencyConflict:
            raise HTTPException(409, ...)
        except IdempotencyMismatch:
            raise HTTPException(400, ...)

        result = ... process ...
        idempotency.mark_complete(key, result.model_dump())
    """

    def __init__(self) -> None:
        self._use_dynamo = bool(_TABLE_NAME)
        if self._use_dynamo:
            self._client = _ddb_client()
            if self._client is None:
                logger.warning("boto3 unavailable — falling back to local idempotency store")
                self._use_dynamo = False
        else:
            logger.info("DYNAMODB_TABLE not set — using local idempotency store (dev mode)")

    def check_and_set(self, key: str, payload_bytes: bytes) -> None:
        sha = _sha256(payload_bytes)

        if self._use_dynamo:
            existing = _ddb_get(self._client, key)
            if existing is None:
                ok = _ddb_put_in_progress(self._client, key, sha)
                if not ok:
                    existing = _ddb_get(self._client, key)
                    if existing and existing["status"] == IdempotencyStatus.IN_PROGRESS:
                        raise IdempotencyConflict(key)
                return
            if existing["status"] == IdempotencyStatus.IN_PROGRESS:
                raise IdempotencyConflict(key)
            if existing["status"] == IdempotencyStatus.COMPLETED:
                if existing["payload_sha256"] == sha:
                    raise IdempotencyCacheHit(json.loads(existing["response_body"]))
                raise IdempotencyMismatch(key)
        else:
            _local_check_and_set(key, sha)

    def mark_complete(self, key: str, response_body: dict) -> None:
        if self._use_dynamo:
            try:
                _ddb_complete(self._client, key, response_body)
            except Exception as e:
                logger.error("Failed to mark idempotency key complete: %s", e)
        else:
            _local_complete(key, response_body)

    @staticmethod
    def sha256_header(payload_bytes: bytes) -> str:
        return _sha256(payload_bytes)
