import threading

import pytest
from fastapi.testclient import TestClient

from src.lead_research import server
from src.lead_research.individual_research import IndividualJobStore, IndividualPipeline
from tests.test_individual_research import (
    LI_A, LI_B, AnySearch, FakeGitHub, FakeResearcher, fetch_ok,
)


def _install(monkeypatch, search, github_factory=FakeGitHub, spawn=None):
    monkeypatch.setattr(server, "individual_jobs", IndividualJobStore())
    monkeypatch.setattr(server, "make_individual_pipeline", lambda: IndividualPipeline(
        search, github_factory(), fetch_ok("https://acme.ai", "Acme AI - secure agents"),
        company_researcher=FakeResearcher))
    monkeypatch.setattr(server, "_spawn", spawn or (lambda fn, *a: fn(*a)))
    return TestClient(server.app)


@pytest.fixture
def client(monkeypatch):
    return _install(monkeypatch, AnySearch([LI_A]))


@pytest.fixture
def client_ambiguous(monkeypatch):
    return _install(monkeypatch, AnySearch([LI_A, LI_B]))


BASE = "/api/individual/research"


def start(c, **kw):
    r = c.post(BASE, json={"name": "Jane Doe", "github_url": "https://github.com/jane", "company": "Acme AI", **kw})
    assert r.status_code == 200
    return r.json()["job_id"]


def test_start_and_poll_completed(client):
    jid = start(client)
    job = client.get(f"{BASE}/{jid}").json()
    assert job["status"] == "completed" and len(job["stages"]) == 6 and job["running"] is False


def test_name_validation(client):
    assert client.post(BASE, json={"name": " "}).status_code == 422
    assert client.post(BASE, json={}).status_code == 422
    assert client.post(BASE, json={"name": "J"}).status_code == 422


def test_bad_and_unknown_job_ids(client):
    assert client.get(f"{BASE}/..%2Fx").status_code in (400, 404)
    assert client.get(f"{BASE}/bad").status_code == 400
    assert client.get(f"{BASE}/ind_0000000000000000").status_code == 404
    assert client.post(f"{BASE}/ind_0000000000000000/retry").status_code == 404
    assert client.post(f"{BASE}/ind_0000000000000000/select", json={"candidate_id": "x"}).status_code == 404


def test_select_flow_and_double_select_conflict(client_ambiguous):
    c = client_ambiguous
    jid = start(c, github_url="", company="")
    job = c.get(f"{BASE}/{jid}").json()
    assert job["status"] == "needs_input"
    cid = job["candidates"][0]["candidate_id"]
    r = c.post(f"{BASE}/{jid}/select", json={"candidate_id": cid})
    assert r.status_code == 200 and r.json()["selected_candidate_id"] == cid
    assert c.get(f"{BASE}/{jid}").json()["status"] in ("completed", "partial")
    assert c.post(f"{BASE}/{jid}/select", json={"candidate_id": cid}).status_code == 409


def test_select_unknown_candidate_404(client_ambiguous):
    jid = start(client_ambiguous, github_url="", company="")
    r = client_ambiguous.post(f"{BASE}/{jid}/select", json={"candidate_id": "cand_nope"})
    assert r.status_code == 404
    assert client_ambiguous.get(f"{BASE}/{jid}").json()["status"] == "needs_input"


def test_retry_nothing_to_retry_409(client):
    jid = start(client)
    assert client.post(f"{BASE}/{jid}/retry").status_code == 409


def test_retry_failed_stage(monkeypatch):
    class Crash:
        def __init__(self, store):
            pass

        def research(self, record):
            raise RuntimeError("boom")

    c = _install(monkeypatch, AnySearch([LI_A]))
    pipes = []
    orig = server.make_individual_pipeline

    def mk():
        p = orig()
        p.company_researcher = Crash if not pipes else FakeResearcher
        pipes.append(p)
        return p

    monkeypatch.setattr(server, "make_individual_pipeline", mk)
    jid = start(c)
    assert c.get(f"{BASE}/{jid}").json()["status"] == "partial"
    r = c.post(f"{BASE}/{jid}/retry")
    assert r.status_code == 200
    assert c.get(f"{BASE}/{jid}").json()["status"] == "completed"
    assert len(pipes) == 2  # fresh pipeline per run


def test_running_job_conflicts_and_get_does_not_block(monkeypatch):
    spawned = []
    c = _install(monkeypatch, AnySearch([LI_A, LI_B]), spawn=lambda fn, *a: fn(*a))
    jid = start(c, github_url="", company="")
    cid = c.get(f"{BASE}/{jid}").json()["candidates"][0]["candidate_id"]
    # defer the worker: it never runs, job stays "running"
    monkeypatch.setattr(server, "_spawn", lambda fn, *a: spawned.append((fn, a)))
    assert c.post(f"{BASE}/{jid}/select", json={"candidate_id": cid}).status_code == 200
    assert len(spawned) == 1
    assert c.post(f"{BASE}/{jid}/select", json={"candidate_id": cid}).status_code == 409
    assert c.post(f"{BASE}/{jid}/retry").status_code == 409
    assert len(spawned) == 1
    assert c.get(f"{BASE}/{jid}").json()["running"] is True
    fn, a = spawned[0]
    fn(*a)
    assert c.get(f"{BASE}/{jid}").json()["running"] is False


def test_get_returns_snapshot_not_live_dict(client):
    jid = start(client)
    live = server.individual_jobs.get(jid)
    snap = client.get(f"{BASE}/{jid}").json()
    live["status"] = "mutated"
    assert snap["status"] == "completed"


def test_worker_clears_running_when_pipeline_factory_fails(monkeypatch):
    c = _install(monkeypatch, AnySearch([LI_A]))

    def boom():
        raise RuntimeError("no pipeline")

    monkeypatch.setattr(server, "make_individual_pipeline", boom)
    jid = start(c)
    job = c.get(f"{BASE}/{jid}").json()
    assert job["running"] is False and job["status"] == "failed" and job["errors"]


def test_make_pipeline_is_fresh_and_uses_company_slots():
    a, b = server.make_individual_pipeline(), server.make_individual_pipeline()
    assert a.github is not b.github and a.search is not b.search
    assert a.company_slots is server.company_research_slots


def test_spawn_starts_daemon_thread():
    ev = threading.Event()
    server._spawn(ev.set)
    assert ev.wait(2)


def test_individual_endpoints_require_auth_in_production(client, monkeypatch):
    monkeypatch.setattr(server, "APP_ENV", "production")
    monkeypatch.setattr(server, "API_SECRET_KEY", "k")
    assert client.post(BASE, json={"name": "Jane Doe"}).status_code == 401
    assert client.get(f"{BASE}/ind_0000000000000000").status_code == 401
    assert client.post(f"{BASE}/ind_0000000000000000/retry").status_code == 401
    assert client.post(f"{BASE}/ind_0000000000000000/select", json={"candidate_id": "x"}).status_code == 401
