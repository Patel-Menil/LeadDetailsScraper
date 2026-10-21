"""Tests for FastAPI endpoints and web dashboard integration."""

import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from src.lead_research.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "storage" in data


def test_dashboard_stats(client: TestClient):
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_leads" in data
    assert "priority_0_count" in data


def test_upload_and_inspect_csv(client: TestClient):
    csv_bytes = (
        b"Full Name,Job Title,Company Name,Email\n"
        b"Victor Stone,CISO,Star Labs,victor@starlabs.com\n"
    )
    files = {"file": ("prospects.csv", csv_bytes, "text/csv")}
    response = client.post("/api/batches/upload", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["valid_leads_count"] == 1
    assert "batch_id" in data
    assert data["headers"] == ["Full Name", "Job Title", "Company Name", "Email"]
    assert data["detected_mapping"]["name"] == "Full Name"
    assert data["detected_mapping"]["professional_email"] == "Email"
    # Clean up test upload
    client.delete(f"/api/batches/{data['batch_id']}")


def test_static_index_serving(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "SealAPI" in response.text


def test_global_leads_endpoint(client: TestClient):
    response = client.get("/api/leads")
    assert response.status_code == 200
    data = response.json()
    assert "leads" in data
    assert "total_records" in data


def test_manifest_export_not_found(client: TestClient):
    response = client.get("/api/batches/non_existent_batch/exports/manifest.json")
    assert response.status_code == 404


def test_api_key_authorization_when_configured(client: TestClient):
    csv_bytes = b"Full Name,Company Name,Email\nClark Kent,Daily Planet,clark@dailyplanet.com\n"
    files = {"file": ("prospects.csv", csv_bytes, "text/csv")}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.lead_research.server.API_SECRET_KEY", "super_secret_token_456")

        # 1. Missing API Key on upload -> 401
        res_no_key = client.post("/api/batches/upload", files=files)
        assert res_no_key.status_code == 401
        assert "Unauthorized" in res_no_key.json()["detail"]

        # 2. Invalid API Key -> 401
        res_bad_key = client.post("/api/batches/upload", files=files, headers={"X-API-Key": "wrong_key"})
        assert res_bad_key.status_code == 401

        # 3. Valid X-API-Key header -> 200
        res_valid = client.post("/api/batches/upload", files={"file": ("prospects.csv", csv_bytes, "text/csv")}, headers={"X-API-Key": "super_secret_token_456"})
        assert res_valid.status_code == 200
        batch_id = res_valid.json()["batch_id"]

        # 4. Valid Authorization Bearer header -> 200
        res_bearer = client.post(
            "/api/batches/upload",
            files={"file": ("prospects.csv", csv_bytes, "text/csv")},
            headers={"Authorization": "Bearer super_secret_token_456"},
        )
        assert res_bearer.status_code == 200

        # 5. Delete operation requires key
        res_del_unauth = client.delete(f"/api/batches/{batch_id}")
        assert res_del_unauth.status_code == 401

        res_del_auth = client.delete(f"/api/batches/{batch_id}", headers={"X-API-Key": "super_secret_token_456"})
        assert res_del_auth.status_code == 200

        # Clean up second upload
        batch_id_bearer = res_bearer.json()["batch_id"]
        client.delete(f"/api/batches/{batch_id_bearer}", headers={"X-API-Key": "super_secret_token_456"})


def test_batch_id_validation_rejects_path_traversal(client: TestClient):
    # Malformed / traversal / injection batch IDs must be rejected with 400
    res1 = client.get("/api/batches/batch..traversal/leads")
    assert res1.status_code == 400
    assert "Invalid batch ID" in res1.json()["detail"]

    res2 = client.get("/api/batches/invalid;batch$id/exports/manifest.json")
    assert res2.status_code == 400
    assert "Invalid batch ID" in res2.json()["detail"]

    res3 = client.get("/api/batches/@bad*batch!/exports/manifest.json")
    assert res3.status_code == 400
    assert "Invalid batch ID" in res3.json()["detail"]


def test_completed_batch_immutability_rejects_restart(client: TestClient, tmp_path: Path):
    from unittest.mock import patch
    import json
    from src.lead_research.server import BATCHES_DIR, UPLOADS_DIR

    test_b_id = "batch_completed_immutable_001"
    b_dir = BATCHES_DIR / test_b_id
    b_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = b_dir / "manifest.json"
    manifest_file.write_text(json.dumps({"batch_id": test_b_id, "status": "completed"}), encoding="utf-8")

    # Create dummy upload file so start check reaches immutability gate
    upload_file = UPLOADS_DIR / f"{test_b_id}.csv"
    upload_file.write_text("Full Name,Company Name\nJohn Doe,Acme\n", encoding="utf-8")

    try:
        # Starting an already completed batch with resume=False must raise 409 Conflict
        res = client.post(f"/api/batches/{test_b_id}/start", json={"resume": False})
        assert res.status_code == 409
        assert "already completed" in res.json()["detail"].lower()
    finally:
        import shutil
        if b_dir.exists():
            shutil.rmtree(b_dir, ignore_errors=True)
        if upload_file.exists():
            upload_file.unlink()


def test_concurrent_batch_start_rejected(client: TestClient):
    from src.lead_research.server import active_batches, BatchProgress, UPLOADS_DIR

    test_b_id = "batch_concurrent_running_01"
    upload_file = UPLOADS_DIR / f"{test_b_id}.csv"
    upload_file.write_text("Name,Company\nAlice,Wonderland\n", encoding="utf-8")

    active_batches[test_b_id] = BatchProgress(
        batch_id=test_b_id,
        filename=f"{test_b_id}.csv",
        status="processing",
    )

    try:
        res = client.post(f"/api/batches/{test_b_id}/start", json={})
        assert res.status_code == 409
        assert "currently running" in res.json()["detail"].lower()
    finally:
        active_batches.pop(test_b_id, None)
        if upload_file.exists():
            upload_file.unlink()


def test_cors_policy_disallows_wildcard_with_credentials(client: TestClient):
    # Verify that CORSMiddleware does not use allow_origins=['*'] with allow_credentials=True
    from fastapi.middleware.cors import CORSMiddleware
    for middleware in app.user_middleware:
        if middleware.cls == CORSMiddleware:
            origins = middleware.kwargs.get("allow_origins", [])
            creds = middleware.kwargs.get("allow_credentials", False)
            if creds:
                assert "*" not in origins, "Wildcard '*' origin cannot be combined with allow_credentials=True"


def test_production_mode_fails_closed_without_api_secret_key(client: TestClient):
    csv_bytes = b"Full Name,Company Name,Email\nBruce Wayne,Wayne Enterprises,bruce@wayne.com\n"
    files = {"file": ("prospects.csv", csv_bytes, "text/csv")}

    with pytest.MonkeyPatch.context() as mp:
        # In production mode with missing API_SECRET_KEY, protected operations must fail closed
        mp.setattr("src.lead_research.server.APP_ENV", "production")
        mp.setattr("src.lead_research.server.API_SECRET_KEY", "")

        res = client.post("/api/batches/upload", files=files)
        assert res.status_code == 500
        assert "Server configuration error" in res.json()["detail"]

        res_tor = client.post("/api/tor/start")
        assert res_tor.status_code == 500


def test_tor_start_requires_authorization(client: TestClient):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.lead_research.server.API_SECRET_KEY", "tor_admin_secret_999")

        # Missing key -> 401
        res = client.post("/api/tor/start")
        assert res.status_code == 401

        # Valid key -> 200
        res_auth = client.post("/api/tor/start", headers={"X-API-Key": "tor_admin_secret_999"})
        assert res_auth.status_code == 200


def test_exports_and_sensitive_reads_require_authorization(client: TestClient):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.lead_research.server.API_SECRET_KEY", "secure_key_12345")

        # Test batch list read
        res = client.get("/api/batches")
        assert res.status_code == 401
        res = client.get("/api/batches", headers={"X-API-Key": "secure_key_12345"})
        assert res.status_code == 200

        # Test dashboard stats read
        res = client.get("/api/dashboard/stats")
        assert res.status_code == 401
        res = client.get("/api/dashboard/stats", headers={"X-API-Key": "secure_key_12345"})
        assert res.status_code == 200

        # Test export download routes
        export_endpoints = [
            "/api/batches/b1/exports/manifest.json",
            "/api/batches/b1/exports/summary.json",
            "/api/batches/b1/exports/prioritized.csv",
            "/api/batches/b1/exports/outreach_ready.csv",
            "/api/batches/b1/exports/needs_review.csv",
            "/api/batches/b1/exports/errors.csv",
            "/api/batches/b1/exports/scraping.log",
            "/api/batches/b1/exports/profiles/person_001.json",
            "/api/batches/b1/exports/zip",
        ]
        for ep in export_endpoints:
            res = client.get(ep)
            assert res.status_code == 401, f"{ep} did not require authentication"

        # Additional sensitive read endpoints
        sensitive_reads = [
            "/api/batches/b1/leads",
            "/api/batches/b1/leads/lead_1/profile",
            "/api/leads",
            "/api/leads/lead_1/profile",
            "/api/batches/latest",
            "/api/tor/status",
        ]
        for ep in sensitive_reads:
            res = client.get(ep)
            assert res.status_code == 401, f"{ep} did not require authentication"


def test_batch_clear_all_requires_authorization(client: TestClient):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.lead_research.server.API_SECRET_KEY", "admin_secret_987")
        res = client.delete("/api/batches")
        assert res.status_code == 401

        res_bad = client.delete("/api/batches", headers={"X-API-Key": "wrong_key"})
        assert res_bad.status_code == 401


def test_api_responses_never_leak_secret_key(client: TestClient):
    secret_token = "confidential_production_secret_key_777"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.lead_research.server.API_SECRET_KEY", secret_token)
        mp.setattr("src.lead_research.server.APP_ENV", "production")

        # 401 Unauthorized response
        res_401 = client.get("/api/batches")
        assert res_401.status_code == 401
        assert secret_token not in res_401.text

        # 404 Not Found response
        res_404 = client.get("/api/nonexistent-route", headers={"X-API-Key": secret_token})
        assert secret_token not in res_404.text

        # Health endpoint
        res_health = client.get("/api/health")
        assert res_health.status_code == 200
        assert secret_token not in res_health.text


