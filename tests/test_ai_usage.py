from src.lead_research.ai_usage import (
    extract_ai_use_cases,
    is_ai_sentence,
    summarize_ai_usage,
    tag_ai_text,
)


def page(url, text, category="products", title="Page"):
    return {"url": url, "normalized_url": url, "text": text, "meta_description": "", "title": title,
            "category": category, "success": True}


# ------------------------------------------------------------------ sentence gate
def test_ai_sentence_gate_accepts_ai_and_rejects_lookalikes():
    assert is_ai_sentence("Our AI assistant drafts replies to customer emails.")
    assert is_ai_sentence("Built on large language models from OpenAI.")
    assert is_ai_sentence("Deploy AI agents that resolve tickets end to end.")
    assert not is_ai_sentence("Talk to one of our support agents today.")
    assert not is_ai_sentence("Contact our assistant manager for billing.")
    assert not is_ai_sentence("We said it again and again.")  # 'ai' inside words is not AI


# ------------------------------------------------------------------ tagging
def test_generative_support_tagging():
    tags = tag_ai_text("Our AI assistant drafts replies to customer support tickets.")
    assert "generative" in tags["types"]
    assert "customer_support" in tags["purposes"]


def test_agentic_workflow_tagging():
    tags = tag_ai_text("AI agents that take actions across your tools to automate workflows on your behalf.")
    assert "agentic" in tags["types"]
    assert "workflow_automation" in tags["purposes"]


def test_predictive_fraud_tagging():
    tags = tag_ai_text("Machine learning models detect fraud and score transaction risk in real time.")
    assert tags["types"] == ["predictive"]
    assert "security_fraud" in tags["purposes"]


def test_retrieval_search_tagging():
    tags = tag_ai_text("AI-powered semantic search answers questions from your docs using RAG.")
    assert "retrieval" in tags["types"]
    assert "search_knowledge" in tags["purposes"]


def test_stage_detection():
    assert tag_ai_text("Our AI copilot is now in beta.")["stage"] == "beta"
    assert tag_ai_text("The AI copilot is now generally available.")["stage"] == "ga"
    assert tag_ai_text("We use machine learning to rank results.")["stage"] == "unspecified"


def test_untyped_ai_sentence_is_general_and_other():
    tags = tag_ai_text("We are an AI company.")
    assert tags["types"] == ["general"]
    assert tags["purposes"] == ["other"]


# ------------------------------------------------------------------ extraction
def test_use_cases_carry_context_source_and_product():
    pages = [
        page("https://acme.com/products/desk", "Acme Desk is great. Our AI assistant drafts replies to support tickets.",
             category="products"),
        page("https://acme.com/careers", "We are hiring engineers to build LLM evaluation pipelines.", category="careers"),
    ]
    products = {"https://acme.com/products/desk": "Acme Desk"}
    cases = extract_ai_use_cases(pages, product_names=products)
    assert len(cases) == 2
    desk = next(c for c in cases if c["source_url"].endswith("/desk"))
    assert desk["context"] == "product"
    assert desk["product"] == "Acme Desk"
    assert "drafts replies" in desk["evidence"]
    hiring = next(c for c in cases if c["source_url"].endswith("/careers"))
    assert hiring["context"] == "hiring_internal"
    assert hiring["product"] == ""


def test_use_cases_are_capped_deduped_and_skip_failed_pages():
    many = " ".join(f"Our AI assistant number {i} drafts replies for customers." for i in range(10))
    pages = [
        page("https://acme.com/a", many),
        page("https://acme.com/b", "Our AI assistant number 1 drafts replies for customers."),  # duplicate sentence
        {**page("https://acme.com/c", "Our AI agents automate workflows."), "success": False},
    ]
    cases = extract_ai_use_cases(pages, per_page=4, total=20)
    assert len([c for c in cases if c["source_url"].endswith("/a")]) == 4
    assert not any(c["source_url"].endswith("/c") for c in cases)
    texts = [c["evidence"] for c in cases]
    assert len(texts) == len(set(texts))


def test_use_cases_total_cap_prefers_ai_and_product_pages():
    pages = [page(f"https://acme.com/careers{i}", "We hire people to build LLM tools. Our AI agents automate workflows.",
                  category="careers") for i in range(3)]
    pages.append(page("https://acme.com/ai", "Our AI copilot drafts code for developers.", category="ai"))
    cases = extract_ai_use_cases(pages, per_page=4, total=2)
    assert len(cases) == 2
    assert cases[0]["source_url"] == "https://acme.com/ai"


def test_evidence_is_length_limited():
    long = "Our AI assistant drafts replies " + "and more " * 100 + "."
    cases = extract_ai_use_cases([page("https://acme.com/x", long)])
    assert len(cases[0]["evidence"]) <= 280


# ------------------------------------------------------------------ summary
def test_summary_counts_types_purposes_and_stage():
    cases = [
        {"types": ["generative"], "purposes": ["customer_support"], "stage": "ga", "context": "product"},
        {"types": ["generative", "agentic"], "purposes": ["customer_support", "workflow_automation"],
         "stage": "beta", "context": "product"},
        {"types": ["predictive"], "purposes": ["security_fraud"], "stage": "unspecified", "context": "hiring_internal"},
    ]
    s = summarize_ai_usage(cases, providers=["OpenAI"])
    assert s["type_counts"] == {"generative": 2, "agentic": 1, "predictive": 1, "retrieval": 0, "general": 0}
    assert s["primary_type"] == "generative"
    assert s["purposes"][0] == {"purpose": "customer_support", "label": "Customer support", "count": 2}
    assert s["stage"] == "ga"
    assert s["contexts"] == {"product": 2, "hiring_internal": 1, "company": 0}
    assert s["providers"] == ["OpenAI"]


def test_summary_empty():
    s = summarize_ai_usage([], providers=[])
    assert s["primary_type"] == ""
    assert s["purposes"] == []
    assert s["stage"] == "unspecified"


def test_sdk_api_and_gateway_wording_counts_as_developer_tooling():
    assert "coding" in tag_ai_text("Build AI applications and agents with the AI SDK, the TypeScript toolkit.")["purposes"]
    assert "coding" in tag_ai_text("Use 400+ AI models without managing rate limits and API keys.")["purposes"]


def test_short_headlines_are_not_use_cases():
    cases = extract_ai_use_cases([page("https://acme.com/ai", "AI Gateway pricing docs\nWorks with your AI stack")])
    assert cases == []


def test_singular_product_category_is_product_context_and_prioritised():
    pages = [page("https://acme.com/careers", "We hire engineers to build LLM evaluation tools.", category="careers"),
             page("https://acme.com/products/x", "Our AI assistant drafts replies for your customers.",
                  category="product")]
    cases = extract_ai_use_cases(pages, total=1)
    assert cases[0]["source_url"] == "https://acme.com/products/x"
    assert cases[0]["context"] == "product"
