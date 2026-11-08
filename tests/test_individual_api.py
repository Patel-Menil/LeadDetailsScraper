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
    monkeypatch.setattr(server, "make_individual_pipeline", lambda *_a, **_k: IndividualPipeline(
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

    def mk(*a, **k):
        p = orig(*a, **k)
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

    def boom(*_a, **_k):
        raise RuntimeError("no pipeline")

    monkeypatch.setattr(server, "make_individual_pipeline", boom)
    jid = start(c)
    job = c.get(f"{BASE}/{jid}").json()
    assert job["running"] is False and job["status"] == "failed" and job["errors"]


def test_make_pipeline_is_fresh_and_uses_company_slots():
    direct = {"use_browser": False, "use_tor": False}  # no Tor probing in unit tests
    a, b = server.make_individual_pipeline(direct), server.make_individual_pipeline(direct)
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


def test_no_second_worker_between_pipeline_clear_and_worker_finally(monkeypatch):
    class Crash:
        def __init__(self, store):
            pass

        def research(self, record):
            raise RuntimeError("boom")

    c = _install(monkeypatch, AnySearch([LI_A]))
    base_factory = server.make_individual_pipeline

    def crash_factory(*_a, **_k):
        p = base_factory()
        p.company_researcher = Crash
        return p

    monkeypatch.setattr(server, "make_individual_pipeline", crash_factory)
    jid = start(c)
    assert c.get(f"{BASE}/{jid}").json()["status"] == "partial"

    gate, spawned, threads = threading.Event(), [], []

    class Gated:
        def __init__(self, inner):
            self.inner = inner

        def run(self, job, stage="discovery"):
            self.inner.run(job, stage)  # pipeline clears job["running"] here
            gate.wait(5)  # worker has not reached its finally yet

        def retry_stage(self, job):
            return self.inner.retry_stage(job)

    monkeypatch.setattr(server, "make_individual_pipeline", lambda *_a, **_k: Gated(crash_factory()))

    def spawn(fn, *a):
        spawned.append(a)
        t = threading.Thread(target=fn, args=a, daemon=True)
        threads.append(t)
        t.start()

    monkeypatch.setattr(server, "_spawn", spawn)
    assert c.post(f"{BASE}/{jid}/retry").status_code == 200
    job = server.individual_jobs.get(jid)
    for _ in range(200):
        if job["running"] is False:
            break
        threading.Event().wait(0.01)
    assert job["running"] is False  # pipeline already cleared the display flag
    assert c.post(f"{BASE}/{jid}/retry").status_code == 409
    assert len(spawned) == 1
    gate.set()
    threads[0].join(5)
    assert c.post(f"{BASE}/{jid}/retry").status_code == 200  # admitted again once the worker finished
    gate.set()
    threads[-1].join(5)


def test_spawn_failure_after_select_leaves_job_failed_and_retryable(client_ambiguous, monkeypatch):
    c = client_ambiguous
    jid = start(c, github_url="", company="")
    cid = c.get(f"{BASE}/{jid}").json()["candidates"][0]["candidate_id"]

    def boom(fn, *a):
        raise RuntimeError("cannot start thread")

    monkeypatch.setattr(server, "_spawn", boom)
    with pytest.raises(RuntimeError):
        c.post(f"{BASE}/{jid}/select", json={"candidate_id": cid})
    job = c.get(f"{BASE}/{jid}").json()
    assert job["status"] == "failed" and job["running"] is False
    assert any(e.startswith("company_discovery: failed") for e in job["errors"])
    monkeypatch.setattr(server, "_spawn", lambda fn, *a: fn(*a))
    assert c.post(f"{BASE}/{jid}/retry").status_code == 200
    assert c.get(f"{BASE}/{jid}").json()["status"] in ("completed", "partial")


def test_context_is_limited_to_1000_characters(client):
    jid = start(client, context="x" * 1000)
    assert client.get(f"{BASE}/{jid}").json()["input"]["context"] == "x" * 1000
    r = client.post(BASE, json={"name": "Jane Doe", "context": "x" * 1001})
    assert r.status_code == 422


def test_search_options_default_on_and_are_reused_for_select_and_retry(monkeypatch):
    seen = []
    c = _install(monkeypatch, AnySearch([LI_A]))
    inner = server.make_individual_pipeline

    def mk(options=None):
        seen.append(options)
        return inner(options)

    monkeypatch.setattr(server, "make_individual_pipeline", mk)
    jid = start(c)
    job = c.get(f"{BASE}/{jid}").json()
    assert job["search_options"] == {"use_browser": True, "use_tor": True}
    assert "use_browser" not in job["input"] and "use_tor" not in job["input"]
    assert seen[-1] == {"use_browser": True, "use_tor": True}

    jid2 = start(c, use_browser=False, use_tor=False)
    assert c.get(f"{BASE}/{jid2}").json()["search_options"] == {"use_browser": False, "use_tor": False}
    assert seen[-1] == {"use_browser": False, "use_tor": False}


def test_pipeline_factory_routes_search_through_stealth_browser_and_tor(monkeypatch):
    from src.lead_research.tor_manager import TorManager
    monkeypatch.setattr(TorManager, "get_proxy_url", lambda self, require_reachable=True: "socks5://tor:9050")
    p = server.make_individual_pipeline({"use_browser": True, "use_tor": True})
    scraper = p.search.scraper
    assert scraper.use_tor is True and scraper.proxy == "socks5://tor:9050"
    assert scraper.use_browser == server.HAS_STEALTHY_FETCHER
    direct = server.make_individual_pipeline({"use_browser": False, "use_tor": False}).search.scraper
    assert direct.use_tor is False and direct.proxy is None and direct.use_browser is False
