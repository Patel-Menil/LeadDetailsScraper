/**
 * Browser helpers for the operator session.
 *
 * The session lives only in the HttpOnly `sealapi_session` cookie set by
 * POST /api/auth/login. Nothing (key or token) is stored in localStorage,
 * sessionStorage or a script-readable cookie.
 *
 * Plain ESM JavaScript so the same code runs in Next.js and under `node --test`.
 */

/** Fired on `window` when any API call returns 401, so the app can show the login screen. */
export const UNAUTHORIZED_EVENT = "sealapi:unauthorized";

/**
 * Ask the server whether the current session cookie is valid.
 * @param {typeof fetch} [fetchImpl]
 * @returns {Promise<boolean>}
 */
export async function checkSession(fetchImpl = fetch) {
  const res = await fetchImpl("/api/auth/status", { credentials: "same-origin", cache: "no-store" });
  if (!res.ok) return false;
  const data = await res.json().catch(() => ({}));
  return data.authenticated === true;
}

/**
 * Sign in with the API secret key, then confirm the HttpOnly session cookie was accepted.
 * @param {string} key
 * @param {typeof fetch} [fetchImpl]
 * @returns {Promise<{ ok: true } | { ok: false, error: string }>}
 */
export async function login(key, fetchImpl = fetch) {
  let res;
  try {
    res = await fetchImpl("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ key }),
    });
  } catch {
    return { ok: false, error: "Could not reach the server. Check that it is running." };
  }

  if (res.status === 401) {
    return { ok: false, error: "Invalid API secret key." };
  }
  if (!res.ok) {
    // e.g. 500 when API_SECRET_KEY is not configured on the server.
    const data = await res.json().catch(() => ({}));
    return { ok: false, error: data.error || `Sign-in failed (HTTP ${res.status}).` };
  }

  // The cookie is not readable from script, so verify it with the server.
  if (!(await checkSession(fetchImpl).catch(() => false))) {
    return {
      ok: false,
      error: "Signed in, but the session could not be verified. Check that cookies are enabled for this site.",
    };
  }
  return { ok: true };
}

/**
 * Clear the session cookie.
 * @param {typeof fetch} [fetchImpl]
 * @returns {Promise<void>}
 */
export async function logout(fetchImpl = fetch) {
  await fetchImpl("/api/auth/logout", { method: "POST", credentials: "same-origin" });
}
