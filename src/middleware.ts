import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname.startsWith("/api/")) {
    const isProduction =
      process.env.NODE_ENV === "production" ||
      process.env.APP_ENV === "production";
    const serverApiKey = process.env.API_SECRET_KEY || "";

    // Operator session check via HttpOnly cookie
    const sessionCookie = request.cookies.get("sealapi_session")?.value;
    const isSessionValid = Boolean(
      sessionCookie && serverApiKey && sessionCookie === serverApiKey
    );

    // Direct caller header check
    const clientKey = request.headers.get("x-api-key");
    const isClientKeyValid = Boolean(
      clientKey && serverApiKey && clientKey === serverApiKey
    );

    const isMutation = ["POST", "DELETE", "PUT", "PATCH"].includes(
      request.method
    );

    // Exclude auth endpoints from session gating
    if (pathname.startsWith("/api/auth/")) {
      return NextResponse.next();
    }

    // In production, unauthenticated mutation requests through the proxy must fail closed
    if (isMutation && isProduction && !isSessionValid && !isClientKeyValid) {
      return NextResponse.json(
        {
          detail:
            "Unauthorized: Operator authentication required for sensitive operations.",
        },
        { status: 401 }
      );
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
