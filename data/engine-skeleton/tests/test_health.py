"""Tests for GET /health."""

import pytest
from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_schema(client: TestClient):
    body = client.get("/health").json()
    assert body["status"] in ("healthy", "degraded", "unhealthy")
    assert "timestamp" in body
    assert "services" in body


def test_health_services_fields(client: TestClient):
    services = client.get("/health").json()["services"]
    assert "s3_audit_bucket" in services
    assert "bedrock_api" in services
    assert "s3_cur_bucket" in services


def test_health_mock_defaults_to_healthy(client: TestClient):
    """Default mock config has all dependencies UP."""
    body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert body["services"]["s3_audit_bucket"] == "connected"
    assert body["services"]["bedrock_api"] == "accessible"
    assert body["services"]["s3_cur_bucket"] == "reachable"


def test_health_no_auth_required(client: TestClient):
    """Health endpoint must not require any authentication headers."""
    resp = client.get("/health", headers={})
    assert resp.status_code == 200
