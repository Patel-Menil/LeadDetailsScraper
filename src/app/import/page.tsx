"use client";

import React, { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  UploadCloud,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Play,
  Settings,
  ArrowRight,
  Eye,
  Info,
  Globe,
  ShieldCheck,
  Cpu,
  RefreshCw,
  Sparkles,
  Radio,
} from "lucide-react";
import { api } from "@/lib/api";
import { UploadInspection, TorStatus } from "@/types";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";

const TARGET_FIELDS = [
  { key: "name", label: "Full Name", required: true },
  { key: "job_title", label: "Job Title", required: true },
  { key: "company", label: "Company", required: true },
  { key: "industry", label: "Industry", required: false },
  { key: "linkedin_url", label: "LinkedIn URL", required: false },
  { key: "company_website", label: "Company Website", required: false },
  { key: "professional_email", label: "Work Email", required: false },
];

export default function ImportPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [inspection, setInspection] = useState<UploadInspection | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Configuration options
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [dryRun, setDryRun] = useState(false);
  const [concurrency, setConcurrency] = useState(2);
  const [maxLeads, setMaxLeads] = useState<number | undefined>(undefined);

  // Scrapling Browser & Tor Options
  const [useBrowser, setUseBrowser] = useState(true);
  const [useTor, setUseTor] = useState(true);
  const [torStatus, setTorStatus] = useState<TorStatus | null>(null);
  const [startingTor, setStartingTor] = useState(false);

  // Confirmation modal state
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [starting, setStarting] = useState(false);

  // Check Tor status on mount
  useEffect(() => {
    checkTorStatus();
  }, []);

  const checkTorStatus = async () => {
    try {
      const status = await api.getTorStatus();
      setTorStatus(status);
    } catch (e) {
      console.warn("Failed to query Tor status:", e);
    }
  };

  const handleStartTor = async () => {
    setStartingTor(true);
    try {
      await api.startTor();
      await checkTorStatus();
    } catch (e: any) {
      console.error("Failed to start Tor proxy:", e);
    } finally {
      setStartingTor(false);
    }
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processSelectedFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processSelectedFile(e.target.files[0]);
    }
  };

  const processSelectedFile = async (selectedFile: File) => {
    setFile(selectedFile);
    setError(null);
    setInspection(null);
    setUploading(true);

    try {
      const data = await api.uploadLeadsFile(selectedFile);
      setInspection(data);
      setMapping(data.detected_mapping || {});
    } catch (err: any) {
      setError(err?.message || "Failed to inspect uploaded file.");
      setFile(null);
    } finally {
      setUploading(false);
    }
  };

  const handleStartResearch = async () => {
    if (!inspection) return;
    setStarting(true);
    try {
      await api.startBatch(inspection.batch_id, {
        mapping_override: mapping,
        dry_run: dryRun,
        concurrency: concurrency,
        max_leads: maxLeads || undefined,
        resume: true,
        use_browser: useBrowser,
        use_tor: useTor,
      });
      setConfirmModalOpen(false);
      router.push(`/batches/${inspection.batch_id}`);
    } catch (err: any) {
      setError(err?.message || "Failed to start research batch.");
      setStarting(false);
    }
  };

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Header Info */}
      <div className="border-b border-[#1c2438] pb-4">
        <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
          <UploadCloud className="w-5 h-5 text-blue-400" />
          <span>Upload & Scrape Leads</span>
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          Upload your CSV or Excel lead file. Scraping will begin only when you click the Scrape button below.
        </p>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold">Import Issue</p>
            <p className="text-xs text-rose-200/90 leading-relaxed">{error}</p>
          </div>
        </div>
      )}

      {/* Upload Zone */}
      {!inspection && (
        <Card className="border-dashed border-2 border-[#232c45] bg-[#0d121f]/50 hover:bg-[#0d121f] transition-all">
          <CardContent className="p-12 text-center">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={handleFileSelect}
            />

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleFileDrop}
              onClick={() => fileInputRef.current?.click()}
              className="cursor-pointer flex flex-col items-center justify-center space-y-4"
            >
              <div
                className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all ${
                  dragOver
                    ? "bg-blue-600/30 text-blue-400 border border-blue-500 scale-110"
                    : "bg-[#141a29] text-slate-400 border border-[#232c45]"
                }`}
              >
                {uploading ? (
                  <div className="w-7 h-7 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <FileSpreadsheet className="w-8 h-8 text-blue-400" />
                )}
              </div>

              <div className="space-y-1.5 max-w-sm">
                <p className="text-base font-semibold text-white">
                  {uploading
                    ? "Inspecting file schema & preview..."
                    : "Click to upload or drag & drop"}
                </p>
                <p className="text-xs text-slate-400">
                  CSV or Excel (.xlsx, .xls) files supported. Leads are validated before scraping.
                </p>
              </div>

              <Button
                variant="secondary"
                size="sm"
                className="mt-2 text-xs"
                disabled={uploading}
                onClick={(e) => {
                  e.stopPropagation();
                  fileInputRef.current?.click();
                }}
              >
                Browse Files
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Inspected File Preview & Configuration */}
      {inspection && (
        <div className="space-y-6 animate-fade-in">
          {/* File Overview Stats */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-white flex items-center gap-2">
                  <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
                  <span>{inspection.filename}</span>
                </CardTitle>
                <CardDescription>
                  Batch ID: <span className="font-mono text-blue-400">{inspection.batch_id}</span> • {(inspection.size_bytes / 1024).toFixed(1)} KB
                </CardDescription>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setInspection(null);
                  setFile(null);
                }}
                className="text-xs text-slate-400"
              >
                Replace File
              </Button>
            </CardHeader>

            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
                <div className="p-3 rounded-lg bg-[#0e1320] border border-[#1c2438]">
                  <span className="text-[11px] text-slate-400">Total Rows</span>
                  <div className="text-lg font-bold text-white font-mono">{inspection.total_rows}</div>
                </div>

                <div className="p-3 rounded-lg bg-[#0e1320] border border-[#1c2438]">
                  <span className="text-[11px] text-emerald-400 flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Valid Leads
                  </span>
                  <div className="text-lg font-bold text-emerald-400 font-mono">
                    {inspection.valid_leads_count}
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-[#0e1320] border border-[#1c2438]">
                  <span className="text-[11px] text-amber-400 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> Duplicates Removed
                  </span>
                  <div className="text-lg font-bold text-amber-400 font-mono">
                    {inspection.duplicate_count}
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-[#0e1320] border border-[#1c2438]">
                  <span className="text-[11px] text-rose-400 flex items-center gap-1">
                    <XCircle className="w-3 h-3" /> Malformed Rows
                  </span>
                  <div className="text-lg font-bold text-rose-400 font-mono">
                    {inspection.malformed_count}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Column Mapping Section */}
          <Card>
            <CardHeader>
              <CardTitle className="text-white flex items-center gap-2">
                <Settings className="w-4 h-4 text-blue-400" />
                <span>Column Schema Mapping</span>
              </CardTitle>
              <CardDescription>
                Verify mapped fields from your spreadsheet headers to SealAPI standard lead attributes
              </CardDescription>
            </CardHeader>

            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
                {TARGET_FIELDS.map((target) => (
                  <div key={target.key} className="space-y-1.5 p-3 rounded-lg bg-[#0e1320] border border-[#1c2438]">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-medium text-slate-300">
                        {target.label}
                        {target.required && <span className="text-rose-400 ml-1">*</span>}
                      </label>
                      {mapping[target.key] ? (
                        <Badge variant="success">Mapped</Badge>
                      ) : target.required ? (
                        <Badge variant="danger">Required</Badge>
                      ) : (
                        <Badge variant="neutral">Optional</Badge>
                      )}
                    </div>

                    <select
                      value={mapping[target.key] || ""}
                      onChange={(e) =>
                        setMapping((prev) => ({
                          ...prev,
                          [target.key]: e.target.value,
                        }))
                      }
                      className="w-full bg-[#151b2c] border border-[#232c45] rounded-md px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 font-mono"
                    >
                      <option value="">-- Unmapped --</option>
                      {inspection.headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Data Preview Table */}
          {inspection.preview_rows.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-white flex items-center gap-2">
                  <Eye className="w-4 h-4 text-blue-400" />
                  <span>Input Data Sample</span>
                </CardTitle>
                <CardDescription>First {inspection.preview_rows.length} rows detected from the uploaded sheet</CardDescription>
              </CardHeader>

              <CardContent className="p-0 overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-y border-[#1c2438] bg-[#0c101a] text-slate-400 font-semibold">
                      <th className="py-2.5 px-4 w-12 font-mono">#</th>
                      {inspection.headers.slice(0, 6).map((hdr) => (
                        <th key={hdr} className="py-2.5 px-4 font-mono truncate max-w-[150px]">
                          {hdr}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1c2438] text-slate-300">
                    {inspection.preview_rows.map((row, idx) => (
                      <tr key={idx} className="hover:bg-[#131929]">
                        <td className="py-2 px-4 font-mono text-slate-500">{idx + 1}</td>
                        {inspection.headers.slice(0, 6).map((hdr) => (
                          <td key={hdr} className="py-2 px-4 truncate max-w-[150px]">
                            {row[hdr] || "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}

          {/* Scrapling Browser & Tor Scraping Controls */}
          <Card className="border border-blue-500/30 bg-gradient-to-br from-[#0c101a] via-[#0d1322] to-[#0c101a]">
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-white flex items-center gap-2">
                    <Globe className="w-4 h-4 text-emerald-400" />
                    <span>Scrapling Browser Scraping & Tor Network</span>
                  </CardTitle>
                  <CardDescription>
                    Automated Chromium browser extraction powered by Scrapling (Patchright) with DuckDuckGo intelligence
                  </CardDescription>
                </div>

                {/* Tor Status Badge */}
                <div className="flex items-center gap-2">
                  {torStatus?.is_running ? (
                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium">
                      <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                      <span>Tor Active (Port {torStatus.port})</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-amber-400">Tor Offline</span>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={handleStartTor}
                        isLoading={startingTor}
                        className="text-[11px] h-6 px-2 text-amber-300 border-amber-500/30 hover:bg-amber-500/10"
                      >
                        Start Tor
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            </CardHeader>

            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                {/* Browser Engine Toggle */}
                <div className="p-3.5 rounded-lg bg-[#0e1320] border border-[#1c2438] flex flex-col justify-between">
                  <div>
                    <label className="text-xs font-semibold text-white flex items-center gap-1.5">
                      <Globe className="w-3.5 h-3.5 text-blue-400" />
                      <span>Browser Engine</span>
                    </label>
                    <p className="text-[11px] text-slate-400 mt-1">
                      Scrapling Stealth Chromium with anti-bot evasion.
                    </p>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="useBrowser"
                      checked={useBrowser}
                      onChange={(e) => setUseBrowser(e.target.checked)}
                      className="rounded bg-[#151b2c] border-[#232c45] text-emerald-500 focus:ring-0 w-4 h-4 cursor-pointer"
                    />
                    <label htmlFor="useBrowser" className="text-xs text-emerald-400 font-medium cursor-pointer">
                      Stealth Chromium
                    </label>
                  </div>
                </div>

                {/* Tor Proxy Toggle */}
                <div className="p-3.5 rounded-lg bg-[#0e1320] border border-[#1c2438] flex flex-col justify-between">
                  <div>
                    <label className="text-xs font-semibold text-white flex items-center gap-1.5">
                      <ShieldCheck className="w-3.5 h-3.5 text-purple-400" />
                      <span>Tor SOCKS Proxy</span>
                    </label>
                    <p className="text-[11px] text-slate-400 mt-1">
                      Routes DuckDuckGo queries via 127.0.0.1:9050.
                    </p>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="useTor"
                      checked={useTor}
                      onChange={(e) => setUseTor(e.target.checked)}
                      className="rounded bg-[#151b2c] border-[#232c45] text-purple-500 focus:ring-0 w-4 h-4 cursor-pointer"
                    />
                    <label htmlFor="useTor" className="text-xs text-purple-300 font-medium cursor-pointer">
                      Enable Tor Routing
                    </label>
                  </div>
                </div>

                {/* Concurrency Slider */}
                <div className="p-3.5 rounded-lg bg-[#0e1320] border border-[#1c2438]">
                  <label className="text-xs font-semibold text-white block">Worker Concurrency</label>
                  <p className="text-[11px] text-slate-400 mt-1">
                    Simultaneous browser scraping threads (1 - 4).
                  </p>
                  <div className="mt-3 flex items-center gap-3">
                    <input
                      type="range"
                      min={1}
                      max={4}
                      value={concurrency}
                      onChange={(e) => setConcurrency(Number(e.target.value))}
                      className="w-full accent-blue-500 cursor-pointer"
                    />
                    <span className="font-mono text-sm text-blue-400 font-bold w-4">{concurrency}</span>
                  </div>
                </div>

                {/* Lead Processing Limit */}
                <div className="p-3.5 rounded-lg bg-[#0e1320] border border-[#1c2438]">
                  <label className="text-xs font-semibold text-white block">Lead Limit (Optional)</label>
                  <p className="text-[11px] text-slate-400 mt-1">
                    Test subset of leads or leave blank for all.
                  </p>
                  <input
                    type="number"
                    min={1}
                    placeholder={`All (${inspection.valid_leads_count})`}
                    value={maxLeads || ""}
                    onChange={(e) => setMaxLeads(e.target.value ? Number(e.target.value) : undefined)}
                    className="mt-2 w-full bg-[#151b2c] border border-[#232c45] rounded-md px-2.5 py-1 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
                  />
                </div>
              </div>

              {/* Start Scraping CTA Section */}
              <div className="pt-4 border-t border-[#1c2438] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="text-xs text-slate-400 space-y-1">
                  <div className="flex items-center gap-1.5 text-slate-300 font-medium">
                    <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Scraping triggers only upon clicking the button.</span>
                  </div>
                  <p className="text-[11px] text-slate-500">
                    Will generate one individual <code className="text-blue-400 font-mono">person_*.json</code> profile per lead and compile <code className="text-blue-400 font-mono">leads_prioritized.csv</code>.
                  </p>
                </div>

                {/* THE EXPLICIT SCRAPING BUTTON */}
                <Button
                  size="lg"
                  variant="primary"
                  onClick={() => setConfirmModalOpen(true)}
                  className="gap-2.5 shadow-xl shadow-emerald-600/25 bg-emerald-600 hover:bg-emerald-500 border border-emerald-400/30 text-white font-bold px-6 py-2.5 text-sm"
                >
                  <Play className="w-4 h-4 fill-white" />
                  <span>Start Scraping Leads</span>
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Explicit Confirmation Modal */}
          <Modal
            isOpen={confirmModalOpen}
            onClose={() => setConfirmModalOpen(false)}
            title="Start Browser Scraping with Scrapling"
            description="Scraping will begin immediately upon confirmation."
          >
            <div className="space-y-4 text-sm text-slate-300">
              <div className="p-3.5 rounded-lg bg-[#0e1320] border border-[#1c2438] space-y-2.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-400">Batch Identifier:</span>
                  <span className="font-mono text-blue-400 font-semibold">{inspection.batch_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Leads to Scrape:</span>
                  <span className="font-bold text-white">
                    {maxLeads ? Math.min(maxLeads, inspection.valid_leads_count) : inspection.valid_leads_count} leads
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Scraper Engine:</span>
                  <span className="text-emerald-400 font-medium">Scrapling StealthyFetcher (Chromium)</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Search Engine:</span>
                  <span className="text-blue-400 font-medium">DuckDuckGo Public Web</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Proxy Route:</span>
                  <span className="text-purple-400 font-medium">{useTor ? "Tor SOCKS (127.0.0.1:9050)" : "Direct"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Output Artifacts:</span>
                  <span className="text-slate-200 font-mono">profiles/*.json + leads_prioritized.csv</span>
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#1c2438]">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmModalOpen(false)}
                  disabled={starting}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  isLoading={starting}
                  onClick={handleStartResearch}
                  className="gap-2 bg-emerald-600 hover:bg-emerald-500 font-semibold"
                >
                  <Play className="w-3.5 h-3.5 fill-white" />
                  <span>Confirm & Start Scraping</span>
                </Button>
              </div>
            </div>
          </Modal>
        </div>
      )}
    </div>
  );
}
