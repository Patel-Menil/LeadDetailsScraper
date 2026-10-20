"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  UploadCloud,
  History,
  Download,
  ShieldCheck,
  Activity,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

const NAV_ITEMS = [
  {
    name: "Dashboard",
    href: "/",
    icon: LayoutDashboard,
    badge: null,
  },
  {
    name: "Prioritized Leads",
    href: "/leads",
    icon: Users,
    badge: "P0-P2",
  },
  {
    name: "Import Leads",
    href: "/import",
    icon: UploadCloud,
    badge: "CSV/XLSX",
  },
  {
    name: "Research Batches",
    href: "/batches",
    icon: History,
    badge: null,
  },
  {
    name: "Export Center",
    href: "/exports",
    icon: Download,
    badge: null,
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const [isBackendHealthy, setIsBackendHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    const checkHealth = async () => {
      try {
        await api.getHealth();
        if (mounted) setIsBackendHealthy(true);
      } catch {
        if (mounted) setIsBackendHealthy(false);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <aside className="w-64 border-r border-[#232c45] bg-[#0c101b] flex flex-col h-screen sticky top-0 select-none z-30">
      {/* Brand Header */}
      <div className="p-5 border-b border-[#1c2438] flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-blue-600/20 border border-blue-500/40 flex items-center justify-center text-blue-400">
          <ShieldCheck className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-white text-base tracking-tight">SealAPI</span>
            <span className="px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
              PRO
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-medium">Lead Research Pipeline</p>
        </div>
      </div>

      {/* Navigation */}
      <div className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
        <div className="px-3 pb-2 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
          Navigation
        </div>

        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150",
                isActive
                  ? "bg-blue-600 text-white shadow-sm shadow-blue-500/20"
                  : "text-slate-400 hover:text-slate-100 hover:bg-[#151b2c]"
              )}
            >
              <div className="flex items-center gap-3">
                <item.icon
                  className={cn(
                    "w-4 h-4 transition-colors",
                    isActive ? "text-white" : "text-slate-400 group-hover:text-slate-200"
                  )}
                />
                <span>{item.name}</span>
              </div>

              {item.badge && (
                <span
                  className={cn(
                    "text-[10px] px-1.5 py-0.2 rounded font-mono font-medium",
                    isActive
                      ? "bg-blue-700 text-blue-100"
                      : "bg-[#1c2438] text-slate-400 group-hover:text-slate-300"
                  )}
                >
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </div>

      {/* System Status Footer */}
      <div className="p-4 border-t border-[#1c2438] bg-[#0a0d14]/70 space-y-3">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "w-2 h-2 rounded-full",
                isBackendHealthy === true
                  ? "bg-emerald-400 shadow-sm shadow-emerald-400/50"
                  : isBackendHealthy === false
                  ? "bg-rose-500 animate-pulse"
                  : "bg-amber-400"
              )}
            />
            <span className="text-slate-300 text-[11px]">
              {isBackendHealthy === true
                ? "Backend Connected"
                : isBackendHealthy === false
                ? "Backend Disconnected"
                : "Checking System..."}
            </span>
          </div>
          <span className="text-[10px] text-slate-500 font-mono">Port 8000</span>
        </div>

        <div className="pt-2 border-t border-[#1c2438] flex items-center justify-between text-[11px] text-slate-500">
          <span>Engine: Scrapling v0.4+</span>
          <a
            href="https://github.com/D4Vinci/Scrapling"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-blue-400 transition flex items-center gap-1"
          >
            <span>Docs</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </div>
    </aside>
  );
}
