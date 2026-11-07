"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Download,
  Loader2,
  MinusCircle,
  RefreshCw,
  Search,
  UserCheck,
  UserSearch,
  XCircle,
  HelpCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { IndividualJob, IndividualResearchInput, IndividualStage } from "@/types";
import {
  STAGE_LABELS,
  buildStartPayload,
  confidenceLabel,
  downloadFilename,
  safeAvatarUrl,
  safeHttpUrl,
  shouldPollJob,
} from "@/lib/individual.mjs";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { IndividualResults } from "@/components/IndividualResults";

const POLL_MS = 1500;

const EMPTY_FORM: Record<string, string> = {
  name: "",
  company: "",
  linkedin_url: "",
  x_url: "",
  github_url: "",
  website: "",
  location: "",
  context: "",
};

const HINT_FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: "company", label: "Company", placeholder: "Current employer, if known" },
  { key: "linkedin_url", label: "LinkedIn URL", placeholder: "https://linkedin.com/in/..." },
  { key: "x_url", label: "X / Twitter URL", placeholder: "https://x.com/..." },
  { key: "github_url", label: "GitHub URL", placeholder: "https://github.com/..." },
  { key: "website", label: "Website", placeholder: "https://..." },
  { key: "location", label: "Location", placeholder: "City, Country" },
  { key: "context", label: "Context", placeholder: "Anything else that helps identify them" },
];

function StageIcon({ status }: { status: string }) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    case "running":
      return <Loader2 className="w-4 h-4 text-sky-400 animate-spin" />;
    case "failed":
      return <XCircle className="w-4 h-4 text-rose-400" />;
    case "needs_input":
      return <HelpCircle className="w-4 h-4 text-amber-400" />;
    case "skipped":
      return <MinusCircle className="w-4 h-4 text-slate-500" />;
    default:
      return <Circle className="w-4 h-4 text-slate-600" />;
  }
}

