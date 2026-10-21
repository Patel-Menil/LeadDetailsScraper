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
  XCircle,
  MessageSquare,
  Send,
  HelpCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { LeadProfile } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { PriorityBadge, StatusBadge, ReadinessBadge, Badge } from "@/components/ui/Badge";
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
  const [activeTab, setActiveTab] = useState<"overview" | "icebreaker" | "claims" | "evidence" | "json">("overview");
  const [copiedJson, setCopiedJson] = useState(false);
  const [copiedDraft, setCopiedDraft] = useState(false);

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
    setCopiedJson(true);
    setTimeout(() => setCopiedJson(false), 2000);
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

  const handleCopyDraft = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedDraft(true);
    setTimeout(() => setCopiedDraft(false), 2000);
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
  const scoring = profile.scoring;
  const readiness = profile.contact_readiness;
  const icebreaker = profile.icebreaker;
  const claims = profile.claims || [];
  const sources = profile.sources || [];
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
  const meta = profile.research_metadata || {
    research_status: "unknown",
    sources_examined: 0,
    errors_and_limitations: [],
  };

  // Determine scores and confidence
  const leadFitScore = scoring?.lead_fit_score ?? prio.score ?? 0;
  const verificationConfidence = scoring?.verification_confidence ?? prio.confidence ?? 0;
  const draftBody =
    icebreaker?.outreach_draft?.full_body ||
    `Hi ${identity.first_name || identity.name},\n\n${icebreaker?.text || emailContext.suggested_call_to_action}\n\n${icebreaker?.why_it_matters || ""}\n\n${icebreaker?.conversation_question || "Would you be open to exchanging thoughts on this?"}\n\nBest regards,\n[Your Name]`;

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
            {copiedJson ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedJson ? "Copied JSON" : "Copy JSON"}</span>
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
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="text-2xl font-bold text-white tracking-tight">{identity.name}</h1>
                <PriorityBadge priority={prio.numeric_priority} />
                <StatusBadge status={meta.research_status} />
                {readiness && <ReadinessBadge readiness={readiness.status} />}
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

            {/* Decoupled Score, Confidence & Readiness Widget */}
            <div className="p-4 rounded-xl bg-[#0e1320] border border-[#1c2438] min-w-[220px] text-right space-y-2.5">
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                  Lead-Fit Score
                </div>
                <div className="text-2xl font-extrabold text-blue-400 font-mono">
                  {leadFitScore.toFixed(1)} <span className="text-xs text-slate-500">/ 100</span>
                </div>
              </div>
              <div className="pt-2 border-t border-[#1c2438]/80 text-xs text-slate-400 flex justify-between items-center">
                <span>Verification Conf:</span>
                <span className="font-semibold text-emerald-400 font-mono">
                  {(verificationConfidence * 100).toFixed(0)}%
                </span>
              </div>
              {readiness && (
                <div className="text-xs text-slate-400 flex justify-between items-center">
                  <span>Contact Readiness:</span>
                  <span className="font-semibold text-white uppercase text-[10px] tracking-wide font-mono">
                    {readiness.status.replace(/_/g, " ")}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Blockers Alert if any */}
          {readiness && readiness.blockers && readiness.blockers.length > 0 && (
            <div className="mt-4 p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-300 text-xs flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
              <div>
                <span className="font-semibold">Contact Readiness Blockers: </span>
                <span className="text-amber-200">
                  {readiness.blockers.map((b) => b.replace(/_/g, " ")).join(", ")}
                </span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Tabs Navigation */}
      <div className="flex border-b border-[#1c2438] gap-6 text-sm font-medium overflow-x-auto">
        <button
          onClick={() => setActiveTab("overview")}
          className={`pb-3 transition-colors relative whitespace-nowrap ${
            activeTab === "overview"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Overview & Relevance
        </button>
        <button
          onClick={() => setActiveTab("icebreaker")}
          className={`pb-3 transition-colors relative whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === "icebreaker"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Sparkles className="w-3.5 h-3.5 text-purple-400" />
          <span>Icebreaker & Outreach</span>
        </button>
        <button
          onClick={() => setActiveTab("claims")}
          className={`pb-3 transition-colors relative whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === "claims"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>Verified Claims ({claims.length})</span>
        </button>
        <button
          onClick={() => setActiveTab("evidence")}
          className={`pb-3 transition-colors relative whitespace-nowrap ${
            activeTab === "evidence"
              ? "text-blue-400 border-b-2 border-blue-400 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Source Evidence ({sources.length})
        </button>
        <button
          onClick={() => setActiveTab("json")}
          className={`pb-3 transition-colors relative whitespace-nowrap ${
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
          {/* Priority & Fit Rationale */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-blue-400" />
                <span>Deterministic Scoring Breakdown</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-slate-200 leading-relaxed font-medium">
                {scoring?.explanations?.length
                  ? scoring.explanations.join(" ")
                  : prio.reason || "No scoring explanation recorded."}
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

      {/* Tab 2: Icebreaker & Outreach */}
      {activeTab === "icebreaker" && (
        <div className="space-y-6">
          {/* Evidence-Based Icebreaker Card */}
          <Card>
            <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-400" />
                  <span>Evidence-Grounded Icebreaker</span>
                </CardTitle>
                <CardDescription>
                  Grounded in verifiable public signals; no fabricated projects or hardcoded dates
                </CardDescription>
              </div>

              {icebreaker && (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono text-slate-400">
                    Type: <span className="text-white">{icebreaker.icebreaker_type || "general"}</span>
                  </span>
                  <Badge
                    variant={
                      icebreaker.personalization_status === "ready"
                        ? "success"
                        : icebreaker.personalization_status === "needs_review"
                        ? "warning"
                        : "neutral"
                    }
                  >
                    {icebreaker.personalization_status || "needs_review"}
                  </Badge>
                </div>
              )}
            </CardHeader>

            <CardContent className="space-y-4">
              <div className="p-4 rounded-xl bg-[#0e1320] border border-[#1c2438] space-y-3">
                <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Conversation Opener
                </div>
                <p className="text-sm text-slate-200 font-medium leading-relaxed italic">
                  "{icebreaker?.text || "No custom icebreaker generated."}"
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Why It Matters */}
                <div className="p-3.5 rounded-lg bg-[#0e1320] border border-[#1c2438] space-y-1.5">
                  <span className="text-[11px] font-semibold text-blue-400 uppercase tracking-wider block">
                    Strategic Context
                  </span>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {icebreaker?.why_it_matters || "Identified from public company domain context."}
                  </p>
                </div>

                {/* Potential Pain Point Hypothesis */}
                <div className="p-3.5 rounded-lg bg-[#0e1320] border border-[#1c2438] space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-semibold text-amber-400 uppercase tracking-wider">
                      Pain Point Hypothesis
                    </span>
                    <span className="text-[10px] text-slate-500 font-mono">(Hypothesis, Not Fact)</span>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {icebreaker?.potential_pain_point || "Need for enterprise API security and guardrails."}
                  </p>
                </div>
              </div>

              {/* Thoughtful Low-Pressure Question */}
              {icebreaker?.conversation_question && (
                <div className="p-3.5 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-200 space-y-1">
                  <span className="text-[11px] font-semibold text-purple-300 uppercase tracking-wider block">
                    Low-Pressure Conversation Question
                  </span>
                  <p className="text-xs font-medium">{icebreaker.conversation_question}</p>
                </div>
              )}

              {/* Supporting Sources for Icebreaker */}
              {icebreaker?.source_ids && icebreaker.source_ids.length > 0 && (
                <div className="text-xs text-slate-400 flex items-center gap-2 pt-1 font-mono">
                  <span>Supporting Sources:</span>
                  <span className="text-blue-400 font-semibold">{icebreaker.source_ids.join(", ")}</span>
                </div>
              )}
            </CardContent>
          </Card>

          {/* First-Contact Outreach Email Draft */}
          <Card>
            <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white flex items-center gap-2">
                  <Send className="w-4 h-4 text-emerald-400" />
                  <span>Outreach Email Draft</span>
                </CardTitle>
                <CardDescription>
                  Personalized, evidence-backed email draft ready for review and transmission
                </CardDescription>
              </div>

              <Button
                size="sm"
                variant="primary"
                onClick={() => handleCopyDraft(draftBody)}
                className="gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500"
              >
                {copiedDraft ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedDraft ? "Copied Draft!" : "Copy Full Email"}</span>
              </Button>
            </CardHeader>

            <CardContent className="space-y-4">
              {icebreaker?.outreach_draft?.subject && (
                <div className="p-3 rounded-lg bg-[#0e1320] border border-[#1c2438] flex items-center gap-2">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Subject:</span>
                  <span className="text-xs text-white font-medium">{icebreaker.outreach_draft.subject}</span>
                </div>
              )}

              <div className="p-4 rounded-xl bg-[#0a0d14] border border-[#1c2438] text-slate-200 text-xs font-mono leading-relaxed whitespace-pre-line">
                {draftBody}
              </div>
            </CardContent>
          </Card>

          {/* Claims to Avoid Guardrails */}
          {emailContext.claims_to_avoid?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-rose-400 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4" />
                  <span>Outreach Guardrails & Claims to Avoid</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1.5">
                  {emailContext.claims_to_avoid.map((c, i) => (
                    <li key={i} className="text-xs text-rose-300 flex items-start gap-2">
                      <span className="text-rose-400 font-bold">&times;</span>
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Tab 3: Verified Claims */}
      {activeTab === "claims" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-white">Claim-Level Verification Trail</CardTitle>
              <CardDescription>
                Auditable evidence trail linking each profile attribute to supporting public source IDs
              </CardDescription>
            </CardHeader>
            <CardContent>
              {claims.length === 0 ? (
                <div className="p-8 text-center text-slate-500 text-xs">
                  No individual claim records generated for this profile.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-[#0e1320] text-slate-400 uppercase font-mono border-b border-[#1c2438]">
                      <tr>
                        <th className="py-2.5 px-3">Field</th>
                        <th className="py-2.5 px-3">Value</th>
                        <th className="py-2.5 px-3">Status</th>
                        <th className="py-2.5 px-3">Confidence</th>
                        <th className="py-2.5 px-3">Supporting Source IDs</th>
                        <th className="py-2.5 px-3">Review Notes</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#1c2438]">
                      {claims.map((claim, idx) => (
                        <tr key={idx} className="hover:bg-[#0e1320]/50 transition">
                          <td className="py-2.5 px-3 font-semibold text-white font-mono">{claim.field}</td>
                          <td className="py-2.5 px-3 text-slate-300 max-w-xs truncate">{claim.value || "-"}</td>
                          <td className="py-2.5 px-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-semibold ${
                                claim.status === "verified"
                                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                                  : claim.status === "partially_verified"
                                  ? "bg-blue-500/10 text-blue-400 border border-blue-500/30"
                                  : claim.status === "input_provided"
                                  ? "bg-purple-500/10 text-purple-400 border border-purple-500/30"
                                  : claim.status === "conflicting"
                                  ? "bg-rose-500/10 text-rose-400 border border-rose-500/30"
                                  : "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                              }`}
                            >
                              {claim.status}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 font-mono text-slate-300">
                            {(claim.confidence * 100).toFixed(0)}%
                          </td>
                          <td className="py-2.5 px-3 font-mono text-blue-400">
                            {claim.source_ids?.length > 0 ? claim.source_ids.join(", ") : "-"}
                          </td>
                          <td className="py-2.5 px-3 text-slate-400 italic">
                            {claim.review_reason || "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab 4: Source Evidence */}
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
                        {src.source_id && (
                          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px]">
                            {src.source_id}
                          </span>
                        )}
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

                    {src.title && (
                      <div className="text-xs text-white font-medium">{src.title}</div>
                    )}

                    {src.relevant_excerpt && (
                      <div className="p-2.5 rounded bg-[#0a0d14] border border-[#1c2438]/80 text-xs text-slate-300 italic">
                        "{src.relevant_excerpt}"
                      </div>
                    )}

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

      {/* Tab 5: Formatted Raw JSON */}
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
                {copiedJson ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedJson ? "Copied" : "Copy"}</span>
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
