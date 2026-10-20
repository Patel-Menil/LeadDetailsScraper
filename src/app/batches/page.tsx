"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  History,
  FileSpreadsheet,
  Download,
  Eye,
  RefreshCw,
  ExternalLink,
  Layers,
  ArrowRight,
  FolderArchive,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { BatchSummary } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/Badge";
import { formatDateTime } from "@/lib/utils";

export default function BatchesHistoryPage() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchBatches = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listBatches();
      setBatches(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load batch history.");
    } finally {
      setLoading(false);
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm("Are you sure you want to delete ALL research batches and output data? This cannot be undone.")) {
      return;
    }
    setLoading(true);
    try {
      await api.clearAllBatches();
      await fetchBatches();
    } catch (err: any) {
      alert(err?.message || "Failed to clear batches.");
      setLoading(false);
    }
  };

  const handleDeleteBatch = async (batchId: string) => {
    if (!window.confirm(`Delete batch '${batchId}' and all its profiles?`)) {
      return;
    }
    try {
      await api.deleteBatch(batchId);
      await fetchBatches();
    } catch (err: any) {
      alert(err?.message || "Failed to delete batch.");
    }
  };

  useEffect(() => {
    fetchBatches();
  }, []);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#1c2438] pb-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <History className="w-5 h-5 text-blue-400" />
            <span>Research Batch History</span>
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Complete audit ledger of lead enrichment runs, Scrapling executions, and generated outputs.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {batches.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleClearAll}
              className="text-rose-400 border-rose-500/30 hover:bg-rose-500/10 gap-1.5 text-xs"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Clear History</span>
            </Button>
          )}

          <Button
            size="sm"
            variant="outline"
            onClick={fetchBatches}
            isLoading={loading}
            className="text-slate-300 text-xs"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </Button>

          <Link href="/import">
            <Button size="sm" variant="primary" className="gap-2 text-xs">
              <FileSpreadsheet className="w-4 h-4" />
              <span>New Batch</span>
            </Button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 text-sm">
          {error}
        </div>
      )}

      {/* Batches Table Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-white">Persisted Runs ({batches.length})</CardTitle>
          <CardDescription>Click any batch to view real-time progress or download exports</CardDescription>
        </CardHeader>

        <CardContent className="p-0 overflow-x-auto">
          {batches.length === 0 ? (
            <div className="p-12 text-center text-slate-400 space-y-3">
              <Layers className="w-8 h-8 mx-auto text-slate-600" />
              <p className="text-sm">No research batches found in storage.</p>
              <Link href="/import">
                <Button size="sm" variant="primary">
                  Upload First Spreadsheet
                </Button>
              </Link>
            </div>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="bg-[#0e1320] border-b border-[#1c2438] text-xs uppercase font-semibold text-slate-400">
                <tr>
                  <th className="py-3 px-5">Batch ID</th>
                  <th className="py-3 px-5">File & Context</th>
                  <th className="py-3 px-5">Total Leads</th>
                  <th className="py-3 px-5">Status</th>
                  <th className="py-3 px-5">Priority Breakdown</th>
                  <th className="py-3 px-5">Profiles Stored</th>
                  <th className="py-3 px-5">Timestamp</th>
                  <th className="py-3 px-5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1c2438] text-slate-300">
                {batches.map((batch) => (
                  <tr key={batch.batch_id} className="hover:bg-[#131929] transition-colors">
                    <td className="py-3.5 px-5 font-mono text-xs text-blue-400">
                      <Link href={`/batches/${batch.batch_id}`} className="hover:underline">
                        {batch.batch_id}
                      </Link>
                    </td>
                    <td className="py-3.5 px-5">
                      <div className="font-medium text-white max-w-[200px] truncate">
                        {batch.input_filename || "Spreadsheet Run"}
                      </div>
                    </td>
                    <td className="py-3.5 px-5 font-semibold text-slate-200">
                      {batch.total_leads}
                    </td>
                    <td className="py-3.5 px-5">
                      <StatusBadge status={batch.status} />
                    </td>
                    <td className="py-3.5 px-5">
                      <div className="flex items-center gap-1.5 text-xs font-mono">
                        <span className="text-red-400 font-semibold" title="P0 High">
                          P0: {batch.priority_counts?.["0"] ?? 0}
                        </span>
                        <span className="text-slate-600">|</span>
                        <span className="text-blue-400 font-semibold" title="P1 Med">
                          P1: {batch.priority_counts?.["1"] ?? 0}
                        </span>
                        <span className="text-slate-600">|</span>
                        <span className="text-slate-400 font-semibold" title="P2 Low">
                          P2: {batch.priority_counts?.["2"] ?? 0}
                        </span>
                      </div>
                    </td>
                    <td className="py-3.5 px-5 font-mono text-xs text-slate-300">
                      {batch.profiles_count ?? 0} files
                    </td>
                    <td className="py-3.5 px-5 text-xs text-slate-400 whitespace-nowrap">
                      {formatDateTime(batch.created_at)}
                    </td>
                    <td className="py-3.5 px-5 text-right space-x-2 whitespace-nowrap">
                      <Link href={`/leads?batch_id=${batch.batch_id}`}>
                        <Button size="sm" variant="ghost" className="text-xs h-7 px-2">
                          View Leads
                        </Button>
                      </Link>

                      <Link href={`/batches/${batch.batch_id}`}>
                        <Button size="sm" variant="outline" className="text-xs h-7 px-2">
                          Progress
                        </Button>
                      </Link>

                      {batch.csv_exists && (
                        <a
                          href={api.getBatchZipUrl(batch.batch_id)}
                          download
                          title="Download ZIP"
                        >
                          <Button size="sm" variant="secondary" className="text-xs h-7 px-2">
                            <FolderArchive className="w-3.5 h-3.5 text-blue-400" />
                          </Button>
                        </a>
                      )}

                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeleteBatch(batch.batch_id)}
                        title="Delete Batch"
                        className="text-xs h-7 px-2 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
