from types import SimpleNamespace

from src.lead_research.live_products import (
    MAX_PROJECT_FETCHES,
    build_company_live_products,
    build_person_projects,
    classify_liveness,
)


def page(url, text="", links=None, success=True, category="products", headings=None, title=""):
    return {"url": url, "normalized_url": url, "text": text, "links": links or [], "success": success,
            "category": category, "headings": headings or [], "title": title, "meta_description": ""}


# ------------------------------------------------------------------ liveness
def test_signup_link_means_live():
    r = classify_liveness(page("https://acme.com/p/desk", "Acme Desk helps teams.",
                               links=[["https://app.acme.com/signup", "Sign up free"]]))
    assert r["status"] == "live"
    assert "Sign up" in r["signal"]


def test_pricing_text_means_live():
    r = classify_liveness(page("https://acme.com/p/desk", "Plans and pricing start at $10 per seat."))
    assert r["status"] == "live"
    assert "pricing" in r["signal"].lower()


def test_app_store_link_means_live():
    r = classify_liveness(page("https://acme.com/p/app", "Our mobile app.",
                               links=[["https://apps.apple.com/app/id123", "App"]]))
    assert r["status"] == "live"


def test_beta_with_signup_is_live_beta():
    r = classify_liveness(page("https://acme.com/p/ai", "Acme AI is now in public beta. Get started today."))
    assert r["status"] == "beta"


def test_waitlist_is_not_live_even_with_site_login():
    r = classify_liveness(page("https://acme.com/p/next", "Acme Next is coming soon. Join the waitlist.",
                               links=[["https://acme.com/login", "Log in"]]))
    assert r["status"] == "not_live"
    assert "coming soon" in r["signal"].lower()


def test_discontinued_product():
    r = classify_liveness(page("https://acme.com/p/old", "Acme Classic has been discontinued. Pricing is archived."),
                          product_name="Acme Classic")
    assert r["status"] == "discontinued"


def test_unrelated_sunset_word_does_not_discontinue():
    r = classify_liveness(page("https://acme.com/p/desk", "Work from sunrise to sunset. Start free trial."),
                          product_name="Acme Desk")
    assert r["status"] == "live"


def test_strong_signal_beats_nav_login():
    r = classify_liveness(page("https://acme.com/p/desk", "Acme Desk. Start free trial.",
                               links=[["https://acme.com/login", "Log in"]]))
    assert r["status"] == "live"
    assert "free trial" in r["signal"].lower()


def test_login_alone_still_counts_as_live():
    r = classify_liveness(page("https://acme.com/p/desk", "Acme Desk.", links=[["https://acme.com/login", "Log in"]]))
    assert r["status"] == "live"
    assert "Log in" in r["signal"]


def test_failed_page_and_no_signal_are_unknown():
    assert classify_liveness(page("https://acme.com/p/x", success=False))["status"] == "unknown"
    assert classify_liveness(page("https://acme.com/p/x", "Acme X is a product."))["status"] == "unknown"


# ------------------------------------------------------------------ company products
def test_company_live_products_split_and_ai_link():
    products = [
        {"name": "Desk", "url": "https://acme.com/p/desk", "url_normalized": "https://acme.com/p/desk",
         "description": "Help desk", "features": ["Inbox"], "inferred": False},
        {"name": "Next", "url": "https://acme.com/p/next", "url_normalized": "https://acme.com/p/next",
         "description": "Future", "features": [], "inferred": False},
    ]
    pages = [
        page("https://acme.com/p/desk", "Start free trial."),
        page("https://acme.com/p/next", "Coming soon. Join the waitlist."),
        page("https://acme.com/ai", "Acme Copilot drafts replies. Get started.", category="ai",
             headings=["Acme Copilot", "Features"]),
    ]
    use_cases = [{"product": "Desk", "types": ["generative"], "purposes": ["customer_support"]}]
    out = build_company_live_products(products, pages, use_cases)
    names = [p["name"] for p in out["live"]]
    assert names == ["Desk", "Acme Copilot"]
    desk = out["live"][0]
    assert desk["status"] == "live" and desk["status_label"] == "Live"
    assert desk["ai_types"] == ["generative"] and desk["ai_purposes"] == ["customer_support"]
    assert out["live"][1]["source"] == "ai_page"
    assert [(p["name"], p["status"]) for p in out["excluded"]] == [("Next", "not_live")]
    assert out["excluded"][0]["reason"]


