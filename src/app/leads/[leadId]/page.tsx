"use client";

import React, { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Copy,
  Check,
  Download,
  Building,
  Briefcase,
  Mail,
  Globe,
  Linkedin,
  ShieldCheck,
  FileText,
  AlertTriangle,
  ExternalLink,
  Code,
  Sparkles,
  Info,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/lib/api";
import { LeadProfile } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { PriorityBadge, StatusBadge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";

function LeadProfileContent() {
  const params = useParams();
  const searchParams = useSearchParams();

  const leadId = (params.leadId as string) || "";
  const batchId = searchParams.get("batch_id") || undefined;

  const [profileData, setProfileData] = useState<{
    batch_id: string;
    lead_id: string;
    filename: string;
    profile: LeadProfile;
  } | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "evidence" | "email" | "json">("overview");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!leadId) return;
    const fetchProfile = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.getLeadProfile(leadId, batchId);
        setProfileData(res);
      } catch (err: any) {
        setError(err?.message || `Failed to fetch profile for lead '${leadId}'`);
      } finally {
        setLoading(false);
      }
    };
    fetchProfile();
  }, [leadId, batchId]);

  const handleCopyJson = () => {
    if (!profileData?.profile) return;
    navigator.clipboard.writeText(JSON.stringify(profileData.profile, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadJson = () => {
    if (!profileData?.profile) return;
    const jsonStr = JSON.stringify(profileData.profile, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${profileData.filename || `${leadId}.json`}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="p-12 text-center text-slate-400 space-y-3 max-w-4xl mx-auto">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-sm">Loading verified lead research profile...</p>
      </div>
    );
  }

  if (error || !profileData) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-4">
        <div className="p-5 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 space-y-2">
          <div className="font-semibold text-base flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-rose-400" />
            <span>Profile Not Found</span>
          </div>
          <p className="text-sm">{error || "The requested profile JSON could not be loaded."}</p>
        </div>
        <Link href="/leads">
          <Button variant="outline" size="sm" className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Leads Registry</span>
          </Button>
        </Link>
      </div>
    );
  }

  const { profile } = profileData;
  const identity = profile.identity || {};
  const prio = profile.priority || { numeric_priority: 2, score: 0, reason: "", confidence: 0 };
  const context = profile.professional_context || {
    responsibilities: [],
    technical_interests: [],
    public_projects: [],
    recent_developments: [],
    sealapi_relevance: { summary: "", relevant_use_cases: [], evidence_points: [] },
  };
  const emailContext = profile.cold_email_context || {
    verified_personalization_points: [],
    suggested_value_propositions: [],
    suggested_call_to_action: "",
    claims_to_avoid: [],
    missing_verification_points: [],
  };
  const sources = profile.sources || [];
  const meta = profile.research_metadata || { research_status: "unknown", sources_examined: 0, errors_and_limitations: [] };

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Back button and quick actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#1c2438] pb-4">
        <div className="flex items-center gap-3">
          <Link href={`/leads${batchId ? `?batch_id=${batchId}` : ""}`}>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs">
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Leads</span>
            </Button>
          </Link>
          <span className="text-xs text-slate-500 font-mono">ID: {profile.lead_id}</span>
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={handleCopyJson} className="gap-1.5 text-xs">
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? "Copied JSON" : "Copy JSON"}</span>
          </Button>

          <Button size="sm" variant="outline" onClick={handleDownloadJson} className="gap-1.5 text-xs">
            <Download className="w-3.5 h-3.5" />
            <span>Download JSON</span>
          </Button>
        </div>
      </div>

      {/* Hero Header Card */}
      <Card>
        <CardContent className="p-6">
          <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-white tracking-tight">{identity.name}</h1>
                <PriorityBadge priority={prio.numeric_priority} />
                <StatusBadge status={meta.research_status} />
              </div>

              <div className="flex flex-wrap items-center gap-y-2 gap-x-5 text-sm text-slate-300">
                <div className="flex items-center gap-1.5">
                  <Briefcase className="w-4 h-4 text-slate-400" />
                  <span className="font-medium text-white">{identity.job_title || "Unknown Title"}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Building className="w-4 h-4 text-slate-400" />
                  <span>{identity.company || "Unknown Company"}</span>
                  {identity.industry && <span className="text-xs text-slate-500">({identity.industry})</span>}
                </div>
                {identity.professional_email && (
                  <div className="flex items-center gap-1.5 font-mono text-xs text-blue-400">
                    <Mail className="w-3.5 h-3.5 text-slate-400" />
                    <span>{identity.professional_email}</span>
                  </div>
                )}
              </div>

              {/* External Profile Links */}
              <div className="flex items-center gap-3 pt-1">
                {identity.company_website && (
                  <a
                    href={identity.company_website.startsWith("http") ? identity.company_website : `https://${identity.company_website}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-slate-400 hover:text-blue-400 flex items-center gap-1 transition"
                  >
                    <Globe className="w-3.5 h-3.5" />
                    <span>Company Web</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
                {identity.linkedin_url && (
                  <a
                    href={identity.linkedin_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-slate-400 hover:text-blue-400 flex items-center gap-1 transition"
                  >
                    <Linkedin className="w-3.5 h-3.5 text-sky-400" />
                    <span>LinkedIn</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </div>

            {/* Score & Confidence Widget */}
            <div className="p-4 rounded-xl bg-[#0e1320] border border-[#1c2438] min-w-[200px] text-right space-y-2">
              <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                SealAPI Score
              </div>
              <div className="text-3xl font-extrabold text-blue-400 font-mono">
                {prio.score.toFixed(1)} <span className="text-xs text-slate-500">/ 100</span>
              </div>
              <div className="text-xs text-slate-400">
                Confidence: <span className="font-semibold text-white">{(prio.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabs Navigation */}
      <div className="flex border-b border-[#1c2438] gap-6 text-sm font-medium">
        <button
          onClick={() => setActiveTab("overview")}
          className={`pb-3 transition-colors relative ${
            activeTab === "overview"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Overview & Relevance
        </button>
        <button
          onClick={() => setActiveTab("evidence")}
          className={`pb-3 transition-colors relative ${
            activeTab === "evidence"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Source Evidence ({sources.length})
        </button>
        <button
          onClick={() => setActiveTab("email")}
          className={`pb-3 transition-colors relative ${
            activeTab === "email"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Cold Outreach Context
        </button>
        <button
          onClick={() => setActiveTab("json")}
          className={`pb-3 transition-colors relative ${
            activeTab === "json"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Raw JSON Profile
        </button>
      </div>

      {/* Tab 1: Overview & SealAPI Relevance */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Priority Rationale Banner */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-blue-400" />
                <span>Deterministic Priority Rationale</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-slate-200 leading-relaxed font-medium">
                {prio.reason || "No priority explanation recorded."}
              </p>
              {prio.supporting_evidence && prio.supporting_evidence.length > 0 && (
                <ul className="space-y-1.5 pt-2 border-t border-[#1c2438]">
                  {prio.supporting_evidence.map((ev, i) => (
                    <li key={i} className="text-xs text-slate-400 flex items-start gap-2">
                      <span className="text-blue-400 font-bold">&bull;</span>
                      <span>{ev}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {/* SealAPI Strategic Relevance */}
          {context.sealapi_relevance && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <Sparkles className="w-4 h-4 text-purple-400" />
                  <span>SealAPI Value Alignment</span>
                </CardTitle>
                <CardDescription>
                  Tailored value proposition mapping based on public signals
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-slate-300 leading-relaxed">
                  {context.sealapi_relevance.summary || "No specific relevance summary available."}
                </p>

                {context.sealapi_relevance.relevant_use_cases?.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      Targeted SealAPI Use Cases
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {context.sealapi_relevance.relevant_use_cases.map((uc, i) => (
                        <span
                          key={i}
                          className="px-2.5 py-1 rounded-md bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-medium"
                        >
                          {uc}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Professional Context Details */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-white">
                  Professional Responsibilities
                </CardTitle>
              </CardHeader>
              <CardContent>
                {context.responsibilities?.length > 0 ? (
                  <ul className="space-y-2">
                    {context.responsibilities.map((r, i) => (
                      <li key={i} className="text-xs text-slate-300 flex items-start gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
                        <span>{r}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-slate-500">Not specifically identified from verified web signals.</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-white">
                  Technical Interests & Focus
                </CardTitle>
              </CardHeader>
              <CardContent>
                {context.technical_interests?.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {context.technical_interests.map((t, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-xs border border-slate-700"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">No public technical interest tags detected.</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Research Limitations Audit */}
          {meta.errors_and_limitations?.length > 0 && (
            <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/5 text-amber-300 text-xs space-y-1.5">
              <div className="font-semibold flex items-center gap-1.5 text-amber-400">
                <AlertTriangle className="w-4 h-4" />
                <span>Research Notes & Limitations</span>
              </div>
              <ul className="list-disc list-inside space-y-1 text-slate-400 pl-1">
                {meta.errors_and_limitations.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Source Evidence */}
      {activeTab === "evidence" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div>
                <CardTitle className="text-white">Consulted Research Sources</CardTitle>
                <CardDescription>
                  Provenance evidence retrieved by Scrapling fetcher with timestamps and verified facts
                </CardDescription>
              </div>
            </CardHeader>

            <CardContent className="space-y-4">
              {sources.length === 0 ? (
                <div className="p-8 text-center text-slate-500 text-xs">
                  No public web sources were successfully retrieved for this lead.
                </div>
              ) : (
                sources.map((src, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-lg bg-[#0e1320] border border-[#1c2438] space-y-3"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10px] font-mono uppercase">
                          {src.source_type}
                        </span>
                        <a
                          href={src.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs font-mono text-slate-200 hover:text-blue-400 flex items-center gap-1 truncate max-w-md transition"
                        >
                          <span className="truncate">{src.source_url}</span>
                          <ExternalLink className="w-3 h-3 shrink-0" />
                        </a>
                      </div>

                      <div className="text-[11px] text-slate-500 font-mono">
                        {formatDateTime(src.retrieval_timestamp)}
                      </div>
                    </div>

                    {src.facts_supported && src.facts_supported.length > 0 && (
                      <div className="pt-2 border-t border-[#1c2438]/60 space-y-1">
                        <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Verified Signals Supported:
                        </span>
                        <ul className="space-y-1">
                          {src.facts_supported.map((fact, fi) => (
                            <li key={fi} className="text-xs text-slate-300 flex items-start gap-2">
                              <span className="text-emerald-400">&bull;</span>
                              <span>{fact}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab 3: Cold-Email Context */}
      {activeTab === "email" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Personalization Points */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-emerald-400 flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Verified Personalization Hooks</span>
                </CardTitle>
                <CardDescription>Only verified from public sources; no hallucinated claims</CardDescription>
              </CardHeader>
              <CardContent>
                {emailContext.verified_personalization_points?.length > 0 ? (
                  <ul className="space-y-2">
                    {emailContext.verified_personalization_points.map((pt, i) => (
                      <li key={i} className="text-xs text-slate-200 p-2 rounded bg-[#0e1320] border border-[#1c2438]">
                        {pt}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-slate-500">No specific personalization points generated.</p>
                )}
              </CardContent>
            </Card>

            {/* Suggested Value Propositions */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-blue-400 flex items-center gap-2">
                  <Sparkles className="w-4 h-4" />
                  <span>Suggested Value Propositions</span>
                </CardTitle>
                <CardDescription>Directly mapped to SealAPI security & AI guardrails</CardDescription>
              </CardHeader>
              <CardContent>
                {emailContext.suggested_value_propositions?.length > 0 ? (
                  <ul className="space-y-2">
                    {emailContext.suggested_value_propositions.map((vp, i) => (
                      <li key={i} className="text-xs text-slate-200 p-2 rounded bg-[#0e1320] border border-[#1c2438]">
                        {vp}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-slate-500">No value propositions available.</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Suggested CTA & Claims to Avoid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-white">Suggested Call to Action</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-slate-300 italic p-3 rounded bg-[#0e1320] border border-[#1c2438]">
                  "{emailContext.suggested_call_to_action || "Brief 15-minute briefing on securing AI endpoints."}"
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-rose-400 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4" />
                  <span>Claims to Avoid</span>
                </CardTitle>
                <CardDescription>Guardrails against unverified outreach claims</CardDescription>
              </CardHeader>
              <CardContent>
                {emailContext.claims_to_avoid?.length > 0 ? (
                  <ul className="space-y-1.5">
                    {emailContext.claims_to_avoid.map((c, i) => (
                      <li key={i} className="text-xs text-rose-300 flex items-start gap-2">
                        <span className="text-rose-400 font-bold">&times;</span>
                        <span>{c}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-slate-500">No negative claims flagged.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Tab 4: Formatted Raw JSON */}
      {activeTab === "json" && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-white">
                <Code className="w-4 h-4 text-blue-400" />
                <span>Profile JSON Representation</span>
              </CardTitle>
              <CardDescription>Exact stored profile document ({profileData.filename})</CardDescription>
            </div>

            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={handleCopyJson} className="gap-1.5 text-xs">
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copied ? "Copied" : "Copy"}</span>
              </Button>
              <Button size="sm" variant="outline" onClick={handleDownloadJson} className="gap-1.5 text-xs">
                <Download className="w-3.5 h-3.5" />
                <span>Download</span>
              </Button>
            </div>
          </CardHeader>

          <CardContent className="p-0">
            <pre className="p-5 bg-[#0a0d14] text-slate-300 font-mono text-xs overflow-x-auto max-h-[600px] border-t border-[#1c2438] rounded-b-xl leading-relaxed">
              {JSON.stringify(profile, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function LeadProfilePage() {
  return (
    <Suspense
      fallback={
        <div className="p-12 text-center text-slate-400 space-y-3 max-w-4xl mx-auto">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm">Loading lead profile...</p>
        </div>
      }
    >
      <LeadProfileContent />
    </Suspense>
  );
}
