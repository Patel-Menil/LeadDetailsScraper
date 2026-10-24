"""BAVRIX / SealAPI capability registry used for value mapping and outreach.

Every entry was checked against the SealAPI codebase (C:\\sealapi\\sealapi, commit 9bfc019, 2026-10-24).
`evidence` lists the files that implement it. "implemented" means code plus unit tests are present in
that repository; this registry does not claim those tests were executed here. Update this file when
the product changes - analysis and outreach may only rely on capabilities marked "implemented".
"""

from typing import Dict, List

POSITIONING = (
    "SealAPI, developed by BAVRIX, focuses on API credential protection, API access controls, "
    "and runtime security guardrails for AI endpoints."
)

# Scope note that applies to every mapping: SealAPI sits between applications and AI providers.
SCOPE_NOTE = (
    "SealAPI is a gateway between applications and AI model providers. It complements, and does not "
    "replace, an existing API gateway, identity provider or secrets manager."
)

CAPABILITIES: Dict[str, Dict[str, object]] = {
    "provider_credential_isolation": {
        "name": "AI provider credential shielding (BYOK)",
        "status": "implemented",
        "description": (
            "Provider API keys are stored as wrapped (KEK/DEK envelope) credentials and unwrapped by the "
            "gateway only after the security gate allows the request; client attempts to pass provider "
            "keys at runtime are rejected."
        ),
        "contribution": "keeps the model-provider key inside the SealAPI gateway instead of application configuration",
        "evidence": [
            "crates/sealapi-gateway/src/byok.rs (reject_client_provider_keys, unwrap_byok_api_key)",
            "crates/sealapi-security/src/vault.rs (unwrap_provider_credential)",
        ],
        "caveats": [],
    },
    "scoped_api_keys": {
        "name": "Per-service SealAPI keys with model allowlists",
        "status": "implemented",
        "description": (
            "Calling applications authenticate with SealAPI-issued keys stored only as hashes (Argon2id on the "
            "dashboard path); each key carries a tenant binding and a model allowlist."
        ),
        "contribution": "gives each calling service its own revocable key limited to approved models",
        "evidence": [
            "crates/sealapi-security/src/api_keys.rs (ApiKeyRecord.model_allowlist, compute_policy_hash)",
            "crates/sealapi-usage/src/lib.rs (UsageService::authenticate)",
        ],
        "caveats": [],
    },
    "rate_limiting": {
        "name": "Per-key rate limiting",
        "status": "implemented",
        "description": "Redis-backed per-key rate limits enforced on the gateway hot path.",
        "contribution": "caps request volume per calling key",
        "evidence": [
            "crates/sealapi-security/src/rate_limit.rs",
            "crates/sealapi-usage/src/lib.rs (check_rate_limit)",
        ],
        "caveats": [],
    },
    "key_misuse_circuit_breaker": {
        "name": "Credential-misuse detection and automatic key pause (ChainGuard)",
        "status": "implemented",
        "description": (
            "ChainGuard scores request metadata (traffic, IP/network, behaviour, model probing) and can pause "
            "a key through the circuit breaker."
        ),
        "contribution": "pauses a SealAPI key automatically when its metadata pattern looks like misuse",
        "evidence": [
            "crates/sealapi-security/src/circuit_breaker.rs (pause_key, is_key_paused)",
            "services/chainguard-api/app/pipeline/engine.py (inspect_request)",
            "services/chainguard-api/app/checks/ai_metadata.py",
        ],
        "caveats": ["Detection uses request metadata only; it does not read prompt content."],
    },
    "pre_dispatch_security_gate": {
        "name": "Fail-closed security decision before provider dispatch",
        "status": "implemented",
        "description": (
            "Every request needs a durable Allow decision from ChainGuard inspection before the gateway calls "
            "the provider; timeouts or missing decisions fail closed."
        ),
        "contribution": "enforces a policy decision on every application-to-AI request before it leaves",
        "evidence": [
            "crates/sealapi-gateway/src/security_gate.rs (FinalSecurityGate, GateDecision)",
            "crates/sealapi-gateway/src/security_gate_dispatch_test.rs",
        ],
        "caveats": [],
    },
    "sealed_payloads": {
        "name": "Client-side sealed request payloads",
        "status": "implemented",
        "description": (
            "SDKs (Python, TypeScript, Go) seal request payloads (X25519 + ChaCha20-Poly1305) so plaintext "
            "is only handled inside the gateway process."
        ),
        "contribution": "keeps prompt payloads sealed between the application and the gateway",
        "evidence": ["docs/wire-format.md", "sdks/python", "sdks/typescript", "sdks/go"],
        "caveats": ["Requires adopting the SealAPI SDK in the calling service."],
    },
    "mcp_tool_policy": {
        "name": "MCP tool permission policy and single-use execution permits",
        "status": "implemented",
        "description": (
            "Deterministic per-tool permission, parameter and intent-scope checks with signed single-use "
            "execution permits for agent tool calls routed through the SealAPI MCP gateway."
        ),
        "contribution": "limits which tools an AI agent may call and with which parameters",
        "evidence": [
            "crates/sealapi-mcp-kernel/src/mcp_enforcement.rs",
            "crates/sealapi-security/src/mcp_permit.rs",
        ],
        "caveats": ["Applies only to agent tool calls routed through the SealAPI MCP gateway."],
    },
    "hardware_tee_attestation": {
        "name": "Hardware TEE execution with attestation",
        "status": "partial",
        "description": (
            "Attestation exists with a mock TEE and a fail-closed Azure SEV-SNP software path; live hardware "
            "end-to-end verification on Azure DCasv5 is still open."
        ),
        "contribution": "",
        "evidence": ["crates/sealapi-attestation/src/azure_sev_snp.rs", "README.md (Live Azure DCasv5 e2e: open)"],
        "caveats": ["Do not claim hardware TEE protection in outreach until the live Azure gate passes."],
    },
    "prompt_content_inspection": {
        "name": "Prompt/response content inspection (PII redaction, prompt-injection detection)",
        "status": "not_supported",
        "description": "ChainGuard deliberately inspects metadata only and never reads prompt plaintext.",
        "contribution": "",
        "evidence": ["services/chainguard-api/app/checks/ai_metadata.py ('do not require prompt plaintext')"],
        "caveats": [],
    },
    "general_api_gateway": {
        "name": "Protection of a company's own customer-facing APIs or non-AI third-party integrations",
        "status": "not_supported",
        "description": (
            "SealAPI brokers calls to AI model providers. It does not issue, scope or monitor credentials for "
            "a company's own public API or for non-AI integrations (CRM, payments, EHR, etc.)."
        ),
        "contribution": "",
        "evidence": ["README.md ('SealAPI sits between enterprise apps and AI providers')"],
        "caveats": [],
    },
}

# Providers with a locally contract-verified adapter (docs/providers/FINAL-PROVIDER-SUPPORT-MATRIX.md).
# The same matrix reports LIVE_PROVIDER_VERIFIED_COUNT = 0, so compatibility always needs validation.
SUPPORTED_AI_PROVIDERS: List[str] = [
    "OpenAI", "Anthropic", "Google Gemini", "Google Vertex AI", "Amazon Bedrock", "Microsoft Azure AI",
    "Mistral AI", "Cohere", "DeepSeek", "Groq", "Fireworks AI", "Together AI", "Hugging Face",
    "NVIDIA NIM", "Perplexity", "Ollama", "xAI",
]
PROVIDER_CAVEAT = (
    "SealAPI's adapter for this provider is locally contract-verified; no provider is yet verified "
    "against live provider APIs."
)


def is_implemented(capability_id: str) -> bool:
    return CAPABILITIES.get(capability_id, {}).get("status") == "implemented"


def capability_summary() -> List[Dict[str, object]]:
    """Registry as a list for the API/UI."""
    return [{"id": cid, **info} for cid, info in CAPABILITIES.items()]
