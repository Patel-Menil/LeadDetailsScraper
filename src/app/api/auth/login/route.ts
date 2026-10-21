import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { key } = body;
    const serverApiKey = process.env.API_SECRET_KEY || "";
    const isProduction =
      process.env.NODE_ENV === "production" ||
      process.env.APP_ENV === "production";

    if (isProduction && !serverApiKey) {
      return NextResponse.json(
        {
          error:
            "Server security configuration error: API_SECRET_KEY must be configured in production.",
        },
        { status: 500 }
      );
    }

    if (!key || key !== serverApiKey) {
      return NextResponse.json(
        { error: "Invalid API secret key." },
        { status: 401 }
      );
    }

    const response = NextResponse.json({
      success: true,
      message: "Authenticated successfully.",
    });

    response.cookies.set("sealapi_session", serverApiKey, {
      httpOnly: true,
      secure: isProduction,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    return response;
  } catch {
    return NextResponse.json(
      { error: "Invalid request payload." },
      { status: 400 }
    );
  }
}
