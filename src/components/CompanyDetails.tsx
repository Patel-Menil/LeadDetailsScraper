"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Building,
  Check,
  CheckCircle2,
  Copy,
  Cpu,
  ExternalLink,
  FileSearch,
  Globe,
  HelpCircle,
  Layers,
  Network,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  Sparkles,
  Target,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { companyStatusMeta, shouldPoll, FIT_TONE } from "@/lib/companyIntel.mjs";
import {
  CompanyFinding,
  CompanyOutreach,
  CompanyProduct,
  CompanyRecord,
  CompanyView,
  ReviewStatus,
} from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";

type Tone = "success" | "warning" | "danger" | "info" | "neutral";

const TECH_CATEGORIES: { id: string; title: string }[] = [
  { id: "api", title: "APIs & developer platform" },
  { id: "integrations", title: "Third-party integrations" },
  { id: "ai", title: "AI / LLM adoption" },
  { id: "ai_provider", title: "Named model providers" },
  { id: "cloud", title: "Cloud infrastructure" },
  { id: "client_app", title: "Client applications" },
  { id: "security_controls", title: "Security & compliance documentation" },
  { id: "sensitive_data", title: "Sensitive data handled" },
  { id: "hiring", title: "Relevant hiring" },
];

const COMPAT_META: Record<string, { label: string; tone: Tone }> = {
  compatible_pending_validation: { label: "Compatible — pending validation", tone: "success" },
  requires_validation: { label: "Requires validation", tone: "info" },
  not_supported: { label: "Not currently supported", tone: "neutral" },
};

function pct(value: number | undefined) {
  return `${Math.round((value || 0) * 100)}%`;
}

function SourceLink({ url, label }: { url: string; label?: string }) {
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-[11px] font-mono text-blue-400 hover:text-blue-300 break-all"
    >
      <span>{label || url}</span>
      <ExternalLink className="w-3 h-3 shrink-0" />
    </a>
  );
}

