import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { Navbar } from "@/components/Navbar";
import { AuthGate } from "@/components/AuthGate";

export const metadata: Metadata = {
  title: "SealAPI Lead Research Engine",
  description: "Enterprise Lead Research, Enrichment & Prioritization Pipeline using Scrapling",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0a0d14] text-slate-100 min-h-screen flex antialiased">
        <AuthGate>
          <Sidebar />
          <div className="flex-1 flex flex-col min-w-0 min-h-screen">
            <Navbar />
            <main className="flex-1 p-8 overflow-y-auto">{children}</main>
          </div>
        </AuthGate>
      </body>
    </html>
  );
}
