"use client";

import React from "react";
import { Building, ExternalLink } from "lucide-react";
import { IndividualJob, IndividualLiveProduct, IndividualRepoProject } from "@/types";
import {
  aiContextLabel,
  aiPurposeLabel,
  aiStageLabel,
  aiTypeChips,
  aiTypeLabel,
  confidenceLabel,
  liveStatusMeta,
  relevanceMeta,
  safeHttpUrl,
} from "@/lib/individual.mjs";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Badge, PriorityBadge } from "@/components/ui/Badge";

/** External link: http(s) only; anything else renders as plain text. */
function SafeLink({ url, label }: { url: string; label?: string }) {
  const href = safeHttpUrl(url);
  const text = label || url;
  if (!href) return <span className="break-all">{text}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 break-all"
    >
      {text}
      <ExternalLink className="w-3 h-3 shrink-0" />
    </a>
  );
}

function Row({ label, value }: { label: string; value?: React.ReactNode }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex gap-3 text-sm">
      <span className="w-36 shrink-0 text-slate-500">{label}</span>
      <span className="text-slate-200 min-w-0 break-words">{value}</span>
    </div>
  );
}

function AiChips({ types, purposes }: { types?: string[]; purposes?: string[] }) {
  if (!types?.length && !purposes?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {(types || []).map((t) => (
        <Badge key={`t-${t}`} variant="info">
          {aiTypeLabel(t)}
        </Badge>
      ))}
      {(purposes || []).map((p) => (
        <Badge key={`p-${p}`} variant="neutral">
          {aiPurposeLabel(p)}
        </Badge>
      ))}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const meta = liveStatusMeta(status);
  return <Badge variant={meta.variant as any}>{meta.label}</Badge>;
}

function LiveProductCard({ p }: { p: IndividualLiveProduct }) {
  return (
    <li className="rounded-lg border border-[#1a3a5f] bg-[#0a2241] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-white break-words">{p.name}</span>
        <div className="flex items-center gap-2 shrink-0">
          {p.source === "company_level" && <Badge variant="neutral">Company-level</Badge>}
          {p.source === "ai_page" && <Badge variant="neutral">From AI page</Badge>}
          <StatusBadge status={p.status} />
        </div>
      </div>
      {p.description && <p className="text-xs text-slate-400 mt-1 break-words">{p.description}</p>}
      {p.features?.length ? (
        <p className="text-xs text-slate-500 mt-1 break-words">{p.features.slice(0, 6).join(" · ")}</p>
      ) : null}
      {p.signal && <p className="text-xs text-emerald-300/80 mt-1 break-words">Live signal: {p.signal}</p>}
      <AiChips types={p.ai_types} purposes={p.ai_purposes} />
      {p.url && (
        <div className="text-xs mt-1">
          <SafeLink url={p.url} />
        </div>
      )}
    </li>
  );
}

function RepoProjectRow({ r }: { r: IndividualRepoProject }) {
  return (
    <li className="rounded-lg border border-[#1a3a5f] bg-[#0a2241] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-white break-words">{r.name}</span>
        <StatusBadge status={r.status} />
      </div>
      {r.description && <p className="text-xs text-slate-400 mt-1 break-words">{r.description}</p>}
      <p className="text-xs text-slate-500 mt-1">
        {[r.language, r.stars ? `★ ${r.stars}` : "", r.pushed_at ? `updated ${r.pushed_at.slice(0, 10)}` : ""]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <AiChips types={r.ai_types} purposes={r.ai_purposes} />
      <div className="text-xs mt-1 flex flex-wrap gap-x-3">
        {r.homepage && <SafeLink url={r.homepage} label="Website" />}
        {r.repo_url && <SafeLink url={r.repo_url} label="Repository" />}
      </div>
    </li>
  );
}

export function IndividualResults({ job }: { job: IndividualJob }) {
  const person = job.person;
  if (!person) return null;
  const cand = person.candidate;
  const company = job.company;
  const intel = company?.intel ?? null;
  const verdict = job.sealapi;
  const rel = verdict ? relevanceMeta(verdict.relevance) : null;
  const liveProducts = job.live_products?.live ?? [];
  const excludedProducts = job.live_products?.excluded ?? [];
  const projects = person.projects;
  const idConfidence = person.identity_confidence ?? 0;
  const ai = job.ai_usage;
  const useCases = ai?.use_cases ?? [];
  const summary = ai?.summary;
  const typeChips = aiTypeChips(summary?.type_counts);
  const hasAi = Boolean(
    ai && (useCases.length || ai.ai_findings?.length || ai.providers?.length || ai.ai_products?.length),
  );

  return (
    <div className="space-y-6">
      {/* Identity & Profile */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Identity & Profile</CardTitle>
            <CardDescription>Who this person most likely is, based on public sources only.</CardDescription>
          </div>
          <Badge variant={idConfidence >= 0.75 ? "success" : idConfidence >= 0.35 ? "warning" : "danger"}>
            Identity confidence: {confidenceLabel(idConfidence)} ({Math.round(idConfidence * 100)}%)
          </Badge>
        </CardHeader>
        <CardContent className="space-y-2">
          <Row label="Name" value={cand?.name} />
          <Row label="Title" value={cand?.title} />
          <Row label="Company" value={cand?.company} />
          <Row label="Location" value={cand?.location} />
          <Row label="Profile" value={cand?.profile_url ? <SafeLink url={cand.profile_url} /> : null} />
          <Row label="Website" value={cand?.website ? <SafeLink url={cand.website} /> : null} />
          <Row label="Summary" value={cand?.description} />
          {job.identity?.message && <Row label="Resolution" value={job.identity.message} />}
          {cand?.confidence_reasons?.length ? (
            <ul className="list-disc pl-5 pt-2 text-xs text-slate-400 space-y-1">
              {cand.confidence_reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      {/* Professional Background */}
      <Card>
        <CardHeader>
          <CardTitle>Professional Background</CardTitle>
          {person.role?.category && <Badge variant="info">{String(person.role.category)}</Badge>}
        </CardHeader>
        <CardContent className="space-y-2">
          <Row label="Current title" value={person.current_title} />
          <Row label="Current company" value={person.current_company} />
          <Row label="Location" value={person.location} />
          <Row label="Authority" value={person.role?.authority ? String(person.role.authority) : ""} />
          {person.github?.login && (
            <Row
              label="GitHub"
              value={`${person.github.login} · ${person.github.public_repos} public repos${
                person.github.languages?.length ? ` · ${person.github.languages.join(", ")}` : ""
              }`}
            />
          )}
          {person.facts?.length ? (
            <ul className="pt-2 space-y-1.5">
              {person.facts.map((f, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                  <Badge variant={f.basis === "verified" ? "success" : "neutral"}>{f.basis}</Badge>
                  <span className="break-words min-w-0">{f.text}</span>
                </li>
              ))}
            </ul>
          ) : (
            !person.current_title && <p className="text-sm text-slate-500">No professional facts were found.</p>
          )}

          <div className="pt-3 border-t border-[#1a3a5f]">
            <h4 className="text-sm font-semibold text-white mb-1">{"Person's projects"}</h4>
            <p className="text-xs text-slate-500 mb-2">
              Their own GitHub repositories and personal-site projects. Live means the project&apos;s website loaded
              when checked.
            </p>
            {!projects || (!projects.live.length && !projects.site.length && !projects.code_only.length) ? (
              <p className="text-sm text-slate-500">No projects were found.</p>
            ) : (
              <div className="space-y-3">
                {projects.live.length || projects.site.length ? (
                  <ul className="space-y-2">
                    {projects.live.map((r) => (
                      <RepoProjectRow key={`live-${r.repo_url || r.name}`} r={r} />
                    ))}
                    {projects.site.map((s) => (
                      <li
                        key={`site-${s.url}`}
                        className="rounded-lg border border-[#1a3a5f] bg-[#0a2241] p-3 flex items-center justify-between gap-2"
                      >
                        <span className="text-sm text-white min-w-0 break-words">
                          {s.name} <span className="text-xs text-slate-500">(personal site)</span>
                        </span>
                        <span className="flex items-center gap-2 shrink-0 text-xs">
                          <SafeLink url={s.url} label="Open" />
                          <StatusBadge status="live" />
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-slate-500">No live project websites were found.</p>
                )}
                {projects.code_only.length ? (
                  <details className="text-sm">
                    <summary className="cursor-pointer text-slate-400">
                      Code-only or unconfirmed repositories ({projects.code_only.length})
                    </summary>
                    <ul className="space-y-2 mt-2">
                      {projects.code_only.map((r) => (
                        <RepoProjectRow key={`code-${r.repo_url || r.name}`} r={r} />
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Company Intelligence */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Company Intelligence</CardTitle>
            <CardDescription>Current company and what it builds.</CardDescription>
          </div>
          {company && (
            <Badge variant={company.status === "verified" ? "success" : "warning"}>
              {company.status === "verified" ? "Website verified" : "Not verified"}
            </Badge>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {!company && <p className="text-sm text-slate-500">No current company was identified.</p>}
          {company && (
            <div className="space-y-2">
              <Row label="Company" value={company.name} />
              <Row
                label="Domain"
                value={company.domain ? <SafeLink url={`https://${company.domain}`} label={company.domain} /> : ""}
              />
              <Row label="Domain source" value={company.domain_source} />
              <Row
                label="Corroborated"
                value={company.corroborated === null || company.corroborated === undefined ? "" : company.corroborated ? "Yes" : "No"}
              />
              <Row label="Note" value={company.note} />
            </div>
          )}
          {intel?.overview?.description && (
            <p className="text-sm text-slate-300 leading-relaxed">{intel.overview.description}</p>
          )}
          {intel?.overview?.business_model?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {intel.overview.business_model.map((b, i) => (
                <Badge key={i} variant="neutral">
                  {b}
                </Badge>
              ))}
            </div>
          ) : null}
          {intel?.errors?.length ? <p className="text-xs text-amber-400">{intel.errors.join(" · ")}</p> : null}

          <div className="pt-3 border-t border-[#1a3a5f]">
            <h4 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
              <Building className="w-4 h-4 text-slate-400" />
              Live Products
            </h4>
            <p className="text-xs text-slate-500 mb-2">
              Shown only when the product page loads and offers a way to use or buy it now.
            </p>
            {liveProducts.length === 0 ? (
              <p className="text-sm text-slate-500">No live products were confirmed.</p>
            ) : (
              <ul className="space-y-3">
                {liveProducts.map((p) => (
                  <LiveProductCard key={p.url || p.name} p={p} />
                ))}
              </ul>
            )}
            {excludedProducts.length ? (
              <details className="text-sm mt-3">
                <summary className="cursor-pointer text-slate-400">
                  Not live or unconfirmed ({excludedProducts.length})
                </summary>
                <ul className="space-y-2 mt-2">
                  {excludedProducts.map((p) => (
                    <li key={p.url || p.name} className="text-xs text-slate-400 break-words">
                      <span className="text-slate-200 font-medium">{p.name}</span> — {p.status_label}
                      {p.reason ? `: ${p.reason}` : ""}
                      {p.signal && p.status !== "unknown" ? <span className="text-slate-500"> (“{p.signal}”)</span> : null}{" "}
                      {p.url && <SafeLink url={p.url} label="page" />}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {/* AI Usage & SealAPI Relevance */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>AI Usage & SealAPI Relevance</CardTitle>
            <CardDescription>Relevance describes company fit and is separate from identity confidence.</CardDescription>
          </div>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            {rel && <Badge variant={rel.variant as any}>Relevance: {rel.label}</Badge>}
            {job.priority && <PriorityBadge priority={job.priority.level} />}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {verdict?.fit_label && <Row label="Fit" value={verdict.fit_label} />}
          {verdict?.reasoning && <p className="text-sm text-slate-300 leading-relaxed">{verdict.reasoning}</p>}
          {job.priority?.reasons?.length ? (
            <ul className="list-disc pl-5 text-xs text-slate-400 space-y-1">
              {job.priority.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : null}

          <div>
            <h4 className="text-sm font-semibold text-white mb-2">AI usage</h4>
            {hasAi ? (
              <div className="space-y-3">
                {summary?.primary_type ? (
                  <Row label="Main AI type" value={aiTypeLabel(summary.primary_type)} />
                ) : null}
                {typeChips.length ? (
                  <Row
                    label="AI types"
                    value={
                      <span className="flex flex-wrap gap-1.5">
                        {typeChips.map((c) => (
                          <Badge key={c.type} variant="info">
                            {c.label} · {c.count}
                          </Badge>
                        ))}
                      </span>
                    }
                  />
                ) : null}
                {summary?.purposes?.length ? (
                  <Row
                    label="Purpose"
                    value={
                      <span className="flex flex-wrap gap-1.5">
                        {summary.purposes.map((p) => (
                          <Badge key={p.purpose} variant="neutral">
                            {p.label} · {p.count}
                          </Badge>
                        ))}
                      </span>
                    }
                  />
                ) : null}
                {summary && aiStageLabel(summary.stage) ? <Row label="Stage" value={aiStageLabel(summary.stage)} /> : null}
                {summary?.contexts ? (
                  <Row
                    label="Where"
                    value={Object.entries(summary.contexts)
                      .filter(([, n]) => n > 0)
                      .map(([c, n]) => `${aiContextLabel(c)} (${n})`)
                      .join(" · ")}
                  />
                ) : null}
                {ai.providers?.length ? (
                  <Row
                    label="Providers"
                    value={
                      <span className="flex flex-wrap gap-1.5">
                        {ai.providers.map((p, i) => (
                          <Badge key={i} variant="info">
                            {p}
                          </Badge>
                        ))}
                      </span>
                    }
                  />
                ) : null}
                {useCases.length ? (
                  <div>
                    <h5 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1.5">
                      AI use cases ({useCases.length})
                    </h5>
                    <ul className="space-y-2">
                      {useCases.map((u, i) => (
                        <li key={i} className="rounded-lg border border-[#1a3a5f] bg-[#0a2241] p-2.5">
                          <p className="text-xs text-slate-300 break-words">“{u.evidence}”</p>
                          <AiChips types={u.types} purposes={u.purposes} />
                          <p className="text-xs text-slate-500 mt-1 flex flex-wrap gap-x-2">
                            <span>{aiContextLabel(u.context)}</span>
                            {aiStageLabel(u.stage) && <span>· {aiStageLabel(u.stage)}</span>}
                            {u.product && <span>· {u.product}</span>}
                            {u.source_url && (
                              <span>
                                · <SafeLink url={u.source_url} label="source" />
                              </span>
                            )}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <ul className="space-y-1.5">
                    {(ai.ai_findings || []).map((f, i) => (
                      <li key={i} className="text-xs text-slate-400 break-words">
                        {f.evidence} {f.source_url && <SafeLink url={f.source_url} label="source" />}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No AI usage evidence was found.</p>
            )}
          </div>

          {verdict?.opportunities?.length ? (
            <div>
              <h4 className="text-sm font-semibold text-white mb-2">Opportunities</h4>
              <ul className="space-y-2">
                {verdict.opportunities.map((o, i) => (
                  <li key={o.opportunity_id || i} className="text-sm text-slate-300 break-words">
                    <span className="font-medium text-white">{o.feature || o.product_name}</span>
                    {o.problem_hypothesis ? `: ${o.problem_hypothesis}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {verdict?.discovery_questions?.length ? (
            <div>
              <h4 className="text-sm font-semibold text-white mb-2">Discovery questions</h4>
              <ul className="list-disc pl-5 text-sm text-slate-300 space-y-1">
                {verdict.discovery_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {verdict?.scope_note && <p className="text-xs text-slate-500 italic">{verdict.scope_note}</p>}
        </CardContent>
      </Card>

      {/* Sources & Evidence */}
      <Card>
        <CardHeader>
          <CardTitle>Sources & Evidence</CardTitle>
          <Badge variant="neutral">{job.sources?.length ?? 0} sources</Badge>
        </CardHeader>
        <CardContent className="space-y-4">
          {job.sources?.length ? (
            <ul className="space-y-1.5">
              {job.sources.map((s, i) => (
                <li key={s.source_id || i} className="text-xs text-slate-400 flex items-start gap-2">
                  <Badge variant="neutral">{s.source_type}</Badge>
                  <span className="min-w-0 break-words">
                    {s.title ? `${s.title} — ` : ""}
                    <SafeLink url={s.url} />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">No sources recorded.</p>
          )}
          {job.limitations?.length ? (
            <div>
              <h4 className="text-sm font-semibold text-white mb-2">Limitations</h4>
              <ul className="list-disc pl-5 text-xs text-slate-400 space-y-1">
                {job.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
