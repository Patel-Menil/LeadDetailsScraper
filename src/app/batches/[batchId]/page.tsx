"use client";

import React, { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Download,
  Users,
  Terminal,
  ArrowLeft,
  RefreshCw,
  FolderArchive,
  FileSpreadsheet,
  FileText,
  Search,
  Maximize2,
  Minimize2,
  Clock,
  Play,
  Globe,
} from "lucide-react";
import { api } from "@/lib/api";
import { BatchProgress } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge, PriorityBadge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";

export default function BatchDetailsPage() {
  const params = useParams();
  const batchId = (params.batchId as string) || "";

  const [batch, setBatch] = useState<BatchProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [logSearch, setLogSearch] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  const fetchStatus = async () => {
    if (!batchId) return;
    try {
      const data = await api.getBatchStatus(batchId);
      setBatch(data);
    } catch (err: any) {
      setError(err?.message || "Failed to retrieve batch status.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();

    // Bounded polling while processing
    const interval = setInterval(() => {
      if (batch?.status === "processing" || batch?.status === "pending") {
        fetchStatus();
      }
    }, 2500);

    return () => clearInterval(interval);
  }, [batchId, batch?.status]);

  if (loading && !batch) {
    return (
      <div className="p-12 text-center text-slate-400 space-y-3 max-w-4xl mx-auto">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-sm">Fetching batch progress & telemetry...</p>
      </div>
    );
  }

  if (error || !batch) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-4">
        <div className="p-5 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300">
          <p className="font-semibold">{error || "Batch not found."}</p>
        </div>
        <Link href="/batches">
          <Button variant="outline" size="sm" className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Batches</span>
          </Button>
        </Link>
      </div>
    );
  }

  const total = batch.total_leads || 0;
  const processed = batch.processed_leads || (batch.status === "completed" ? total : 0);
  const progressPct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : (batch.status === "completed" ? 100 : 0);

  const pCounts = batch.priority_counts || { "0": 0, "1": 0, "2": 0 };

  const filteredLogs = (batch.recent_logs || []).filter((line) =>
    logSearch.trim() ? line.toLowerCase().includes(logSearch.toLowerCase()) : true
  );

  const handleStartScraping = async () => {
    if (!batchId) return;
    setStarting(true);
    try {
      await api.startBatch(batchId, {
        resume: true,
        use_browser: true,
        use_tor: true,
        concurrency: 2,
      });
      fetchStatus();
    } catch (err: any) {
      alert(err?.message || "Failed to initiate scraping.");
    } finally {
      setStarting(false);
    }
  };

  const isProcessing = batch?.status === "processing";

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header and Back Link */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#1c2438] pb-4">
        <div className="flex items-center gap-3">
          <Link href="/batches">
            <Button size="sm" variant="outline" className="gap-1.5 text-xs">
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>All Batches</span>
            </Button>
          </Link>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-blue-400 font-semibold">{batch.batch_id}</span>
            <StatusBadge status={batch.status} />
          </div>
        </div>

        <div className="flex items-center gap-3">
          {!isProcessing && (
            <Button
              size="sm"
              variant="primary"
              onClick={handleStartScraping}
              isLoading={starting}
              className="gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 font-semibold"
            >
              <Play className="w-3.5 h-3.5 fill-white" />
              <span>Start Browser Scraping</span>
            </Button>
          )}

          <Button
            size="sm"
            variant="outline"
            onClick={fetchStatus}
            isLoading={loading}
            className="text-slate-300 text-xs"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </Button>

          <Link href={`/leads?batch_id=${batch.batch_id}`}>
            <Button size="sm" variant="secondary" className="gap-1.5 text-xs">
              <Users className="w-3.5 h-3.5" />
              <span>View Enriched Leads</span>
            </Button>
          </Link>
        </div>
      </div>

      {/* Live Progress Bar Card */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <div className="flex items-center justify-between text-sm">
            <div className="space-y-1">
              <span className="font-semibold text-white">
                {batch.status === "processing"
                  ? "Research Pipeline in Progress..."
                  : batch.status === "completed"
                  ? "Batch Processing Complete"
                  : `Batch Status: ${batch.status}`}
              </span>
              <p className="text-xs text-slate-400">
                Input file: <span className="font-medium text-slate-300">{batch.filename || "Uploaded Spreadsheet"}</span>
              </p>
            </div>

            <div className="text-right">
              <span className="text-2xl font-bold font-mono text-blue-400">{progressPct}%</span>
              <div className="text-xs text-slate-400">
                {processed} of {total} leads processed
              </div>
            </div>
          </div>

          {/* Animated Progress Bar */}
          <div className="h-3 w-full bg-[#1c2438] rounded-full overflow-hidden">
            <div
              style={{ width: `${progressPct}%` }}
              className={`h-full transition-all duration-300 rounded-full ${
                batch.status === "completed"
                  ? "bg-emerald-500"
                  : batch.status === "failed"
                  ? "bg-rose-500"
                  : "bg-blue-500"
              }`}
            />
          </div>

          {batch.current_lead_name && batch.status === "processing" && (
            <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
              <Activity className="w-3.5 h-3.5 text-blue-400 animate-spin" />
              <span>Current target: {batch.current_lead_name}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-[#101522] border border-[#232c45]">
          <div className="text-xs font-semibold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Completed</span>
          </div>
          <div className="text-2xl font-bold text-white mt-2">{batch.completed_count ?? 0}</div>
        </div>

        <div className="p-4 rounded-xl bg-[#101522] border border-[#232c45]">
          <div className="text-xs font-semibold text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Review Required</span>
          </div>
          <div className="text-2xl font-bold text-white mt-2">{batch.partial_count ?? 0}</div>
        </div>

        <div className="p-4 rounded-xl bg-[#101522] border border-[#232c45]">
          <div className="text-xs font-semibold text-rose-400 uppercase tracking-wider flex items-center gap-1.5">
            <XCircle className="w-3.5 h-3.5" />
            <span>Failed</span>
          </div>
          <div className="text-2xl font-bold text-white mt-2">{batch.failed_count ?? 0}</div>
        </div>

        <div className="p-4 rounded-xl bg-[#101522] border border-[#232c45]">
          <div className="text-xs font-semibold text-blue-400 uppercase tracking-wider font-mono">
            Priority Tiers
          </div>
          <div className="text-xs font-mono text-slate-300 mt-2 space-y-1">
            <div>
              P0 High: <span className="font-bold text-red-400">{pCounts["0"] ?? 0}</span>
            </div>
            <div>
              P1 Med: <span className="font-bold text-blue-400">{pCounts["1"] ?? 0}</span>
            </div>
            <div>
              P2 Low: <span className="font-bold text-slate-400">{pCounts["2"] ?? 0}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Live Log Stream Card */}
      <Card>
        <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <CardTitle className="text-white flex items-center gap-2 text-sm">
              <Terminal className="w-4 h-4 text-emerald-400" />
              <span>Scraping & Research Activity Stream</span>
              {batch.recent_logs && (
                <span className="text-[11px] font-normal px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  {batch.recent_logs.length} events
                </span>
              )}
            </CardTitle>
            <CardDescription>
              Granular live logs from Scrapling browser engine, Tor DuckDuckGo queries, and lead evaluation
            </CardDescription>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                placeholder="Filter logs..."
                value={logSearch}
                onChange={(e) => setLogSearch(e.target.value)}
                className="pl-8 pr-2.5 py-1 text-xs bg-[#0a0d14] border border-[#1c2438] rounded-md text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-36 sm:w-44"
              />
            </div>

            <Button
              size="sm"
              variant="outline"
              onClick={() => setIsExpanded(!isExpanded)}
              className="text-xs h-7 px-2.5 border-[#1c2438] text-slate-300 hover:text-white"
              title={isExpanded ? "Collapse view" : "Expand view"}
            >
              {isExpanded ? (
                <>
                  <Minimize2 className="w-3 h-3 mr-1" /> Collapse
                </>
              ) : (
                <>
                  <Maximize2 className="w-3 h-3 mr-1" /> Expand
                </>
              )}
            </Button>

            <a
              href={api.getScrapingLogUrl(batch.batch_id)}
              download
              className="inline-flex items-center gap-1 text-xs h-7 px-2.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 rounded-md transition"
              title="Download full scraping log file"
            >
              <Download className="w-3 h-3" /> Raw Log
            </a>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          <div
            className={`p-4 bg-[#0a0d14] font-mono text-xs text-slate-300 overflow-y-auto space-y-2 border-t border-[#1c2438] rounded-b-xl transition-all duration-200 ${
              isExpanded ? "max-h-[600px]" : "max-h-80"
            }`}
          >
            {filteredLogs.length > 0 ? (
              filteredLogs.map((log, idx) => {
                let badgeClass = "text-slate-300";
                if (log.includes("🌐") || log.includes("[Web Scraper]")) {
                  badgeClass = "text-cyan-300 bg-cyan-950/40 px-1.5 py-0.5 rounded border border-cyan-800/40 inline-block";
                } else if (log.includes("🧅") || log.includes("[Tor")) {
                  badgeClass = "text-purple-300 bg-purple-950/40 px-1.5 py-0.5 rounded border border-purple-800/40 inline-block";
                } else if (log.includes("↳ [Status 200]") || log.includes("✅")) {
                  badgeClass = "text-emerald-300";
                } else if (log.includes("⭐ [Scoring]")) {
                  badgeClass = "text-amber-300 bg-amber-950/30 px-1.5 py-0.5 rounded border border-amber-800/30 inline-block";
                } else if (log.includes("❌") || log.includes("[Error]") || log.includes("[Notice]")) {
                  badgeClass = "text-rose-300";
                } else if (log.includes("🎯")) {
                  badgeClass = "text-sky-300 font-semibold";
                }

                return (
                  <div key={idx} className="flex items-start gap-2 text-[11px] leading-relaxed">
                    <span className="text-slate-600 select-none text-[10px] pt-0.5 min-w-[20px] text-right">
                      {idx + 1}.
                    </span>
                    <span className={badgeClass}>{log}</span>
                  </div>
                );
              })
            ) : (
              <div className="text-slate-500 italic py-2">
                {logSearch ? `No logs matching "${logSearch}".` : "No events logged yet."}
              </div>
            )}
            <div ref={logEndRef} />
          </div>
        </CardContent>
      </Card>

      {/* Export Shortcuts */}
      <Card>
        <CardHeader>
          <CardTitle className="text-white text-sm">Batch Output Deliverables</CardTitle>
          <CardDescription>Download research artifacts and audit deliverables generated for this batch</CardDescription>
        </CardHeader>

        <CardContent className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <a
            href={api.getPrioritizedCsvUrl(batch.batch_id)}
            download
            className="p-4 rounded-lg bg-[#0e1320] border border-[#1c2438] hover:border-emerald-500/40 hover:bg-[#131929] transition block space-y-2 group"
          >
            <div className="flex items-center justify-between text-xs font-semibold text-white">
              <span className="flex items-center gap-1.5">
                <FileSpreadsheet className="w-4 h-4 text-emerald-400 group-hover:scale-110 transition" />
                <span>leads_prioritized.csv</span>
              </span>
              <Download className="w-3.5 h-3.5 text-slate-400 group-hover:text-emerald-400 transition" />
            </div>
            <p className="text-[11px] text-slate-400">
              Sorted enriched spreadsheet with numeric priorities (0, 1, 2)
            </p>
          </a>

          <a
            href={api.getScrapingLogUrl(batch.batch_id)}
            download
            className="p-4 rounded-lg bg-[#0e1320] border border-[#1c2438] hover:border-cyan-500/40 hover:bg-[#131929] transition block space-y-2 group"
          >
            <div className="flex items-center justify-between text-xs font-semibold text-white">
              <span className="flex items-center gap-1.5">
                <FileText className="w-4 h-4 text-cyan-400 group-hover:scale-110 transition" />
                <span>scraping.log</span>
              </span>
              <Download className="w-3.5 h-3.5 text-slate-400 group-hover:text-cyan-400 transition" />
            </div>
            <p className="text-[11px] text-slate-400">
              Full trace of all websites visited, Tor queries, and HTTP status codes
            </p>
          </a>

          <a
            href={api.getBatchZipUrl(batch.batch_id)}
            download
            className="p-4 rounded-lg bg-[#0e1320] border border-[#1c2438] hover:border-blue-500/40 hover:bg-[#131929] transition block space-y-2 group"
          >
            <div className="flex items-center justify-between text-xs font-semibold text-white">
              <span className="flex items-center gap-1.5">
                <FolderArchive className="w-4 h-4 text-blue-400 group-hover:scale-110 transition" />
                <span>Complete Batch ZIP</span>
              </span>
              <Download className="w-3.5 h-3.5 text-slate-400 group-hover:text-blue-400 transition" />
            </div>
            <p className="text-[11px] text-slate-400">
              Archive containing CSV, manifest, and all individual person JSON profiles
            </p>
          </a>

          <a
            href={api.getErrorsCsvUrl(batch.batch_id)}
            download
            className="p-4 rounded-lg bg-[#0e1320] border border-[#1c2438] hover:border-rose-500/40 hover:bg-[#131929] transition block space-y-2 group"
          >
            <div className="flex items-center justify-between text-xs font-semibold text-white">
              <span className="flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-rose-400 group-hover:scale-110 transition" />
                <span>errors.csv</span>
              </span>
              <Download className="w-3.5 h-3.5 text-slate-400 group-hover:text-rose-400 transition" />
            </div>
            <p className="text-[11px] text-slate-400">
              Diagnostic audit trail of any unreachable domains or failures
            </p>
          </a>
        </CardContent>
      </Card>
    </div>
  );
}
