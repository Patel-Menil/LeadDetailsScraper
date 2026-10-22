"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus, ChevronRight, Sparkles, LogOut } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { logout } from "@/lib/session.mjs";

async function signOut() {
  await logout().catch(() => undefined);
  window.location.reload();
}

export function Navbar() {
  const pathname = usePathname();

  // Simple title mapper
  let pageTitle = "Dashboard";
  let breadcrumbs = [{ label: "Home", href: "/" }];

  if (pathname.startsWith("/leads/")) {
    pageTitle = "Lead Research Profile";
    breadcrumbs = [
      { label: "Dashboard", href: "/" },
      { label: "Prioritized Leads", href: "/leads" },
      { label: "Profile", href: pathname },
    ];
  } else if (pathname === "/leads") {
    pageTitle = "Prioritized Leads";
    breadcrumbs = [
      { label: "Dashboard", href: "/" },
      { label: "Prioritized Leads", href: "/leads" },
    ];
  } else if (pathname === "/import") {
    pageTitle = "Import & Research Pipeline";
    breadcrumbs = [
      { label: "Dashboard", href: "/" },
      { label: "Import Leads", href: "/import" },
    ];
  } else if (pathname.startsWith("/batches/")) {
    pageTitle = "Batch Progress & Results";
    breadcrumbs = [
      { label: "Dashboard", href: "/" },
      { label: "Batches", href: "/batches" },
      { label: "Batch Details", href: pathname },
    ];
  } else if (pathname === "/batches") {
    pageTitle = "Research Batch History";
    breadcrumbs = [
      { label: "Dashboard", href: "/" },
      { label: "Batches", href: "/batches" },
    ];
  } else if (pathname === "/exports") {
    pageTitle = "Export Center";
    breadcrumbs = [
      { label: "Dashboard", href: "/" },
      { label: "Export Center", href: "/exports" },
    ];
  }

  return (
    <header className="h-16 border-b border-[#232c45] bg-[#0c101b]/80 backdrop-blur-md px-8 flex items-center justify-between sticky top-0 z-20">
      {/* Left: Breadcrumbs & Page Title */}
      <div className="flex flex-col">
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          {breadcrumbs.map((crumb, idx) => (
            <React.Fragment key={crumb.href + idx}>
              {idx > 0 && <ChevronRight className="w-3 h-3 text-slate-600" />}
              {idx === breadcrumbs.length - 1 ? (
                <span className="text-slate-200 font-medium">{crumb.label}</span>
              ) : (
                <Link href={crumb.href} className="hover:text-blue-400 transition">
                  {crumb.label}
                </Link>
              )}
            </React.Fragment>
          ))}
        </div>
        <h1 className="text-lg font-semibold text-white tracking-tight leading-tight">
          {pageTitle}
        </h1>
      </div>

      {/* Right: Quick Actions */}
      <div className="flex items-center gap-3">
        {pathname !== "/import" && (
          <Link href="/import">
            <Button size="sm" variant="primary" className="gap-1.5 shadow-md shadow-blue-600/20">
              <Plus className="w-3.5 h-3.5" />
              <span>Import Leads</span>
            </Button>
          </Link>
        )}
        <Button size="sm" variant="ghost" onClick={signOut} className="gap-1.5">
          <LogOut className="w-3.5 h-3.5" />
          <span>Sign out</span>
        </Button>
      </div>
    </header>
  );
}
