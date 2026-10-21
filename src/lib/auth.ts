export interface SessionPayload {
  role: string;
  iat: number;
  exp: number;
}

export function getSessionSecret(): string {
  return process.env.SESSION_SECRET || process.env.API_SECRET_KEY || "";
}

function base64UrlEncode(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function base64UrlDecode(str: string): Uint8Array {
  let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4) {
    base64 += "=";
  }
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/**
 * Creates a cryptographically signed, expiring session token using Web Crypto API.
 * 100% compliant with Next.js Edge Runtime and Node.js runtime.
 */
export async function createSessionToken(secret: string, maxAgeSeconds: number = 60 * 60 * 24 * 7): Promise<string> {
  if (!secret) {
    throw new Error("Cannot create session token: secret is required.");
  }

  const now = Math.floor(Date.now() / 1000);
  const payload: SessionPayload = {
    role: "operator",
    iat: now,
    exp: now + maxAgeSeconds,
  };

  const payloadJson = JSON.stringify(payload);
  const encoder = new TextEncoder();
  const payloadB64 = base64UrlEncode(encoder.encode(payloadJson));

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const sigBuf = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(payloadB64)
  );

  const signatureB64 = base64UrlEncode(sigBuf);
  return `${payloadB64}.${signatureB64}`;
}

/**
 * Verifies a signed session token using Web Crypto API.
 * Validates HMAC-SHA256 signature and expiration timestamp.
 */
export async function verifySessionToken(token: string | undefined | null, secret: string): Promise<{ valid: boolean; payload?: SessionPayload }> {
  if (!token || !secret) {
    return { valid: false };
  }

  const parts = token.split(".");
  if (parts.length !== 2) {
    return { valid: false };
  }

  const [payloadB64, signatureB64] = parts;

  try {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );

    const sigBytes = base64UrlDecode(signatureB64);
    const sigBuffer = sigBytes.buffer.slice(
      sigBytes.byteOffset,
      sigBytes.byteOffset + sigBytes.byteLength
    ) as ArrayBuffer;
    const validSig = await crypto.subtle.verify(
      "HMAC",
      key,
      sigBuffer,
      encoder.encode(payloadB64)
    );

    if (!validSig) {
      return { valid: false };
    }

    const payloadBytes = base64UrlDecode(payloadB64);
    const decoder = new TextDecoder();
    const payload: SessionPayload = JSON.parse(decoder.decode(payloadBytes));

    const now = Math.floor(Date.now() / 1000);
    if (!payload.exp || payload.exp <= now) {
      return { valid: false };
    }

    return { valid: true, payload };
  } catch {
    return { valid: false };
  }
}
