"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Users,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  TrendingUp,
  UploadCloud,
  FileSpreadsheet,
  ArrowRight,
  RefreshCw,
  Layers,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api";
import { DashboardStats } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge, PriorityBadge, StatusBadge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDashboardStats();
      setStats(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load dashboard statistics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  const total = stats?.total_leads || 0;
  const p0 = stats?.priority_0_count || 0;
  const p1 = stats?.priority_1_count || 0;
  const p2 = stats?.priority_2_count || 0;

  const p0Pct = total > 0 ? Math.round((p0 / total) * 100) : 0;
  const p1Pct = total > 0 ? Math.round((p1 / total) * 100) : 0;
  const p2Pct = total > 0 ? Math.round((p2 / total) * 100) : 0;

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Top Welcome & Refresh Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#1c2438]">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <span>Enterprise Intelligence Overview</span>
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Real-time telemetry and priority scoring from the Scrapling research pipeline.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            onClick={fetchStats}
            isLoading={loading}
            className="text-slate-300"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh Metrics</span>
          </Button>

          <Link href="/import">
            <Button size="sm" variant="primary" className="gap-2">
              <UploadCloud className="w-4 h-4" />
              <span>Import Leads</span>
            </Button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 text-sm flex items-center justify-between">
          <div className="flex items-center gap-3">
            <XCircle className="w-5 h-5 text-rose-400" />
            <span>{error}</span>
          </div>
          <Button size="sm" variant="outline" onClick={fetchStats}>
            Retry
          </Button>
        </div>
      )}

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* Total Leads */}
        <Card hoverEffect>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Total Enriched Leads
              </span>
              <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                <Users className="w-4 h-4" />
              </div>
            </div>
            <div className="mt-4 flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-white tracking-tight">
                {stats?.total_leads ?? 0}
              </span>
              <span className="text-xs text-slate-400">leads across batches</span>
            </div>
            <div className="mt-3 text-xs text-slate-500 flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-blue-400" />
              <span>{stats?.total_batches ?? 0} total batches recorded</span>
            </div>
          </CardContent>
        </Card>

        {/* Completed Research */}
        <Card hoverEffect>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Completed Research
              </span>
              <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                <CheckCircle2 className="w-4 h-4" />
              </div>
            </div>
            <div className="mt-4 flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-emerald-400 tracking-tight">
                {stats?.completed_count ?? 0}
              </span>
              <span className="text-xs text-slate-400">
                ({total > 0 ? Math.round(((stats?.completed_count || 0) / total) * 100) : 0}%)
              </span>
            </div>
            <div className="mt-3 text-xs text-slate-500 flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Full identity and context verified</span>
            </div>
          </CardContent>
        </Card>

        {/* Review Required / Partial */}
        <Card hoverEffect>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Review Required
              </span>
              <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                <AlertTriangle className="w-4 h-4" />
              </div>
            </div>
            <div className="mt-4 flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-amber-400 tracking-tight">
                {stats?.review_required_count ?? 0}
              </span>
              <span className="text-xs text-slate-400">partial info</span>
            </div>
            <div className="mt-3 text-xs text-slate-500 flex items-center gap-1.5">
              <span>Partial evidence retrieved</span>
            </div>
          </CardContent>
        </Card>

        {/* Failed */}
        <Card hoverEffect>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Research Failures
              </span>
              <div className="w-8 h-8 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
                <XCircle className="w-4 h-4" />
              </div>
            </div>
            <div className="mt-4 flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-rose-400 tracking-tight">
                {stats?.failed_count ?? 0}
              </span>
              <span className="text-xs text-slate-400">unreachable</span>
            </div>
            <div className="mt-3 text-xs text-slate-500 flex items-center gap-1.5">
              <span>Logged to error audit reports</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Priority Distribution Breakdown */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-blue-400" />
              <span>Priority Score Distribution</span>
            </CardTitle>
            <CardDescription>
              Deterministic scoring based on SealAPI value alignment (Security, LLM Guardrails, Enterprise AI)
            </CardDescription>
          </div>
          <Link href="/leads">
            <Button size="sm" variant="ghost" className="text-blue-400 hover:text-blue-300 gap-1 text-xs">
              <span>View All Prioritized Leads</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Button>
          </Link>
        </CardHeader>

        <CardContent className="space-y-6">
          {/* Progress Bar Visualizer */}
          <div className="h-3 w-full bg-[#1c2438] rounded-full overflow-hidden flex">
            <div
              style={{ width: `${p0Pct}%` }}
              className="bg-red-500 transition-all duration-500 hover:opacity-90"
              title={`Priority 0 (High): ${p0} leads (${p0Pct}%)`}
            />
            <div
              style={{ width: `${p1Pct}%` }}
              className="bg-blue-500 transition-all duration-500 hover:opacity-90"
              title={`Priority 1 (Medium): ${p1} leads (${p1Pct}%)`}
            />
            <div
              style={{ width: `${p2Pct}%` }}
              className="bg-slate-600 transition-all duration-500 hover:opacity-90"
              title={`Priority 2 (Low): ${p2} leads (${p2Pct}%)`}
            />
          </div>

          {/* Cards for each priority tier */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl border border-red-500/20 bg-red-500/5 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-red-400 uppercase tracking-wider font-mono">
                  Priority 0 &bull; High
                </span>
                <span className="text-xs font-mono text-slate-400">{p0Pct}%</span>
              </div>
              <div className="text-2xl font-bold text-white">{p0}</div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Security & AI decision-makers (CISO, VP Security, AI Lead) at enterprises or high-growth tech companies.
              </p>
            </div>

            <div className="p-4 rounded-xl border border-blue-500/20 bg-blue-500/5 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider font-mono">
                  Priority 1 &bull; Medium
                </span>
                <span className="text-xs font-mono text-slate-400">{p1Pct}%</span>
              </div>
              <div className="text-2xl font-bold text-white">{p1}</div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Technical leaders (CTO, VP Eng, Product) or security architects at general organizations.
              </p>
            </div>

            <div className="p-4 rounded-xl border border-slate-700/40 bg-slate-800/20 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider font-mono">
                  Priority 2 &bull; Low
                </span>
                <span className="text-xs font-mono text-slate-400">{p2Pct}%</span>
              </div>
              <div className="text-2xl font-bold text-white">{p2}</div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Adjacent roles, unverified technical titles, or non-technical domains requiring lower outreach priority.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Recent Batches History Table */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
              <span>Recent Research Batches</span>
            </CardTitle>
            <CardDescription>
              History of uploaded spreadsheets and Scrapling enrichment runs
            </CardDescription>
          </div>
          <Link href="/batches">
            <Button size="sm" variant="outline" className="gap-1 text-xs">
              <span>View All Batches</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Button>
          </Link>
        </CardHeader>

        <CardContent className="p-0">
          {!stats?.recent_batches || stats.recent_batches.length === 0 ? (
            <div className="p-8 text-center text-slate-400 space-y-3">
              <Layers className="w-8 h-8 mx-auto text-slate-600" />
              <p className="text-sm">No research batches processed yet.</p>
              <Link href="/import">
                <Button size="sm" variant="primary">
                  Upload First Lead List
                </Button>
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-[#0e1320] border-b border-[#1c2438] text-xs uppercase font-semibold text-slate-400">
                  <tr>
                    <th className="py-3 px-5">Batch ID</th>
                    <th className="py-3 px-5">Input File</th>
                    <th className="py-3 px-5">Total Leads</th>
                    <th className="py-3 px-5">Status</th>
                    <th className="py-3 px-5">Priority Tiers</th>
                    <th className="py-3 px-5">Created</th>
                    <th className="py-3 px-5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1c2438] text-slate-300">
                  {stats.recent_batches.map((batch) => (
                    <tr key={batch.batch_id} className="hover:bg-[#131929] transition-colors">
                      <td className="py-3.5 px-5 font-mono text-xs text-blue-400">
                        <Link href={`/batches/${batch.batch_id}`} className="hover:underline">
                          {batch.batch_id}
                        </Link>
                      </td>
                      <td className="py-3.5 px-5 font-medium text-white max-w-[200px] truncate">
                        {batch.input_filename || "Batch Upload"}
                      </td>
                      <td className="py-3.5 px-5">{batch.total_leads}</td>
                      <td className="py-3.5 px-5">
                        <StatusBadge status={batch.status} />
                      </td>
                      <td className="py-3.5 px-5">
                        <div className="flex items-center gap-1.5 text-xs font-mono">
                          <span className="text-red-400 font-semibold" title="P0 High">
                            {batch.priority_counts?.["0"] ?? 0}
                          </span>
                          <span className="text-slate-600">/</span>
                          <span className="text-blue-400 font-semibold" title="P1 Med">
                            {batch.priority_counts?.["1"] ?? 0}
                          </span>
                          <span className="text-slate-600">/</span>
                          <span className="text-slate-400 font-semibold" title="P2 Low">
                            {batch.priority_counts?.["2"] ?? 0}
                          </span>
                        </div>
                      </td>
                      <td className="py-3.5 px-5 text-xs text-slate-400">
                        {formatDateTime(batch.created_at)}
                      </td>
                      <td className="py-3.5 px-5 text-right space-x-2">
                        <Link href={`/leads?batch_id=${batch.batch_id}`}>
                          <Button size="sm" variant="ghost" className="text-xs h-7 px-2">
                            Leads
                          </Button>
                        </Link>
                        <Link href={`/batches/${batch.batch_id}`}>
                          <Button size="sm" variant="outline" className="text-xs h-7 px-2">
                            Details
                          </Button>
                        </Link>
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
  );
}
