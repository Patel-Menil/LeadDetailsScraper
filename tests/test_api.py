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