function Section({
  letter,
  title,
  description,
  icon,
  children,
}: {
  letter: string;
  title: string;
  description?: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-white flex items-center gap-2">
          <span className="text-[10px] font-mono text-slate-500 border border-[#1a3a5f] rounded px-1.5 py-0.5">{letter}</span>
          {icon}
          <span>{title}</span>
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">{label}</div>
      <div className="text-xs text-slate-200 leading-relaxed">{children}</div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-slate-500">{children}</p>;
}

function ReviewBadge({ status }: { status: ReviewStatus }) {
  const tone: Record<ReviewStatus, Tone> = { verified: "success", rejected: "danger", needs_review: "warning", unreviewed: "neutral" };
  return <Badge variant={tone[status]}>{status.replace("_", " ")}</Badge>;
}

function ReviewButtons({
  finding,
  disabled,
  onReview,
}: {
  finding: CompanyFinding;
  disabled: boolean;
  onReview: (id: string, status: ReviewStatus) => void;
}) {
  const options: { status: ReviewStatus; label: string; icon: React.ReactNode }[] = [
    { status: "verified", label: "Verify", icon: <CheckCircle2 className="w-3 h-3" /> },
    { status: "needs_review", label: "Needs review", icon: <HelpCircle className="w-3 h-3" /> },
    { status: "rejected", label: "Reject", icon: <XCircle className="w-3 h-3" /> },
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.status}
          type="button"
          disabled={disabled || finding.verification_status === o.status}
          onClick={() => onReview(finding.finding_id, o.status)}
          aria-label={`${o.label}: ${finding.label}`}
          className="inline-flex items-center gap-1 px-2 py-1 rounded border border-[#1a3a5f] text-[10px] text-slate-300 hover:border-blue-500/50 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {o.icon}
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

function FindingLine({ f }: { f: CompanyFinding }) {
  return (
    <li className="p-2.5 rounded-lg bg-[#061a33] border border-[#1a3a5f]/80 space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-white">{f.label}</span>
        <span className="text-[10px] font-mono text-slate-400">confidence {pct(f.confidence)}</span>
        <ReviewBadge status={f.verification_status} />
        {f.product_id === null && <span className="text-[10px] text-slate-500">company-level</span>}
      </div>
      <p className="text-xs text-slate-300 italic">&ldquo;{f.evidence}&rdquo;</p>
      <SourceLink url={f.source_url} />
    </li>
  );
}

function ArchitectureView({ product }: { product: CompanyProduct }) {
  const arch = product.architecture;
  if (!arch) return null;
  const names = Object.fromEntries(arch.components.map((c) => [c.id, c.name]));
  return (
    <div className="p-4 rounded-xl bg-[#0b2545] border border-[#1a3a5f] space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-white">{product.name}</span>
        <Badge variant={arch.status === "documented" ? "success" : arch.status === "partial" ? "warning" : "neutral"}>
          architecture: {arch.status}
        </Badge>
      </div>
      {arch.limitation && (
        <p className="text-xs text-amber-300 flex items-start gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>{arch.limitation}</span>
        </p>
      )}
      {arch.components.length === 0 ? (
        <Empty>No architectural components are documented in public sources.</Empty>
      ) : (
        <>
          <div className="flex flex-wrap gap-2" role="list" aria-label={`${product.name} components`}>
            {arch.components.map((c) => (
              <div
                key={c.id}
                role="listitem"
                className={`px-3 py-2 rounded-lg text-xs max-w-[260px] ${
                  c.documented
                    ? "border border-blue-500/40 bg-blue-500/5 text-slate-200"
                    : "border border-dashed border-slate-600 text-slate-400"
                }`}
                title={c.unknowns.join("; ")}
              >
                <div className="font-semibold">{c.name}</div>
                <div className="text-[10px] text-slate-400">
                  {c.documented ? `documented · ${pct(c.confidence)}` : "inferred — validate"}
                </div>
                {c.sealapi_relevance && <div className="text-[10px] text-purple-300 mt-0.5">{c.sealapi_relevance}</div>}
              </div>
            ))}
          </div>
          {arch.flows.length > 0 && (
            <ul className="space-y-1.5">
              {arch.flows.map((fl, i) => (
                <li key={i} className="text-xs text-slate-300 flex flex-wrap items-center gap-1.5">
                  <span className="font-medium">{names[fl.from]}</span>
                  <ArrowRight className="w-3 h-3 text-slate-500" />
                  <span className="font-medium">{names[fl.to]}</span>
                  <span className="text-slate-500">— {fl.data}</span>
                  <Badge variant={fl.documented ? "success" : "neutral"}>{fl.documented ? "documented" : "inferred"}</Badge>
                  {fl.crosses_trust_boundary && <Badge variant="warning">trust boundary</Badge>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {arch.unknowns.length > 0 && (
        <Field label="Unknown implementation details">
          <ul className="list-disc list-inside text-slate-400 space-y-0.5">
            {arch.unknowns.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </Field>
      )}
    </div>
  );
}

export function CompanyDetails({ leadId, batchId, jobTitle }: { leadId: string; batchId?: string; jobTitle?: string }) {
  const [view, setView] = useState<CompanyView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [domainInput, setDomainInput] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await api.getLeadCompany(leadId, batchId);
      setView(res);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Failed to load company research.");
    } finally {
      setLoading(false);
    }
  }, [leadId, batchId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!shouldPoll(view)) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [view, load]);

  const act = async (fn: () => Promise<unknown>) => {
    if (acting) return; // prevent duplicate submissions from repeated clicks
    setActing(true);
    setActionError(null);
    try {
      const res = await fn();
      if (res && typeof res === "object" && "company" in (res as object)) setView(res as CompanyView);
      else await load();
    } catch (err: any) {
      setActionError(err?.message || "Action failed.");
      await load();
    } finally {
      setActing(false);
    }
  };

  const startResearch = (refresh: boolean) => act(() => api.startLeadCompanyResearch(leadId, batchId, refresh));
  const review = (findingId: string, status: ReviewStatus) =>
    view && act(() => api.reviewCompanyFinding(view.company_id, findingId, status));

  const company: CompanyRecord | undefined = view?.company;
  const findingsById = useMemo(
    () => Object.fromEntries((company?.findings || []).map((f) => [f.finding_id, f])),
    [company]
  );

  if (loading) {
    return (
      <div className="p-10 text-center text-slate-400 space-y-3">
        <div className="w-7 h-7 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-sm">Loading company research...</p>
      </div>
    );
  }

  if (error || !view || !company) {
    return (
      <div className="p-5 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 text-sm flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
        <div className="space-y-2">
          <p>{error || "Company research is unavailable."}</p>
          <Button size="sm" variant="outline" onClick={load}>Try again</Button>
        </div>
      </div>
    );
  }

  const meta = companyStatusMeta(view.research_status, view.job_running, Boolean(company.normalized_domain));
  const usable = company.findings.filter((f) => f.verification_status !== "rejected");
  const progress = company.progress || { stage: "", pages_done: 0, pages_planned: 0 };
  const showResults = company.pages.length > 0 || company.products.length > 0;

  return (
    <div className="space-y-6">
      {/* Status, actions and progress */}
      <Card>
        <CardContent className="p-5 space-y-4">
          <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              {company.overview?.logo_url ? (
                <img
                  src={company.overview.logo_url}
                  alt={`${company.overview.official_name || company.canonical_name} logo`}
                  className="w-12 h-12 rounded-lg object-contain bg-white/5 border border-[#1a3a5f]"
                />
              ) : (
                <div className="w-12 h-12 rounded-lg bg-[#0b2545] border border-[#1a3a5f] flex items-center justify-center">
                  <Building className="w-5 h-5 text-slate-500" />
                </div>
              )}
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-bold text-white">{company.overview?.official_name || company.canonical_name}</h2>
                  <Badge variant={meta.tone as Tone} className={meta.busy ? "animate-pulse" : ""}>{meta.label}</Badge>
                  {company.company_fit && meta.hasResults && (
                    <Badge variant={FIT_TONE[company.company_fit.classification] as Tone}>{company.company_fit.label}</Badge>
                  )}
                </div>
                <div className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
                  <span className="font-mono">{company.normalized_domain || "no domain"}</span>
                  <span>
                    Last researched: {company.last_researched_at ? formatDateTime(company.last_researched_at) : "never"}
                  </span>
                  <span>Leads linked: {company.lead_refs?.length || 0}</span>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {meta.canStart && (
                <Button size="sm" onClick={() => startResearch(false)} disabled={acting} className="gap-1.5 text-xs">
                  <Search className="w-3.5 h-3.5" />
                  <span>Start company research</span>
                </Button>
              )}
              {meta.canRetry && (
                <Button size="sm" variant="danger" onClick={() => startResearch(false)} disabled={acting} className="gap-1.5 text-xs">
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Retry research</span>
                </Button>
              )}
              {meta.canRefresh && (
                <Button size="sm" variant="secondary" onClick={() => startResearch(true)} disabled={acting} className="gap-1.5 text-xs">
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Refresh research</span>
                </Button>
              )}
              {meta.hasResults && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => act(() => api.regenerateCompanyAnalysis(view.company_id))}
                  disabled={acting || meta.busy}
                  className="gap-1.5 text-xs"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>Regenerate opportunity analysis</span>
                </Button>
              )}
              {company.official_website && (
                <a href={company.official_website} target="_blank" rel="noopener noreferrer">
                  <Button size="sm" variant="ghost" className="gap-1.5 text-xs">
                    <Globe className="w-3.5 h-3.5" />
                    <span>Official website</span>
                    <ExternalLink className="w-3 h-3" />
                  </Button>
                </a>
              )}
            </div>
          </div>

          {meta.busy && (
            <div className="space-y-1.5" role="status" aria-live="polite">
              <div className="flex justify-between text-[11px] text-slate-400 font-mono">
                <span>Researching official pages ({progress.stage || "queued"})</span>
                <span>
                  {progress.pages_done}/{progress.pages_planned || "?"} pages
                </span>
              </div>
              <div className="h-1.5 rounded bg-[#0b2545] overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all"
                  style={{
                    width: `${progress.pages_planned ? Math.min(100, (progress.pages_done / progress.pages_planned) * 100) : 10}%`,
                  }}
                />
              </div>
            </div>
          )}

          {actionError && (
            <div className="p-3 rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-300 text-xs">{actionError}</div>
          )}
          {company.errors?.length > 0 && view.research_status === "failed" && (
            <div className="p-3 rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-300 text-xs space-y-1">
              <div className="font-semibold">Research failed</div>
              {company.errors.map((e, i) => (
                <div key={i}>{e}</div>
              ))}
            </div>
          )}
          {company.research_warnings?.length > 0 && (
            <div className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/5 text-amber-300 text-xs space-y-1">
              {company.research_warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}

          {meta.needsDomain && (
            <form
              className="flex flex-col sm:flex-row gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (domainInput.trim()) act(() => api.setCompanyDomain(view.company_id, domainInput.trim()));
              }}
            >
              <label className="sr-only" htmlFor="company-domain">Official company domain</label>
              <input
                id="company-domain"
                value={domainInput}
                onChange={(e) => setDomainInput(e.target.value)}
                placeholder="Set the official domain, e.g. example.com"
                className="flex-1 px-3 py-2 rounded-lg bg-[#061a33] border border-[#1a3a5f] text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
              />
              <Button size="sm" type="submit" disabled={acting || !domainInput.trim()}>Save domain</Button>
            </form>
          )}
        </CardContent>
      </Card>

      {!showResults && !meta.busy && (
        <div className="p-8 rounded-xl border border-dashed border-[#1a3a5f] text-center space-y-2">
          <FileSearch className="w-6 h-6 text-slate-500 mx-auto" />
          <p className="text-sm text-slate-300">No company research yet.</p>
          <p className="text-xs text-slate-500 max-w-lg mx-auto">
            Research reads public pages on {company.normalized_domain || "the company's official domain"} only (robots.txt
            respected, no scanning or probing), then maps documented products to SealAPI&apos;s verified capabilities.
          </p>
        </div>
      )}

      {showResults && (
        <>
          {/* A. Company overview */}
          <Section letter="A" title="Company Overview" icon={<Building className="w-4 h-4 text-blue-400" />}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="Official website">
                {company.official_website ? <SourceLink url={company.official_website} /> : "—"}
              </Field>
              <Field label="Domain">
                <span className="font-mono">{company.normalized_domain}</span>{" "}
                <span className="text-slate-500">(from {company.domain_source.replace("_", " ")})</span>
              </Field>
              <Field label="Identity check">
                {company.identity_corroborated ? "Corroborated on official site" : company.corroboration_note || "Not corroborated"}
              </Field>
              <Field label="Industry (input file)">{company.input_context?.industry || "—"}</Field>
              <Field label="Headquarters (input file)">{company.input_context?.headquarters || "—"}</Field>
              <Field label="Company size (input file)">
                {company.input_context?.employee_range ? `${company.input_context.employee_range} employees` : "—"}
              </Field>
              <Field label="Business model">{(company.overview?.business_model || []).join("; ") || "—"}</Field>
              <Field label="Products & services">
                {company.products.map((p) => p.name).join(", ") || "—"}
              </Field>
            </div>
            <Field label="Company description (official site)">
              {company.overview?.description ? <span className="italic">&ldquo;{company.overview.description}&rdquo;</span> : "Not published in page metadata."}
            </Field>
            <Field label="Documented markets / customer segments">
              {company.overview?.customer_segments ? (
                <span className="italic">&ldquo;{company.overview.customer_segments}&rdquo;</span>
              ) : (
                "Not determined from public sources."
              )}
            </Field>
          </Section>

          {/* B. Technology & integrations */}
          <Section
            letter="B"
            title="Technology and Integrations"
            description="Quoted from official pages; confidence reflects where on the page the evidence appeared"
            icon={<Cpu className="w-4 h-4 text-emerald-400" />}
          >
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {TECH_CATEGORIES.map((cat) => {
                const items = usable.filter((f) => f.category === cat.id);
                return (
                  <div key={cat.id} className="space-y-2">
                    <h4 className="text-xs font-semibold text-slate-300">{cat.title}</h4>
                    {items.length === 0 ? (
                      <Empty>No public evidence found.</Empty>
                    ) : (
                      <ul className="space-y-2">
                        {items.slice(0, 4).map((f) => (
                          <FindingLine key={f.finding_id} f={f} />
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
            <Field label="Developer resources consulted">
              <div className="flex flex-col gap-1">
                {company.pages.filter((p) => p.success && p.category === "developer").map((p) => (
                  <SourceLink key={p.url} url={p.url} label={p.title || p.url} />
                ))}
                {!company.pages.some((p) => p.success && p.category === "developer") && "None found."}
              </div>
            </Field>
          </Section>

          {/* C. Products */}
          <Section
            letter="C"
            title="Company Products"
            description="Ranked by potential relevance to SealAPI (see section G for the scoring factors)"
            icon={<Layers className="w-4 h-4 text-purple-400" />}
          >
            {company.products.length === 0 && <Empty>No products could be identified.</Empty>}
            {company.products.map((p) => (
              <div key={p.product_id} className="p-4 rounded-xl bg-[#0b2545] border border-[#1a3a5f] space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  {p.rank && <span className="text-[10px] font-mono text-slate-500">#{p.rank}</span>}
                  <span className="text-sm font-semibold text-white">{p.name}</span>
                  {p.inferred && <Badge variant="neutral">company-level (no product page)</Badge>}
                  {p.category && <span className="text-[11px] text-slate-400">{p.category}</span>}
                  {p.fit && <Badge variant={FIT_TONE[p.fit.classification] as Tone}>{p.fit.label}</Badge>}
                </div>
                <SourceLink url={p.url} />
                {p.description && <p className="text-xs text-slate-300 italic">&ldquo;{p.description}&rdquo;</p>}
                {p.features.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {p.features.map((feat) => (
                      <span key={feat} className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px] border border-slate-700">
                        {feat}
                      </span>
                    ))}
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <Field label="API & integration details">
                    {[...(p.api_details || []), ...(p.integration_details || [])].slice(0, 3).map((d, i) => (
                      <div key={i} className="italic text-slate-400">&ldquo;{d}&rdquo;</div>
                    ))}
                    {!(p.api_details?.length || p.integration_details?.length) && "Not documented."}
                  </Field>
                  <Field label="AI functionality">
                    {(p.ai_details || []).slice(0, 3).map((d, i) => (
                      <div key={i} className="italic text-slate-400">&ldquo;{d}&rdquo;</div>
                    ))}
                    {!p.ai_details?.length && "No public evidence of AI functionality."}
                  </Field>
                  <Field label="Relevance score">
                    {p.score ? `${p.score.total.toFixed(1)} / 100` : "—"}
                  </Field>
                </div>
              </div>
            ))}
          </Section>

          {/* D. Architecture */}
          <Section
            letter="D"
            title="Product Architecture and Data Flows"
            description="Solid boxes are documented in public sources; dashed boxes are inferred and must be validated"
            icon={<Network className="w-4 h-4 text-sky-400" />}
          >
            {company.products.map((p) => (
              <ArchitectureView key={p.product_id} product={p} />
            ))}
          </Section>

          {/* E. Security gap analysis */}
          <Section
            letter="E"
            title="Security Gap Analysis"
            description="Potential risks inferred from documented context. None of these is a verified vulnerability; missing documentation is not proof a control is absent."
            icon={<ShieldAlert className="w-4 h-4 text-amber-400" />}
          >
            {company.gaps.length === 0 && <Empty>No potential gaps could be derived from the available evidence.</Empty>}
            {company.gaps.map((g) => (
              <div key={g.gap_id} className="p-4 rounded-xl bg-[#0b2545] border border-[#1a3a5f] space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-white">{g.title}</span>
                  <Badge variant="warning">Potential risk — not a verified vulnerability</Badge>
                  <span className="text-[10px] font-mono text-slate-400">confidence {pct(g.confidence)}</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label="Product & feature">{g.product_name} · {g.feature}</Field>
                  <Field label="Documented context">{g.technical_context}</Field>
                  <Field label="Potential exposure scenario">{g.exposure_scenario}</Field>
                  <Field label="Possible consequence">{g.possible_consequence}</Field>
                  <Field label="Existing documented controls">
                    {g.existing_controls.length ? g.existing_controls.map((c) => c.control).join(", ") : "None found in public sources"}
                  </Field>
                  <Field label="Controls that could not be verified">{g.unverified_controls.join("; ")}</Field>
                  <Field label="Information needed to validate">{g.information_needed.join("; ")}</Field>
                  <Field label="Validation question">{g.discovery_question}</Field>
                </div>
                <Field label="Supporting evidence">
                  <div className="flex flex-col gap-1">
                    {g.evidence_ids.map((id) => findingsById[id]).filter(Boolean).slice(0, 4).map((f) => (
                      <SourceLink key={f.finding_id} url={f.source_url} label={`${f.label}: ${f.source_url}`} />
                    ))}
                  </div>
                </Field>
              </div>
            ))}
          </Section>

          {/* F. Where BAVRIX adds value */}
          <Section
            letter="F"
            title="Where BAVRIX Adds Value"
            description="Mapped only to SealAPI capabilities verified as implemented in the SealAPI codebase"
            icon={<Target className="w-4 h-4 text-purple-400" />}
          >
            {company.opportunities.length === 0 && <Empty>No product-specific opportunities identified.</Empty>}
            {company.opportunities.map((o) => {
              const compat = COMPAT_META[o.compatibility.status];
              const unsupported = o.compatibility.status === "not_supported";
              return (
                <div
                  key={o.opportunity_id}
                  className={`p-4 rounded-xl border space-y-3 ${unsupported ? "border-[#1a3a5f] bg-[#061a33] opacity-80" : "border-purple-500/30 bg-purple-500/5"}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-white">{o.product_name} · {o.feature}</span>
                    <Badge variant={compat.tone}>{compat.label}</Badge>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <Field label="Security requirement">{o.security_requirement}</Field>
                    <Field label="Potential problem">{o.problem_hypothesis}</Field>
                    <Field label="Proposed SealAPI contribution">{o.proposed_contribution}</Field>
                    <Field label="Integration point">{o.integration_point}</Field>
                    {!unsupported && (
                      <>
                        <Field label="Expected security benefit">{o.expected_benefit}</Field>
                        <Field label="Dependencies">{o.dependencies.join("; ")}</Field>
                        <Field label="Implementation complexity">
                          {o.complexity.estimate} — {o.complexity.assumptions}
                        </Field>
                        <Field label="Operational trade-offs">{o.operational_tradeoffs}</Field>
                      </>
                    )}
                    <Field label="Compatibility">{o.compatibility.detail}</Field>
                    <Field label="Evidence confidence">{pct(o.confidence)}</Field>
                  </div>
                </div>
              );
            })}
          </Section>

          {/* G. Necessity and product fit */}
          <Section letter="G" title="Necessity and Product Fit" icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />}>
            {company.products.map((p) =>
              p.fit ? (
                <div key={p.product_id} className="p-4 rounded-xl bg-[#0b2545] border border-[#1a3a5f] space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-white">{p.name}</span>
                    <Badge variant={FIT_TONE[p.fit.classification] as Tone}>{p.fit.label}</Badge>
                  </div>
                  <Field label="Reasoning">{p.fit.reasoning}</Field>
                  <Field label="Role of SealAPI">{p.fit.role}</Field>
                  <Field label="Existing controls compared">
                    {p.fit.existing_controls_compared.join(", ") || "None documented"}
                  </Field>
                  {p.fit.compatibility_concerns.length > 0 && (
                    <Field label="Unresolved compatibility concerns">
                      <ul className="list-disc list-inside text-slate-400">
                        {p.fit.compatibility_concerns.map((c) => (
                          <li key={c}>{c}</li>
                        ))}
                      </ul>
                    </Field>
                  )}
                  <p className="text-[11px] text-slate-500">{p.fit.scope_note}</p>
                  {p.score && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs text-left">
                        <thead className="text-slate-400 uppercase font-mono border-b border-[#1a3a5f]">
                          <tr>
                            <th className="py-1.5 pr-3">Factor</th>
                            <th className="py-1.5 pr-3">Value</th>
                            <th className="py-1.5 pr-3">Weight</th>
                            <th className="py-1.5 pr-3">Points</th>
                            <th className="py-1.5">Explanation</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#1a3a5f]">
                          {p.score.factors.map((f) => (
                            <tr key={f.factor}>
                              <td className="py-1.5 pr-3 font-mono text-slate-300">{f.factor}</td>
                              <td className="py-1.5 pr-3 font-mono">{f.value}</td>
                              <td className="py-1.5 pr-3 font-mono">{f.weight}</td>
                              <td className="py-1.5 pr-3 font-mono text-blue-400">{f.points}</td>
                              <td className="py-1.5 text-slate-400">{f.explanation}</td>
                            </tr>
                          ))}
                          <tr>
                            <td className="py-1.5 pr-3 font-mono text-slate-300">uncertainty penalty</td>
                            <td colSpan={2} />
                            <td className="py-1.5 pr-3 font-mono text-rose-400">-{p.score.uncertainty_penalty}</td>
                            <td className="py-1.5 text-slate-400">architecture documentation level</td>
                          </tr>
                        </tbody>
                      </table>
                      <p className="text-[11px] text-slate-500 mt-2">
                        Total {p.score.total.toFixed(1)} / 100. {p.score.note}
                      </p>
                    </div>
                  )}
                </div>
              ) : null
            )}
          </Section>

          {/* H. Discovery questions */}
          <Section
            letter="H"
            title="Discovery Questions"
            description="Generated from this company's research; the first group is ordered for this prospect's role"
            icon={<HelpCircle className="w-4 h-4 text-sky-400" />}
          >
            {view.role_questions.length > 0 && (
              <Field label={`For this prospect${jobTitle ? ` (${jobTitle})` : ""}`}>
                <ol className="list-decimal list-inside space-y-1">
                  {view.role_questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ol>
              </Field>
            )}
            {company.discovery_questions.length === 0 ? (
              <Empty>No research-based questions yet.</Empty>
            ) : (
              <Field label="All research-based questions">
                <ul className="list-disc list-inside space-y-1 text-slate-300">
                  {company.discovery_questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              </Field>
            )}
          </Section>

          {/* I. Evidence and research limitations */}
          <Section
            letter="I"
            title="Evidence and Research Limitations"
            description="Mark findings verified, rejected or needing review. Rejected findings are excluded from analysis and outreach; refreshes keep your decisions."
            icon={<FileSearch className="w-4 h-4 text-blue-400" />}
          >
            {company.findings.length === 0 ? (
              <Empty>No findings were extracted.</Empty>
            ) : (
              <ul className="space-y-3">
                {company.findings.map((f) => {
                  const page = company.pages.find((p) => p.source_id === f.source_id);
                  return (
                    <li key={f.finding_id} className="p-3 rounded-lg bg-[#0b2545] border border-[#1a3a5f] space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-white">{f.label}</span>
                        <span className="text-[10px] font-mono text-slate-500">{f.category}</span>
                        <ReviewBadge status={f.verification_status} />
                        <span className="text-[10px] font-mono text-slate-400">confidence {pct(f.confidence)}</span>
                        {f.stale && <Badge variant="warning">not found in latest refresh</Badge>}
                      </div>
                      <p className="text-xs text-slate-300 italic">&ldquo;{f.evidence}&rdquo;</p>
                      <div className="text-[11px] text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
                        <span>Source: {page?.title || f.source_domain}</span>
                        <span>Domain: {f.source_domain}</span>
                        <span>Published: {f.publication_date ? formatDateTime(f.publication_date) : "not stated"}</span>
                        <span>Researched: {formatDateTime(f.accessed_at)}</span>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <SourceLink url={f.source_url} />
                        <ReviewButtons finding={f} disabled={acting || meta.busy} onReview={review} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            <Field label="Pages consulted">
              <ul className="space-y-1">
                {company.pages.map((p) => (
                  <li key={p.url} className="flex flex-wrap items-center gap-2">
                    {p.success ? <Check className="w-3 h-3 text-emerald-400" /> : <XCircle className="w-3 h-3 text-rose-400" />}
                    <SourceLink url={p.url} label={p.title || p.url} />
                    {!p.success && <span className="text-[11px] text-slate-500">{p.error || `HTTP ${p.status_code}`}</span>}
                  </li>
                ))}
              </ul>
            </Field>
            <Field label="Missing information & unverified assumptions">
              <ul className="list-disc list-inside space-y-0.5 text-slate-400">
                {company.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
                {Array.from(new Set(company.products.flatMap((p) => p.architecture?.unknowns || []))).map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            </Field>
          </Section>
        </>
      )}
    </div>
  );
}

export function CompanyOutreachCard({ leadId, batchId }: { leadId: string; batchId?: string }) {
  const [data, setData] = useState<CompanyOutreach | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getLeadCompanyOutreach(leadId, batchId);
      setData(res);
      setDrafts(Object.fromEntries(res.variants.map((v) => [v.variant_id, `Subject: ${v.subject}\n\n${v.body}`])));
    } catch (err: any) {
      setError(err?.message || "Failed to generate company-informed drafts.");
    } finally {
      setLoading(false);
    }
  }, [leadId, batchId]);

  useEffect(() => {
    load();
  }, [load]);

  const copy = (id: string) => {
    navigator.clipboard.writeText(drafts[id] || "");
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <Card>
      <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <CardTitle className="text-white flex items-center gap-2">
            <Target className="w-4 h-4 text-purple-400" />
            <span>Company-Informed Outreach (BAVRIX / SealAPI)</span>
          </CardTitle>
          <CardDescription>
            Built from Company Details research. Drafts are editable and are never sent automatically.
          </CardDescription>
        </div>
        <Button size="sm" variant="outline" onClick={load} disabled={loading} className="gap-1.5 text-xs">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          <span>Regenerate</span>
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && !data && <p className="text-xs text-slate-400">Generating drafts...</p>}
        {error && <div className="p-3 rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-300 text-xs">{error}</div>}
        {data?.note && (
          <div className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/5 text-amber-300 text-xs">{data.note}</div>
        )}
        {data?.variants.map((v) => (
          <div key={v.variant_id} className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-white">Variant {v.variant_id} — {v.label}</span>
                <span className="text-[10px] font-mono text-slate-400">{v.word_count} words</span>
                {v.requires_review && <Badge variant="warning">observation not yet verified — review source</Badge>}
                {v.guardrail_violations.length > 0 && (
                  <Badge variant="danger">check claims: {v.guardrail_violations.join(", ")}</Badge>
                )}
              </div>
              <Button size="sm" variant="secondary" onClick={() => copy(v.variant_id)} className="gap-1.5 text-xs">
                {copied === v.variant_id ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copied === v.variant_id ? "Copied" : "Copy"}</span>
              </Button>
            </div>
            <label className="sr-only" htmlFor={`draft-${v.variant_id}`}>Variant {v.variant_id} draft</label>
            <textarea
              id={`draft-${v.variant_id}`}
              value={drafts[v.variant_id] || ""}
              onChange={(e) => setDrafts((d) => ({ ...d, [v.variant_id]: e.target.value }))}
              rows={14}
              className="w-full p-3 rounded-xl bg-[#061a33] border border-[#1a3a5f] text-slate-200 text-xs font-mono leading-relaxed focus:outline-none focus:border-blue-500"
            />
            {v.observation_source_url && (
              <div className="text-[11px] text-slate-400 flex items-center gap-2">
                <span>Observation source:</span>
                <SourceLink url={v.observation_source_url} />
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
