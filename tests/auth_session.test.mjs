import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { checkSession, login, logout, UNAUTHORIZED_EVENT } from "../src/lib/session.mjs";

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/**
 * Fake of the three Next.js auth routes. `session` stands in for the HttpOnly
 * cookie: login sets it, logout clears it, status reports it.
 */
function fakeServer({ apiKey = "correct-key", configured = true, cookiesWork = true } = {}) {
  const server = { session: false, calls: [] };
  server.fetch = async (url, init = {}) => {
    server.calls.push({ url, init });
    if (url === "/api/auth/login") {
      if (!configured) {
        return json(500, { error: "Server security configuration error: API_SECRET_KEY must be configured in production." });
      }
      const { key } = JSON.parse(init.body);
      if (key !== apiKey) return json(401, { error: "Invalid API secret key." });
      server.session = cookiesWork;
      return json(200, { success: true });
    }
    if (url === "/api/auth/status") return json(200, { authenticated: server.session, mode: "production" });
    if (url === "/api/auth/logout") {
      server.session = false;
      return json(200, { success: true });
    }
    return json(404, {});
  };
  return server;
}

describe("Operator login screen session helpers", () => {
  it("logs in with the correct key and verifies the session", async () => {
    const server = fakeServer();
    assert.deepEqual(await login("correct-key", server.fetch), { ok: true });

    const [loginCall, statusCall] = server.calls;
    assert.equal(loginCall.url, "/api/auth/login");
    assert.equal(loginCall.init.method, "POST");
    assert.equal(loginCall.init.credentials, "same-origin");
    assert.equal(loginCall.init.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(loginCall.init.body), { key: "correct-key" });
    assert.equal(statusCall.url, "/api/auth/status");
    assert.equal(statusCall.init.credentials, "same-origin");
  });

  it("rejects an invalid key with a clear error and no session", async () => {
    const server = fakeServer();
    assert.deepEqual(await login("wrong-key", server.fetch), { ok: false, error: "Invalid API secret key." });
    assert.equal(await checkSession(server.fetch), false);
  });

  it("shows the server's configuration error", async () => {
    const result = await login("anything", fakeServer({ configured: false }).fetch);
    assert.equal(result.ok, false);
    assert.match(result.error, /API_SECRET_KEY must be configured/);
  });

  it("fails when login succeeds but the session cookie is not accepted", async () => {
    const result = await login("correct-key", fakeServer({ cookiesWork: false }).fetch);
    assert.equal(result.ok, false);
    assert.match(result.error, /session could not be verified/);
  });

  it("reports an unreachable server", async () => {
    const result = await login("correct-key", async () => {
      throw new TypeError("fetch failed");
    });
    assert.equal(result.ok, false);
    assert.match(result.error, /Could not reach the server/);
  });

  it("checkSession only trusts an explicit authenticated: true", async () => {
    assert.equal(await checkSession(async () => json(200, { authenticated: true })), true);
    assert.equal(await checkSession(async () => json(200, { authenticated: "true" })), false);
    assert.equal(await checkSession(async () => json(200, {})), false);
    assert.equal(await checkSession(async () => json(500, { authenticated: true })), false);
    assert.equal(await checkSession(async () => new Response("not json", { status: 200 })), false);
  });

  it("logout clears the session", async () => {
    const server = fakeServer();
    await login("correct-key", server.fetch);
    assert.equal(await checkSession(server.fetch), true);

    await logout(server.fetch);
    const logoutCall = server.calls.find((c) => c.url === "/api/auth/logout");
    assert.equal(logoutCall.init.method, "POST");
    assert.equal(logoutCall.init.credentials, "same-origin");
    assert.equal(await checkSession(server.fetch), false);
  });

  it("exposes the event name the API client uses to request the login screen", () => {
    assert.equal(UNAUTHORIZED_EVENT, "sealapi:unauthorized");
    const apiClient = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
    assert.match(apiClient, /notifyUnauthorized\(response\.status\)/);
  });

  it("frontend code never stores the key or session in browser-readable storage", () => {
    const files = [];
    const walk = (dir) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.(ts|tsx|mjs|js)$/.test(name)) files.push(path);
      }
    };
    walk(fileURLToPath(new URL("../src", import.meta.url)));
    const offenders = files.filter((f) => !f.includes("lead_research") &&
      /(localStorage|sessionStorage)\s*\.|document\.cookie/.test(readFileSync(f, "utf8")));
    assert.deepEqual(offenders, []);
  });
});
