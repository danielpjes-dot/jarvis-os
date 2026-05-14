import { NextResponse } from "next/server";

export async function GET() {
  try {
    const res = await fetch("http://127.0.0.1:11434/api/ps", {
      cache: "no-store",
    });

    if (!res.ok) {
      return NextResponse.json({
        ok: false,
        brain: "unknown",
        model: null,
        error: `Ollama ps failed: ${res.status}`,
      });
    }

    const data = await res.json();
    const models = data.models || [];

    const active =
      models.find((m: any) => String(m.name || "").includes("coder")) ||
      models[0] ||
      null;

    const modelName = active?.name || active?.model || null;

    let brain = "unknown";

    if (modelName?.includes("qwen3-coder")) brain = "ollama_code";
    else if (modelName?.includes("qwen3:8b")) brain = "ollama_fast";
    else if (modelName?.includes("qwen3:14b")) brain = "ollama_reason";
    else if (modelName?.includes("gemma")) brain = "ollama_deep";

    return NextResponse.json({
      ok: true,
      brain,
      model: modelName,
      models,
    });
  } catch (err) {
    return NextResponse.json({
      ok: false,
      brain: "unknown",
      model: null,
      error: String(err),
    });
  }
}