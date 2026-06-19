import { NextResponse } from "next/server";

const JARVIS = process.env.JARVIS_URL || "http://127.0.0.1:7900";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await fetch(`${JARVIS}/api/plans`, {
      signal: AbortSignal.timeout(5000),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ plans: [] });
  }
}
