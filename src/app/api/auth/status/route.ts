import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  const serverApiKey = process.env.API_SECRET_KEY || "";
  const isProduction =
    process.env.NODE_ENV === "production" ||
    process.env.APP_ENV === "production";

  if (!isProduction && !serverApiKey) {
    // In local development with no key set, permissive bypass
    return NextResponse.json({ authenticated: true, mode: "development" });
  }

  const sessionCookie = request.cookies.get("sealapi_session")?.value;
  const isAuthenticated = Boolean(
    sessionCookie && serverApiKey && sessionCookie === serverApiKey
  );

  return NextResponse.json({
    authenticated: isAuthenticated,
    mode: isProduction ? "production" : "development",
  });
}
