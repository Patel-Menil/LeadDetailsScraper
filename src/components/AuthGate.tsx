"use client";

import React, { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { checkSession, login, UNAUTHORIZED_EVENT } from "@/lib/session.mjs";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

type GateState = "checking" | "authenticated" | "login";

/** Shows the app only with a valid operator session; otherwise shows the login screen. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<GateState>("checking");

  useEffect(() => {
    checkSession()
      .then((ok) => setState(ok ? "authenticated" : "login"))
      .catch(() => setState("login"));

    const onUnauthorized = () => setState("login");
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (state === "checking") {
    return <div className="flex-1 flex items-center justify-center text-sm text-slate-400">Checking session…</div>;
  }
  if (state === "login") {
    // Reload so the current page refetches its data with the new session.
    return <LoginScreen onSuccess={() => window.location.reload()} />;
  }
  return <>{children}</>;
}

function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await login(key);
    if (result.ok) {
      onSuccess();
      return;
    }
    setError(result.error);
    setSubmitting(false);
  };

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardContent className="p-6 space-y-5">
          <div className="space-y-1 text-center">
            <div className="mx-auto w-10 h-10 rounded-full bg-blue-600/15 border border-blue-500/30 flex items-center justify-center">
              <Lock className="w-5 h-5 text-blue-400" />
            </div>
            <h1 className="text-lg font-semibold text-white">Sign in</h1>
            <p className="text-sm text-slate-400">SealAPI Lead Research Engine</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="api-key" className="text-sm font-medium text-slate-300">
                API secret key
              </label>
              <input
                id="api-key"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={key}
                onChange={(e) => setKey(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-[#0a0d14] px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              />
            </div>

            {error && (
              <p role="alert" className="text-sm text-rose-400">
                {error}
              </p>
            )}

            <Button type="submit" className="w-full" isLoading={submitting} disabled={!key}>
              Sign in
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
