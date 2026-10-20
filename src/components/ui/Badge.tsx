import React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "p0" | "p1" | "p2" | "success" | "warning" | "danger" | "info" | "neutral";
  size?: "sm" | "md";
}

export function Badge({ children, variant = "neutral", size = "sm", className, ...props }: BadgeProps) {
  const variantStyles = {
    p0: "bg-red-500/10 text-red-400 border-red-500/30",
    p1: "bg-blue-500/10 text-blue-400 border-blue-500/30",
    p2: "bg-slate-500/10 text-slate-400 border-slate-500/30",
    success: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    warning: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    danger: "bg-rose-500/10 text-rose-400 border-rose-500/30",
    info: "bg-sky-500/10 text-sky-400 border-sky-500/30",
    neutral: "bg-slate-800/60 text-slate-300 border-slate-700/60",
  };

  const sizeStyles = {
    sm: "px-2 py-0.5 text-xs font-medium",
    md: "px-2.5 py-1 text-xs font-semibold",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border tracking-wide uppercase font-mono",
        variantStyles[variant],
        sizeStyles[size],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: number | string }) {
  const pStr = String(priority).trim();
  if (pStr === "0") {
    return <Badge variant="p0">Priority 0 &bull; High</Badge>;
  } else if (pStr === "1") {
    return <Badge variant="p1">Priority 1 &bull; Med</Badge>;
  } else if (pStr === "2") {
    return <Badge variant="p2">Priority 2 &bull; Low</Badge>;
  }
  return <Badge variant="neutral">Priority {priority}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const s = (status || "").toLowerCase().trim();
  if (s === "completed") {
    return <Badge variant="success">Completed</Badge>;
  } else if (s === "partial" || s === "review_required") {
    return <Badge variant="warning">Review Required</Badge>;
  } else if (s === "failed") {
    return <Badge variant="danger">Failed</Badge>;
  } else if (s === "processing") {
    return (
      <Badge variant="info" className="animate-pulse">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-ping inline-block" />
        Processing
      </Badge>
    );
  } else if (s === "pending") {
    return <Badge variant="neutral">Pending</Badge>;
  }
  return <Badge variant="neutral">{status}</Badge>;
}

export function ReadinessBadge({ readiness }: { readiness?: string }) {
  const r = (readiness || "").toLowerCase().trim();
  if (r === "ready") {
    return <Badge variant="success">Outreach Ready</Badge>;
  } else if (r === "ready_with_caveat") {
    return <Badge variant="warning">Ready (Caveat)</Badge>;
  } else if (r === "needs_research") {
    return <Badge variant="info">Needs Research</Badge>;
  } else if (r === "not_ready") {
    return <Badge variant="danger">Not Ready</Badge>;
  }
  return <Badge variant="neutral">{readiness || "Unassessed"}</Badge>;
}