def test_ai_page_already_a_product_is_not_duplicated():
    products = [{"name": "Copilot", "url": "https://acme.com/ai", "url_normalized": "https://acme.com/ai",
                 "description": "", "features": [], "inferred": False}]
    pages = [page("https://acme.com/ai", "Get started.", category="ai", headings=["Copilot"])]
    out = build_company_live_products(products, pages, [])
    assert [p["name"] for p in out["live"]] == ["Copilot"]


# ------------------------------------------------------------------ person projects
def repo(name, homepage="", fork=False, archived=False, pushed="2026-01-01T00:00:00Z", desc="", topics=None):
    return {"name": name, "homepage": homepage, "fork": fork, "archived": archived, "pushed_at": pushed,
            "description": desc, "topics": topics or [], "language": "Python", "stargazers_count": 3,
            "html_url": f"https://github.com/me/{name}"}


class FakeFetch:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url):
        self.calls.append(url)
        p = self.pages.get(url)
        if p is None:
            return SimpleNamespace(url=url, success=False, status_code=404, links=[])
        return SimpleNamespace(url=url, success=True, status_code=200, links=p)


def test_repos_live_when_homepage_loads_and_code_only_otherwise():
    fetch = FakeFetch({"https://good.dev": []})
    repos = [
        repo("good", homepage="https://good.dev", pushed="2026-03-01T00:00:00Z", desc="An LLM chat assistant"),
        repo("down", homepage="down.dev", pushed="2026-02-01T00:00:00Z"),
        repo("plain", pushed="2026-04-01T00:00:00Z"),
        repo("forked", homepage="https://f.dev", fork=True),
        repo("old", homepage="https://o.dev", archived=True),
        repo("self", homepage="https://github.com/me/self"),
    ]
    out = build_person_projects(repos, fetch)
    assert [p["name"] for p in out["live"]] == ["good"]
    assert out["live"][0]["status"] == "live"
    assert "generative" in out["live"][0]["ai_types"]
    code_only = {p["name"]: p["status"] for p in out["code_only"]}
    assert code_only == {"plain": "code_only", "down": "down", "self": "code_only"}
    assert "https://down.dev" in fetch.calls  # scheme added
    assert not any("f.dev" in c or "o.dev" in c or "github.com" in c for c in fetch.calls)


def test_repo_checks_are_capped():
    fetch = FakeFetch({})
    repos = [repo(f"r{i}", homepage=f"https://r{i}.dev", pushed=f"2026-01-{10 + i}T00:00:00Z") for i in range(8)]
    out = build_person_projects(repos, fetch)
    assert len(fetch.calls) == 3
    assert sum(1 for p in out["code_only"] if p["status"] == "not_checked") >= 3


def test_personal_site_projects_from_projects_page():
    fetch = FakeFetch({
        "https://me.dev": [["https://me.dev/projects", "Projects"], ["https://linkedin.com/in/me", "LinkedIn"]],
        "https://me.dev/projects": [
            ["https://coolapp.io", "Cool App"], ["https://dead.io", "Dead App"],
            ["https://twitter.com/me", "Twitter"], ["https://github.com/me/x", "Source"],
            ["https://me.dev/about", "About"],
        ],
        "https://coolapp.io": [],
    })
    out = build_person_projects([], fetch, website="https://me.dev")
    assert [(p["name"], p["url"]) for p in out["site"]] == [("Cool App", "https://coolapp.io")]
    assert out["checks_used"] <= MAX_PROJECT_FETCHES
    assert not any("twitter" in c or "linkedin" in c or "github.com" in c for c in fetch.calls)


def test_personal_site_without_projects_page_adds_nothing():
    fetch = FakeFetch({"https://me.dev": [["https://employer.com", "Employer"]]})
    out = build_person_projects([], fetch, website="https://me.dev")
    assert out["site"] == []
    assert fetch.calls == ["https://me.dev"]


def test_total_fetch_budget_is_respected():
    fetch = FakeFetch({
        "https://me.dev": [["https://me.dev/work", "Work"]],
        "https://me.dev/work": [[f"https://app{i}.io", f"App {i}"] for i in range(10)],
    })
    repos = [repo(f"r{i}", homepage=f"https://r{i}.dev", pushed=f"2026-01-{10 + i}T00:00:00Z") for i in range(5)]
    out = build_person_projects(repos, fetch, website="https://me.dev")
    assert len(fetch.calls) == MAX_PROJECT_FETCHES
    assert out["checks_used"] == MAX_PROJECT_FETCHES


def test_fetch_exceptions_are_contained():
    def boom(url):
        raise RuntimeError("network down")
    out = build_person_projects([repo("a", homepage="https://a.dev")], boom, website="https://me.dev")
    assert out["live"] == []
    assert out["code_only"][0]["status"] == "down"
