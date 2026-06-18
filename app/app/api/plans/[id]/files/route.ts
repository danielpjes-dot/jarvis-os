import { NextRequest, NextResponse } from "next/server";

const JARVIS = process.env.JARVIS_URL || "http://127.0.0.1:7900";

export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const res = await fetch(`${JARVIS}/api/plans/${params.id}/files`, {
      signal: AbortSignal.timeout(5000),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ dev: [], tested: [], approved: [] });
  }
}
