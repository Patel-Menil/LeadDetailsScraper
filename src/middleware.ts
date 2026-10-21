import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getSessionSecret, verifySessionToken } from "@/lib/auth";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname.startsWith("/api/")) {
    // Exclude public endpoints: auth routes and public health check
    if (pathname.startsWith("/api/auth/") || pathname === "/api/health") {
      return NextResponse.next();
    }

    const isProduction =
      process.env.NODE_ENV === "production" ||
      process.env.APP_ENV === "production";
    const serverApiKey = process.env.API_SECRET_KEY || "";
    const sessionSecret = getSessionSecret();

    // Operator session check via HttpOnly cookie
    const sessionCookie = request.cookies.get("sealapi_session")?.value;
    const sessionResult = await verifySessionToken(sessionCookie, sessionSecret);
    const isSessionValid = sessionResult.valid;

    // Direct caller header check
    const clientKey = request.headers.get("x-api-key");
    const isClientKeyValid = Boolean(
      clientKey && serverApiKey && clientKey === serverApiKey
    );

    // In production, unauthenticated requests (reads and mutations) through the proxy must fail closed
    if (isProduction && !isSessionValid && !isClientKeyValid) {
      return NextResponse.json(
        {
          detail:
            "Unauthorized: Valid operator session or API key required.",
        },
        { status: 401 }
      );
    }

    // CSRF protection for cookie-authenticated mutation requests
    const isMutation = ["POST", "PUT", "DELETE", "PATCH"].includes(request.method);
    if (isMutation && isSessionValid && !isClientKeyValid) {
      const origin = request.headers.get("origin");
      const host = request.headers.get("host");
      const secFetchSite = request.headers.get("sec-fetch-site");
      if (secFetchSite && secFetchSite === "cross-site") {
        return NextResponse.json(
          { detail: "Forbidden: Cross-site request rejected." },
          { status: 403 }
        );
      }
      if (origin) {
        try {
          const originHost = new URL(origin).host;
          if (host && originHost !== host) {
            return NextResponse.json(
              { detail: "Forbidden: Origin mismatch." },
              { status: 403 }
            );
          }
        } catch {
          return NextResponse.json(
            { detail: "Forbidden: Invalid origin header." },
            { status: 403 }
          );
        }
      }
    }

    // Inject server-side API key when forwarding to backend if session is valid or in local dev
    const requestHeaders = new Headers(request.headers);
    if (serverApiKey && (isSessionValid || !isProduction)) {
      requestHeaders.set("x-api-key", serverApiKey);
    }

    return NextResponse.next({
      request: {
        headers: requestHeaders,
      },
    });
  }

  return NextResponse.next();
}

export const config = {
  matcher: "/api/:path*",
};
