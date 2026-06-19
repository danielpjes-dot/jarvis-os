import { NextRequest, NextResponse } from "next/server";

const JARVIS = process.env.JARVIS_URL || "http://127.0.0.1:7900";

export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  const { searchParams } = new URL(req.url);
  const file  = searchParams.get("file")  || "";
  const stage = searchParams.get("stage") || "dev";

  try {
    const res = await fetch(
      `${JARVIS}/api/plans/${params.id}/read?file=${encodeURIComponent(file)}&stage=${stage}`,
      { signal: AbortSignal.timeout(10000) }
    );
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Unreachable" }, { status: 502 });
  }
}
