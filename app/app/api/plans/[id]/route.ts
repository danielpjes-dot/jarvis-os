import { NextRequest, NextResponse } from "next/server";

const JARVIS = process.env.JARVIS_URL || "http://127.0.0.1:7900";

export const dynamic = "force-dynamic";

// GET /api/plans/[id] — step statuses
export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const res = await fetch(
      `${JARVIS}/api/plan-status?plan_id=${encodeURIComponent(params.id)}`,
      { signal: AbortSignal.timeout(5000) }
    );
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Unreachable" }, { status: 502 });
  }
}

// POST /api/plans/[id] — approve (copy tested → approved)
export async function POST(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const res = await fetch(`${JARVIS}/api/plans/${params.id}/approve`, {
      method: "POST",
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Unreachable" }, { status: 502 });
  }
}
