/**
 * Typed API Client for SealAPI Lead Research Backend
 */

import {
  DashboardStats,
  BatchSummary,
  BatchProgress,
  UploadInspection,
  BatchLeadsResponse,
  LeadProfile,
  StartBatchPayload,
  TorStatus,
} from "@/types";
import { UNAUTHORIZED_EVENT } from "@/lib/session.mjs";

const API_BASE = "";

/** Tell the AuthGate to show the login screen instead of an error banner. */
function notifyUnauthorized(status: number) {
  if (status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(options?.headers as Record<string, string>),
  };

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    let errorDetail = `Request failed with status ${response.status}`;
    try {
      const errorJson = await response.json();
      errorDetail = errorJson.detail || errorJson.message || errorDetail;
    } catch {
      // ignore json parse error on response
    }
    notifyUnauthorized(response.status);
    throw new ApiError(errorDetail, response.status);
  }

  return response.json();
}

export const api = {
  // System Health
  async getHealth(): Promise<{ status: string; storage: Record<string, any>; active_batches_count: number }> {
    return request("/api/health");
  },

  // Tor Proxy Status & Management
  async getTorStatus(verifyRouting: boolean = false): Promise<TorStatus> {
    const query = verifyRouting ? "?verify_routing=true" : "";
    return request(`/api/tor/status${query}`);
  },

  async startTor(): Promise<{ success: boolean; message: string; port: number | null }> {
    return request("/api/tor/start", { method: "POST" });
  },

  // Dashboard Aggregated Stats
  async getDashboardStats(): Promise<DashboardStats> {
    return request("/api/dashboard/stats");
  },

  // File Upload & Inspection
  async uploadLeadsFile(file: File): Promise<UploadInspection> {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch("/api/batches/upload", {
      method: "POST",
      body: formData,
      headers: {
        Accept: "application/json",
      },
      credentials: "same-origin",
    });

    if (!response.ok) {
      let errorDetail = `Upload failed with status ${response.status}`;
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || errorJson.message || errorDetail;
      } catch {
        // ignore
      }
      notifyUnauthorized(response.status);
      throw new ApiError(errorDetail, response.status);
    }

    return response.json();
  },

  // Start Batch Pipeline
  async startBatch(batchId: string, payload: StartBatchPayload = {}): Promise<{ message: string; batch_id: string }> {
    return request(`/api/batches/${encodeURIComponent(batchId)}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  // List all batches
  async listBatches(): Promise<BatchSummary[]> {
    return request("/api/batches");
  },

  // Delete specific batch
  async deleteBatch(batchId: string): Promise<{ message: string }> {
    return request(`/api/batches/${encodeURIComponent(batchId)}`, {
      method: "DELETE",
    });
  },

  // Clear all batches & history
  async clearAllBatches(): Promise<{ message: string }> {
    return request("/api/batches", {
      method: "DELETE",
    });
  },

  // Get specific batch progress/status
  async getBatchStatus(batchId: string): Promise<BatchProgress> {
    return request(`/api/batches/${encodeURIComponent(batchId)}`);
  },

  // Retrieve prioritized leads from batch or global latest
  async getLeads(params: {
    batchId?: string;
    priority?: string;
    status?: string;
    search?: string;
    page?: number;
    pageSize?: number;
  } = {}): Promise<BatchLeadsResponse> {
    const query = new URLSearchParams();
    if (params.priority && params.priority !== "all") query.append("priority", params.priority);
    if (params.status && params.status !== "all") query.append("status", params.status);
    if (params.search) query.append("search", params.search);
    if (params.page) query.append("page", String(params.page));
    if (params.pageSize) query.append("page_size", String(params.pageSize));

    if (params.batchId) {
      return request(`/api/batches/${encodeURIComponent(params.batchId)}/leads?${query.toString()}`);
    } else {
      return request(`/api/leads?${query.toString()}`);
    }
  },

  // Individual Lead Profile
  async getLeadProfile(leadId: string, batchId?: string): Promise<{ batch_id: string; lead_id: string; filename: string; profile: LeadProfile }> {
    const query = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
    return request(`/api/leads/${encodeURIComponent(leadId)}/profile${query}`);
  },

  // Direct export URL builders
  getPrioritizedCsvUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/prioritized.csv`;
  },

  getErrorsCsvUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/errors.csv`;
  },

  getScrapingLogUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/scraping.log`;
  },

  getBatchZipUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/zip`;
  },

  getManifestUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/manifest.json`;
  },

  getProfileJsonUrl(batchId: string, filename: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/profiles/${encodeURIComponent(filename)}`;
  },

  getOutreachReadyCsvUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/outreach_ready.csv`;
  },

  getNeedsReviewCsvUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/needs_review.csv`;
  },

  getSummaryUrl(batchId: string): string {
    return `/api/batches/${encodeURIComponent(batchId)}/exports/summary.json`;
  },

  async getLatestBatch(): Promise<any> {
    return request("/api/batches/latest");
  },
};
