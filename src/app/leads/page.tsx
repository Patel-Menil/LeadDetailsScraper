"use client";

import React, { useEffect, useState, useMemo, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Users,
  Search,
  Filter,
  ArrowUpDown,
  Download,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  RefreshCw,
  Eye,
  FileSpreadsheet,
  AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { PrioritizedLead, BatchSummary } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { PriorityBadge, StatusBadge } from "@/components/ui/Badge";

function PrioritizedLeadsContent() {
  const searchParams = useSearchParams();
  const initialBatchId = searchParams.get("batch_id") || "";

  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string>(initialBatchId);
  const [leads, setLeads] = useState<PrioritizedLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Search
  const [priorityFilter, setPriorityFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchTerm, setSearchTerm] = useState<string>("");

  // Pagination
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(25);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [totalRecords, setTotalRecords] = useState<number>(0);

  // Sorting
  const [sortField, setSortField] = useState<string>("priority");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");

  // Load available batches once
  useEffect(() => {
    const loadBatches = async () => {
      try {
        const batchList = await api.listBatches();
        setBatches(batchList);
        if (!selectedBatchId && batchList.length > 0) {
          const firstWithCsv = batchList.find((b) => b.csv_exists);
          if (firstWithCsv) {
            setSelectedBatchId(firstWithCsv.batch_id);
          } else {
            setSelectedBatchId(batchList[0].batch_id);
          }
        }
      } catch (e) {
        console.error("Failed to load batches:", e);
      }
    };
    loadBatches();
  }, [initialBatchId]);

  // Fetch leads when parameters change
  const fetchLeads = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getLeads({
        batchId: selectedBatchId || undefined,
        priority: priorityFilter !== "all" ? priorityFilter : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        search: searchTerm.trim() || undefined,
        page: page,
        pageSize: pageSize,
      });

      setLeads(res.leads || []);
      setTotalPages(res.total_pages || 1);
      setTotalRecords(res.total_records || 0);
    } catch (err: any) {
      setError(err?.message || "Failed to load prioritized leads.");
      setLeads([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLeads();
  }, [selectedBatchId, priorityFilter, statusFilter, page, pageSize]);

  // Handle client-side search trigger
  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchLeads();
  };

  // Sorting helper: 0 first, then 1, then 2
  const sortedLeads = useMemo(() => {
    return [...leads].sort((a, b) => {
      let aVal = a[sortField];
      let bVal = b[sortField];

      if (sortField === "priority") {
        const numA = Number(aVal ?? 99);
        const numB = Number(bVal ?? 99);
        return sortDirection === "asc" ? numA - numB : numB - numA;
      }

      aVal = String(aVal || "").toLowerCase();
      bVal = String(bVal || "").toLowerCase();
      if (aVal < bVal) return sortDirection === "asc" ? -1 : 1;
      if (aVal > bVal) return sortDirection === "asc" ? 1 : -1;
      return 0;
    });
  }, [leads, sortField, sortDirection]);

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#1c2438] pb-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Users className="w-5 h-5 text-blue-400" />
            <span>Prioritized Lead Registry</span>
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Enriched profiles ranked strictly by SealAPI product fit (0 = Highest, 1 = Medium, 2 = Lowest).
          </p>
        </div>

        <div className="flex items-center gap-3">
          {selectedBatchId && (
            <a
              href={api.getPrioritizedCsvUrl(selectedBatchId)}
              download
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button size="sm" variant="outline" className="gap-2 text-xs">
                <Download className="w-3.5 h-3.5" />
                <span>Download CSV</span>
              </Button>
            </a>
          )}

          <Button
            size="sm"
            variant="outline"
            onClick={fetchLeads}
            isLoading={loading}
            className="text-slate-300"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </Button>
        </div>
      </div>

      {/* Filter and Control Bar */}
      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            {/* Batch Selector */}
            <div>
              <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                Batch
              </label>
              <select
                value={selectedBatchId}
                onChange={(e) => {
                  setSelectedBatchId(e.target.value);
                  setPage(1);
                }}
                className="w-full bg-[#0e1320] border border-[#232c45] rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
              >
                {batches.length === 0 ? (
                  <option value="">No batches found</option>
                ) : (
                  batches.map((b) => (
                    <option key={b.batch_id} value={b.batch_id}>
                      {b.input_filename || b.batch_id} ({b.total_leads} leads)
                    </option>
                  ))
                )}
              </select>
            </div>

            {/* Priority Filter */}
            <div>
              <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                Priority Tier
              </label>
              <select
                value={priorityFilter}
                onChange={(e) => {
                  setPriorityFilter(e.target.value);
                  setPage(1);
                }}
                className="w-full bg-[#0e1320] border border-[#232c45] rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="all">All Priorities</option>
                <option value="0">Priority 0 (High - CISO, AI Sec)</option>
                <option value="1">Priority 1 (Medium - CTO, Eng)</option>
                <option value="2">Priority 2 (Low - General)</option>
              </select>
            </div>

            {/* Status Filter */}
            <div>
              <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                Research Status
              </label>
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(1);
                }}
                className="w-full bg-[#0e1320] border border-[#232c45] rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="all">All Statuses</option>
                <option value="completed">Completed</option>
                <option value="partial">Review Required</option>
                <option value="failed">Failed</option>
              </select>
            </div>

            {/* Search Input Form */}
            <div>
              <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                Search Leads
              </label>
              <form onSubmit={handleSearchSubmit} className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search name, title, company..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full bg-[#0e1320] border border-[#232c45] rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <Button size="sm" variant="secondary" type="submit" className="text-xs px-2.5">
                  Go
                </Button>
              </form>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Error Message */}
      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 text-sm flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-rose-400" />
            <span>{error}</span>
          </div>
          <Button size="sm" variant="outline" onClick={fetchLeads}>
            Retry
          </Button>
        </div>
      )}

      {/* Leads Table */}
      <Card>
        <CardHeader className="flex-row items-center justify-between py-3.5 px-5">
          <div className="text-xs text-slate-400">
            Showing <span className="font-semibold text-white">{sortedLeads.length}</span> of{" "}
            <span className="font-semibold text-white">{totalRecords}</span> leads
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Rows per page:</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="bg-[#0e1320] border border-[#232c45] rounded px-2 py-1 text-xs text-slate-300"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        </CardHeader>

        <CardContent className="p-0 overflow-x-auto">
          {sortedLeads.length === 0 ? (
            <div className="p-12 text-center text-slate-400 space-y-3">
              <Users className="w-8 h-8 mx-auto text-slate-600" />
              <p className="text-sm font-medium">No leads match the selected criteria.</p>
              <p className="text-xs text-slate-500">
                Try selecting a different batch or clearing priority and status filters.
              </p>
            </div>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="bg-[#0e1320] border-b border-[#1c2438] text-xs uppercase font-semibold text-slate-400">
                <tr>
                  <th
                    className="py-3 px-4 cursor-pointer hover:text-white"
                    onClick={() => toggleSort("priority")}
                  >
                    <div className="flex items-center gap-1.5 font-mono">
                      <span>Priority</span>
                      <ArrowUpDown className="w-3 h-3 text-slate-500" />
                    </div>
                  </th>
                  <th
                    className="py-3 px-4 cursor-pointer hover:text-white"
                    onClick={() => toggleSort("name")}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Lead Name</span>
                      <ArrowUpDown className="w-3 h-3 text-slate-500" />
                    </div>
                  </th>
                  <th
                    className="py-3 px-4 cursor-pointer hover:text-white"
                    onClick={() => toggleSort("job_title")}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Job Title</span>
                      <ArrowUpDown className="w-3 h-3 text-slate-500" />
                    </div>
                  </th>
                  <th
                    className="py-3 px-4 cursor-pointer hover:text-white"
                    onClick={() => toggleSort("company")}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Company</span>
                      <ArrowUpDown className="w-3 h-3 text-slate-500" />
                    </div>
                  </th>
                  <th className="py-3 px-4">Priority Rationale</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1c2438] text-slate-300">
                {sortedLeads.map((lead) => {
                  const leadUrl = `/leads/${lead.lead_id}${selectedBatchId ? `?batch_id=${selectedBatchId}` : ""}`;
                  return (
                    <tr key={lead.lead_id} className="hover:bg-[#131929] transition-colors">
                      <td className="py-3 px-4 whitespace-nowrap">
                        <PriorityBadge priority={lead.priority} />
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        <Link
                          href={leadUrl}
                          className="font-medium text-white hover:text-blue-400 transition"
                        >
                          {lead.name}
                        </Link>
                        {lead.professional_email && (
                          <div className="text-[11px] text-slate-500 font-mono">
                            {lead.professional_email}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-xs text-slate-300 max-w-[200px] truncate">
                        {lead.job_title}
                      </td>
                      <td className="py-3 px-4 text-xs font-medium text-slate-200 whitespace-nowrap">
                        {lead.company}
                        {lead.industry && (
                          <span className="block text-[11px] text-slate-500 font-normal">
                            {lead.industry}
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-xs text-slate-400 max-w-[280px] truncate" title={lead.priority_reason}>
                        {lead.priority_reason || lead.relevance_evidence || "—"}
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        <StatusBadge status={lead.research_status} />
                      </td>
                      <td className="py-3 px-4 text-right whitespace-nowrap">
                        <Link href={leadUrl}>
                          <Button size="sm" variant="outline" className="text-xs h-7 px-2.5 gap-1.5">
                            <Eye className="w-3 h-3 text-blue-400" />
                            <span>Profile</span>
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>

        {/* Pagination Bar */}
        <div className="p-4 border-t border-[#1c2438] flex items-center justify-between">
          <div className="text-xs text-slate-400">
            Page <span className="font-semibold text-white">{page}</span> of{" "}
            <span className="font-semibold text-white">{totalPages}</span>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="text-xs h-8 px-2.5"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Previous</span>
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="text-xs h-8 px-2.5"
            >
              <span>Next</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

export default function PrioritizedLeadsPage() {
  return (
    <Suspense
      fallback={
        <div className="p-12 text-center text-slate-400 space-y-3 max-w-4xl mx-auto">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm">Loading prioritized leads registry...</p>
        </div>
      }
    >
      <PrioritizedLeadsContent />
    </Suspense>
  );
}
