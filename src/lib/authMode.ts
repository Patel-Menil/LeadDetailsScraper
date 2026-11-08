/**
 * Local single-user mode. When AUTH_DISABLED=true the dashboard skips the sign-in screen and the
 * API proxy stops requiring a session. Only for a machine you run yourself.
 */
export function isAuthDisabled(): boolean {
  const value = (process.env.AUTH_DISABLED || "").trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}