function StageList({ stages }: { stages: IndividualStage[] }) {
  return (
    <ul className="space-y-2">
      {stages.map((s) => (
        <li key={s.name} className="flex items-start gap-3">
          <span className="mt-0.5">
            <StageIcon status={s.status} />
          </span>
          <div className="min-w-0">
            <div className="text-sm text-slate-200">{(STAGE_LABELS as Record<string, string>)[s.name] || s.name}</div>
            {s.message && <div className="text-xs text-slate-500 break-words">{s.message}</div>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function IndividualResearchPage() {
  const [form, setForm] = useState<Record<string, string>>({ ...EMPTY_FORM });
  const [showHints, setShowHints] = useState(false);
  const [job, setJob] = useState<IndividualJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Bumped on Clear/unmount so late responses and ticks from an old job are ignored.
  const generation = useRef(0);
  const inFlight = useRef(false);

  const nameOk = form.name.trim().length >= 2;
  const polling = shouldPollJob(job);
  const jobId = job?.job_id ?? null;

  const poll = useCallback(async (id: string, gen: number) => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const next = await api.getIndividualResearch(id);
      if (generation.current === gen) {
        setJob(next);
        setError(null);
      }
    } catch (err: any) {
      if (generation.current === gen) setError(err?.message || "Failed to refresh research status.");
    } finally {
      inFlight.current = false;
    }
  }, []);

  // Poll only while the server reports the job as running.
  useEffect(() => {
    if (!polling || !jobId) return;
    const gen = generation.current;
    const timer = setInterval(() => poll(jobId, gen), POLL_MS);
    return () => clearInterval(timer);
  }, [polling, jobId, poll]);

  // Stop everything on unmount.
  useEffect(() => {
    return () => {
      generation.current += 1;
    };
  }, []);

  const handleStart = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!nameOk || busy || polling) return;
    const gen = ++generation.current;
    inFlight.current = false;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const payload = buildStartPayload(form) as IndividualResearchInput;
      const { job_id } = await api.startIndividualResearch(payload);
      const first = await api.getIndividualResearch(job_id);
      if (generation.current === gen) setJob(first);
    } catch (err: any) {
      if (generation.current === gen) setError(err?.message || "Failed to start research.");
    } finally {
      if (generation.current === gen) setBusy(false);
    }
  };

  const handleSelect = async (candidateId: string) => {
    if (!job || busy) return;
    const gen = generation.current;
    setBusy(true);
    setError(null);
    try {
      const next = await api.selectIndividualCandidate(job.job_id, candidateId);
      if (generation.current === gen) setJob(next);
    } catch (err: any) {
      if (generation.current === gen) setError(err?.message || "Failed to select candidate.");
    } finally {
      if (generation.current === gen) setBusy(false);
    }
  };

  const handleRetry = async () => {
    if (!job || busy) return;
    const gen = generation.current;
    setBusy(true);
    setError(null);
    try {
      const next = await api.retryIndividualResearch(job.job_id);
      if (generation.current === gen) setJob(next);
    } catch (err: any) {
      if (generation.current === gen) setError(err?.message || "Failed to retry research.");
    } finally {
      if (generation.current === gen) setBusy(false);
    }
  };

  const handleClear = () => {
    generation.current += 1;
    inFlight.current = false;
    setForm({ ...EMPTY_FORM });
    setJob(null);
    setError(null);
    setBusy(false);
  };

  const handleDownload = () => {
    if (!job) return;
    const blob = new Blob([JSON.stringify(job, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadFilename(job);
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const identityStage = job?.stages.find((s) => s.name === "identity_resolution");
  const needsSelection = job?.status === "needs_input" && identityStage?.status === "needs_input";
  const hasCandidates = (job?.candidates?.length ?? 0) > 0;
  const canRetry = job?.status === "partial" || job?.status === "failed";

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="border-b border-[#1c2438] pb-4">
        <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
          <UserSearch className="w-6 h-6 text-blue-400" />
          Individual Research
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Research one person by name from public sources, then assess their company&apos;s relevance to SealAPI.
        </p>
      </div>

      {/* Form */}
      <Card>
        <CardContent>
          <form onSubmit={handleStart} className="space-y-4">
            <div>
              <label htmlFor="ind-name" className="block text-xs font-medium text-slate-400 mb-1.5">
                Full name <span className="text-rose-400">*</span>
              </label>
              <input
                id="ind-name"
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Jane Doe"
                maxLength={200}
                className="w-full bg-[#0a0d14] border border-[#232c45] rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              />
            </div>

            <button
              type="button"
              onClick={() => setShowHints((v) => !v)}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-400 hover:text-blue-300"
              aria-expanded={showHints}
            >
              {showHints ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              Add hints
            </button>

            {showHints && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {HINT_FIELDS.map((f) => (
                  <div key={f.key} className={f.key === "context" ? "sm:col-span-2" : ""}>
                    <label htmlFor={`ind-${f.key}`} className="block text-xs font-medium text-slate-400 mb-1.5">
                      {f.label}
                    </label>
                    <input
                      id={`ind-${f.key}`}
                      type="text"
                      value={form[f.key]}
                      onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
                      placeholder={f.placeholder}
                      className="w-full bg-[#0a0d14] border border-[#232c45] rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                    />
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={!nameOk || polling} isLoading={busy && !job}>
                <Search className="w-4 h-4" />
                Start research
              </Button>
              <Button type="button" variant="outline" onClick={handleClear}>
                Clear
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Errors */}
      {error && (
        <div role="alert" className="flex items-start gap-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="break-words min-w-0">{error}</span>
        </div>
      )}
      {job?.errors?.length ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-300">
          <div className="flex items-center gap-2 font-medium mb-1">
            <AlertTriangle className="w-4 h-4" />
            Some steps reported problems
          </div>
          <ul className="list-disc pl-6 space-y-0.5 text-xs">
            {job.errors.map((e, i) => (
              <li key={i} className="break-words">
                {e}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Progress */}
      {job && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Research progress</CardTitle>
              <CardDescription>
                {job.running || job.status === "running"
                  ? "Running..."
                  : job.status === "needs_input"
                  ? "Waiting for your input"
                  : job.status === "completed"
                  ? "Completed"
                  : job.status === "partial"
                  ? "Completed with some steps failed"
                  : "Failed"}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {canRetry && (
                <Button size="sm" variant="secondary" onClick={handleRetry} disabled={busy}>
                  <RefreshCw className="w-3.5 h-3.5" />
                  Retry
                </Button>
              )}
              {job.person && (
                <Button size="sm" variant="outline" onClick={handleDownload}>
                  <Download className="w-3.5 h-3.5" />
                  Download JSON
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <StageList stages={job.stages} />
          </CardContent>
        </Card>
      )}

      {/* Candidate selection */}
      {needsSelection && hasCandidates && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Select the right person</CardTitle>
              <CardDescription>{job?.identity?.message || "Several public profiles match this name."}</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {job!.candidates.map((c) => {
              const avatar = safeAvatarUrl(c.avatar_url);
              const profile = safeHttpUrl(c.profile_url);
              return (
                <div key={c.candidate_id} className="rounded-lg border border-[#232c45] bg-[#0c101b] p-4 space-y-3">
                  <div className="flex items-start gap-3">
                    {avatar ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={avatar}
                        alt=""
                        referrerPolicy="no-referrer"
                        className="w-12 h-12 rounded-full object-cover bg-slate-800 shrink-0"
                      />
                    ) : (
                      <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center shrink-0">
                        <UserCheck className="w-5 h-5 text-slate-500" />
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-white break-words">{c.name}</div>
                      {c.title && <div className="text-xs text-slate-300 break-words">{c.title}</div>}
                      {c.company && <div className="text-xs text-slate-400 break-words">{c.company}</div>}
                      {c.location && <div className="text-xs text-slate-500 break-words">{c.location}</div>}
                    </div>
                  </div>
                  <div>
                    <Badge variant={c.confidence >= 0.75 ? "success" : c.confidence >= 0.35 ? "warning" : "danger"}>
                      Identity confidence: {confidenceLabel(c.confidence)} ({Math.round(c.confidence * 100)}%)
                    </Badge>
                  </div>
                  {c.description && <p className="text-xs text-slate-400 break-words line-clamp-3">{c.description}</p>}
                  {c.confidence_reasons?.length ? (
                    <ul className="list-disc pl-5 text-xs text-slate-500 space-y-0.5">
                      {c.confidence_reasons.slice(0, 4).map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  ) : null}
                  <div className="flex items-center justify-between gap-2">
                    {profile ? (
                      <a
                        href={profile}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-blue-400 hover:text-blue-300"
                      >
                        View profile
                      </a>
                    ) : (
                      <span />
                    )}
                    <Button size="sm" onClick={() => handleSelect(c.candidate_id)} disabled={busy}>
                      Select
                    </Button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {needsSelection && !hasCandidates && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-300 break-words">
          {job?.identity?.message ||
            "No candidate could be identified with enough confidence. Try adding hints such as company, LinkedIn or GitHub URL, then start again."}
        </div>
      )}

      {/* Results */}
      {job?.person && <IndividualResults job={job} />}
    </div>
  );
}
