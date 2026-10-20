"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Download,
  FileSpreadsheet,
  FolderArchive,
  FileText,
  AlertTriangle,
  Layers,
  ExternalLink,
  Users,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/lib/api";
import { BatchSummary, PrioritizedLead } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";

export default function ExportCenterPage() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string>("");
  const [leads, setLeads] = useState<PrioritizedLead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadBatches = async () => {
      setLoading(true);
      try {
        const list = await api.listBatches();
        setBatches(list);
        if (list.length > 0) {
          const firstWithCsv = list.find((b) => b.csv_exists) || list[0];
          setSelectedBatchId(firstWithCsv.batch_id);
        }
      } catch (e) {
        console.error("Failed to load batches:", e);
      } finally {
        setLoading(false);
      }
    };
    loadBatches();
  }, []);

  useEffect(() => {
    if (!selectedBatchId) return;
    const loadLeadsForBatch = async () => {
      try {
        const res = await api.getLeads({ batchId: selectedBatchId, pageSize: 50 });
        setLeads(res.leads || []);
      } catch {
        setLeads([]);
      }
    };
    loadLeadsForBatch();
  }, [selectedBatchId]);

  const selectedBatch = batches.find((b) => b.batch_id === selectedBatchId);

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="border-b border-[#1c2438] pb-4">
        <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
          <Download className="w-5 h-5 text-blue-400" />
          <span>Export Center</span>
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          Download finalized research datasets, verified JSON profile archives, manifests, and error audit logs.
        </p>
      </div>

      {/* Batch Selection Card */}
      <Card>
        <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex-1">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1">
              Select Target Batch
            </label>
            <select
              value={selectedBatchId}
              onChange={(e) => setSelectedBatchId(e.target.value)}
              className="w-full bg-[#0e1320] border border-[#232c45] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500"
            >
              {batches.length === 0 ? (
                <option value="">No batches available</option>
              ) : (
                batches.map((b) => (
                  <option key={b.batch_id} value={b.batch_id}>
                    {b.input_filename || b.batch_id} &bull; {b.total_leads} leads &bull; {formatDateTime(b.created_at)}
                  </option>
                ))
              )}
            </select>
          </div>

          {selectedBatch && (
            <div className="flex items-center gap-3 pt-2 sm:pt-0">
              <StatusBadge status={selectedBatch.status} />
              <span className="text-xs text-slate-400 font-mono">
                {selectedBatch.total_leads} leads processed
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Download Deliverables Cards */}
      {selectedBatchId && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Outreach-Ready CSV */}
          <Card hoverEffect className="border-emerald-500/30">
            <CardContent className="p-5 flex items-start justify-between">
              <div className="space-y-2 pr-4">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  <span className="font-semibold text-white text-sm">Outreach-Ready Lead CSV</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Only leads that pass the strict verification policy: verified identity, verified role, usable contact channel, and evidence-grounded icebreaker.
                </p>
                <div className="text-[11px] font-mono text-emerald-400/80">
                  Filename: outreach_ready.csv
                </div>
              </div>

              <a
                href={api.getOutreachReadyCsvUrl(selectedBatchId)}
                download
                className="shrink-0"
              >
                <Button size="sm" variant="primary" className="gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500">
                  <Download className="w-3.5 h-3.5" />
                  <span>Download</span>
                </Button>
              </a>
            </CardContent>
          </Card>

          {/* Needs-Review CSV */}
          <Card hoverEffect className="border-amber-500/30">
            <CardContent className="p-5 flex items-start justify-between">
              <div className="space-y-2 pr-4">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-amber-400" />
                  <span className="font-semibold text-white text-sm">Needs-Review Lead CSV</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Leads with identity ambiguity, unverified claims, missing professional contact channels, or icebreakers requiring human review.
                </p>
                <div className="text-[11px] font-mono text-amber-400/80">
                  Filename: needs_review.csv
                </div>
              </div>

              <a
                href={api.getNeedsReviewCsvUrl(selectedBatchId)}
                download
                className="shrink-0"
              >
                <Button size="sm" variant="outline" className="gap-1.5 text-xs text-amber-300 border-amber-500/40 hover:bg-amber-500/10">
                  <Download className="w-3.5 h-3.5" />
                  <span>Download</span>
                </Button>
              </a>
            </CardContent>
          </Card>

          {/* Prioritized CSV */}
          <Card hoverEffect>
            <CardContent className="p-5 flex items-start justify-between">
              <div className="space-y-2 pr-4">
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className="w-5 h-5 text-blue-400" />
                  <span className="font-semibold text-white text-sm">Prioritized Lead CSV</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Includes all input fields enriched with numerical priority (0 first, 1, 2), priority rationale, and paths to individual JSON files.
                </p>
                <div className="text-[11px] font-mono text-slate-500">
                  Filename: leads_prioritized.csv
                </div>
              </div>

              <a
                href={api.getPrioritizedCsvUrl(selectedBatchId)}
                download
                className="shrink-0"
              >
                <Button size="sm" variant="secondary" className="gap-1.5 text-xs">
                  <Download className="w-3.5 h-3.5" />
                  <span>Download</span>
                </Button>
              </a>
            </CardContent>
          </Card>

          {/* Full Batch ZIP Archive */}
          <Card hoverEffect>
            <CardContent className="p-5 flex items-start justify-between">
              <div className="space-y-2 pr-4">
                <div className="flex items-center gap-2">
                  <FolderArchive className="w-5 h-5 text-purple-400" />
                  <span className="font-semibold text-white text-sm">Complete Batch ZIP Archive</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Consolidated archive bundling the prioritized CSV, manifest.json, errors.csv, and the full directory of individual person JSON profiles.
                </p>
                <div className="text-[11px] font-mono text-slate-500">
                  Filename: {selectedBatchId}_export.zip
                </div>
              </div>

              <a
                href={api.getBatchZipUrl(selectedBatchId)}
                download
                className="shrink-0"
              >
                <Button size="sm" variant="secondary" className="gap-1.5 text-xs">
                  <Download className="w-3.5 h-3.5 text-purple-400" />
                  <span>Download ZIP</span>
                </Button>
              </a>
            </CardContent>
          </Card>

          {/* Batch Summary JSON */}
          <Card hoverEffect>
            <CardContent className="p-5 flex items-start justify-between">
              <div className="space-y-2 pr-4">
                <div className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-sky-400" />
                  <span className="font-semibold text-white text-sm">Batch Summary Report</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Aggregated statistics, conversion rates, priority breakdowns, execution duration, and audit totals in JSON format.
                </p>
                <div className="text-[11px] font-mono text-slate-500">
                  Filename: summary.json
                </div>
              </div>

              <a
                href={api.getSummaryUrl(selectedBatchId)}
                download
                className="shrink-0"
              >
                <Button size="sm" variant="outline" className="gap-1.5 text-xs text-sky-300 border-sky-500/40 hover:bg-sky-500/10">
                  <Download className="w-3.5 h-3.5" />
                  <span>Summary</span>
                </Button>
              </a>
            </CardContent>
          </Card>

          {/* Manifest JSON */}
          <Card hoverEffect>
            <CardContent className="p-5 flex items-start justify-between">
              <div className="space-y-2 pr-4">
                <div className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-purple-400" />
                  <span className="font-semibold text-white text-sm">Batch Manifest JSON</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Cryptographic run manifest with SHA-256 hashes, priority distributions, Scrapling version metadata, and pipeline execution logs.
                </p>
                <div className="text-[11px] font-mono text-slate-500">
                  Filename: manifest.json
                </div>
              </div>

              <a
                href={api.getManifestUrl(selectedBatchId)}
                download
                className="shrink-0"
              >
                <Button size="sm" variant="outline" className="gap-1.5 text-xs">
                  <Download className="w-3.5 h-3.5" />
                  <span>Manifest</span>
                </Button>
              </a>
            </CardContent>
          </Card>

          {/* Error Audit Report */}
          <Card hoverEffect>
            <CardContent className="p-5 flex items-start justify-between">
              <div className="space-y-2 pr-4">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-rose-400" />
                  <span className="font-semibold text-white text-sm">Error Audit CSV</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Log of unreachable company URLs, HTTP status codes, malformed rows, and partial research gaps for QA compliance.
                </p>
                <div className="text-[11px] font-mono text-slate-500">
                  Filename: errors.csv
                </div>
              </div>

              <a
                href={api.getErrorsCsvUrl(selectedBatchId)}
                download
                className="shrink-0"
              >
                <Button size="sm" variant="outline" className="gap-1.5 text-xs text-rose-300 hover:text-white">
                  <Download className="w-3.5 h-3.5" />
                  <span>Errors CSV</span>
                </Button>
              </a>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Individual JSON Profiles Directory */}
      {leads.length > 0 && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="text-white text-sm">
                Individual Lead JSON Profiles ({leads.length} sampled)
              </CardTitle>
              <CardDescription>
                Direct access to individual person research documents generated by the pipeline
              </CardDescription>
            </div>
            <Link href={`/leads?batch_id=${selectedBatchId}`}>
              <Button size="sm" variant="ghost" className="text-xs text-blue-400 hover:text-blue-300">
                View Full Table
              </Button>
            </Link>
          </CardHeader>

          <CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0e1320] border-b border-[#1c2438] uppercase font-semibold text-slate-400">
                <tr>
                  <th className="py-2.5 px-4">Person Name</th>
                  <th className="py-2.5 px-4">Company</th>
                  <th className="py-2.5 px-4">Priority</th>
                  <th className="py-2.5 px-4">Status</th>
                  <th className="py-2.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1c2438] text-slate-300">
                {leads.slice(0, 15).map((l) => (
                  <tr key={l.lead_id} className="hover:bg-[#131929]">
                    <td className="py-2 px-4 font-medium text-white">{l.name}</td>
                    <td className="py-2 px-4 text-slate-400">{l.company}</td>
                    <td className="py-2 px-4 font-mono">P{l.priority}</td>
                    <td className="py-2 px-4">{l.research_status}</td>
                    <td className="py-2 px-4 text-right space-x-2">
                      <Link href={`/leads/${l.lead_id}?batch_id=${selectedBatchId}`}>
                        <Button size="sm" variant="outline" className="text-[11px] h-6 px-2">
                          View
                        </Button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
