"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { HudPanel } from "./hud-panel";

const HEADER_OFFSET_PX = 172;

interface PlanSummary {
  plan_id: string;
  summary?: string;
  goal?: string;
  total: number;
  done: number;
  failed: number;
  has_dev: boolean;
  has_tested: boolean;
  has_approved: boolean;
}

interface PlanStep {
  task_id: number;
  task: string;
  status: string;
  result?: string | null;
}

const JARVIS_FILES = [
  "scripts/react_server.py",
  "scripts/plan_runner.py",
  "skills/coding_qwen3_coder.py",
  "app/page.tsx",
  "config/models-config.json",
];

export function CodingWorkspace({ projectDir }: { projectDir?: string }) {
  const rootDir = projectDir || "/mnt/e/coding/jarvis-os";

  // Layout
  const [leftWidth,       setLeftWidth]      = useState(300);
  const [rightWidth,      setRightWidth]     = useState(320);
  const [terminalHeight,  setTerminalHeight] = useState(220);
  const [showFiles,       setShowFiles]      = useState(true);
  const [showRight,       setShowRight]      = useState(true);
  const [showTerminal,    setShowTerminal]   = useState(true);
  const [agentExpanded,   setAgentExpanded]  = useState(false);
  const dragRef = useRef<"left" | "right" | "terminal" | null>(null);

  // Editor / agent
  const [activeFile,    setActiveFile]   = useState<string | null>(null);
  const [editorText,    setEditorText]   = useState("");
  const [agentInput,    setAgentInput]   = useState("");
  const [agentLog,      setAgentLog]     = useState("");
  const [coderHistory,  setCoderHistory] = useState("");
  const coderHistoryEndRef = useRef<HTMLDivElement | null>(null);

  // Terminal / PTY
  const [terminalOutput, setTerminalOutput] = useState("");
  const [terminalInput,  setTerminalInput]  = useState("");
  const [ptyConnected,   setPtyConnected]   = useState(false);
  const wsRef         = useRef<WebSocket | null>(null);
  const terminalEndRef = useRef<HTMLDivElement | null>(null);

  // Plan picker
  const [plans,        setPlans]       = useState<PlanSummary[]>([]);
  const [activePlan,   setActivePlan]  = useState<string | null>(null);
  const [planSteps,    setPlanSteps]   = useState<PlanStep[]>([]);
  const [stagingFiles, setStagingFiles]= useState<{ dev: string[]; tested: string[]; approved: string[] }>({ dev: [], tested: [], approved: [] });
  const [approving,    setApproving]   = useState(false);
  const [activeStage,  setActiveStage] = useState<"dev" | "tested" | "approved">("dev");

  // ── Drag resize ────────────────────────────────────────────────────────────
  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragRef.current) return;
      if (dragRef.current === "left")
        setLeftWidth(Math.max(220, Math.min(600, e.clientX - 250)));
      if (dragRef.current === "right")
        setRightWidth(Math.max(220, Math.min(600, window.innerWidth - e.clientX - 15)));
      if (dragRef.current === "terminal")
        setTerminalHeight(Math.max(120, Math.min(420, window.innerHeight - e.clientY - 20)));
    }
    function onUp() {
      dragRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  function startDrag(side: "left" | "right" | "terminal") {
    dragRef.current = side;
    document.body.style.cursor = side === "terminal" ? "row-resize" : "col-resize";
    document.body.style.userSelect = "none";
  }

  // ── Agent log polling ──────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const res  = await fetch("http://127.0.0.1:7900/api/coding-log");
        const data = await res.json();
        if (!alive) return;
        const lines = (data.events || []).map((e: any) => {
          const d = e.data || {};
          return `[${e.time || ""}] ${(e.type || "").toUpperCase()} ${e.message || ""}${d.route ? ` route=${d.route}` : ""}${d.model ? ` model=${d.model}` : ""}${d.iteration ? ` iter=${d.iteration}` : ""}`;
        });
        setAgentLog(lines.join("\n"));
      } catch {}
    }
    poll();
    const t = setInterval(poll, 1500);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // ── Plan list polling ──────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    async function pollPlans() {
      try {
        const res  = await fetch("/api/plans");
        const data = await res.json();
        if (!alive) return;
        setPlans(data.plans || []);
      } catch {}
    }
    pollPlans();
    const t = setInterval(pollPlans, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // ── Active plan step + file polling ───────────────────────────────────────
  const pollActivePlan = useCallback(async (pid: string) => {
    try {
      const [stepsRes, filesRes] = await Promise.all([
        fetch(`/api/plans/${pid}`),
        fetch(`/api/plans/${pid}/files`),
      ]);
      const stepsData = await stepsRes.json();
      const filesData = await filesRes.json();
      setPlanSteps(stepsData.tasks || []);
      setStagingFiles({ dev: filesData.dev || [], tested: filesData.tested || [], approved: filesData.approved || [] });
    } catch {}
  }, []);

  useEffect(() => {
    if (!activePlan) {
      setPlanSteps([]);
      setStagingFiles({ dev: [], tested: [], approved: [] });
      return;
    }
    pollActivePlan(activePlan);
    const t = setInterval(() => pollActivePlan(activePlan), 4000);
    return () => clearInterval(t);
  }, [activePlan, pollActivePlan]);

  // ── PTY WebSocket ──────────────────────────────────────────────────────────
  useEffect(() => {
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket("ws://localhost:4010");
      wsRef.current = ws;
      ws.onopen    = () => { setPtyConnected(true);  setTerminalOutput(p => p + "[PTY connected]\n"); ws?.send(JSON.stringify({ type: "cwd", cwd: rootDir })); };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if      (msg.type === "output") setTerminalOutput(p => (p + msg.data).slice(-30000));
          else if (msg.type === "exit")   { setTerminalOutput(p => p + `\n[PTY exited: ${msg.code}]\n`); setPtyConnected(false); }
          else if (msg.type === "error")  setTerminalOutput(p => p + `\n[PTY error: ${msg.error}]\n`);
        } catch { setTerminalOutput(p => (p + String(ev.data)).slice(-30000)); }
      };
      ws.onerror = () => { setTerminalOutput(p => p + "[PTY error]\n"); setPtyConnected(false); };
      ws.onclose = () => { setTerminalOutput(p => p + "[PTY disconnected]\n"); setPtyConnected(false); };
    } catch { setTerminalOutput(p => p + "[PTY unavailable]\n"); }
    return () => { ws?.close(); wsRef.current = null; };
  }, [rootDir]);

  useEffect(() => { terminalEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [terminalOutput]);
  useEffect(() => { coderHistoryEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [coderHistory]);

  // ── Helpers ────────────────────────────────────────────────────────────────
  function isPlanMessage(text: string) {
    return text.includes("PLAN_ID:") && text.includes("WAITING_FOR:");
  }
  function extractPlanId(text: string) {
    return text.match(/PLAN_ID:\s*([a-zA-Z0-9_-]+)/)?.[1] ?? null;
  }
  function appendCoderHistory(title: string, content: string) {
    const time = new Date().toLocaleTimeString();
    setCoderHistory(prev =>
      [prev, `\n\n━━━━ [${time}] ${title} ━━━━`, content || "(empty)"]
        .filter(Boolean).join("\n").slice(-80000)
    );
  }
  function stepIcon(status: string) {
    if (status === "done")    return "✓";
    if (status === "failed")  return "✗";
    if (status === "running") return "…";
    return "·";
  }
  function stepColor(status: string) {
    if (status === "done")    return "text-green-400/80";
    if (status === "failed")  return "text-red-400/80";
    if (status === "running") return "text-yellow-400 animate-pulse";
    return "text-white/30";
  }

  // ── Send to coding agent ───────────────────────────────────────────────────
  async function sendAgentText(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    appendCoderHistory("USER", trimmed);
    setEditorText("Running coder...\n");
    setAgentInput("");
    setActiveFile(null);
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10 * 60 * 1000);
      const res = await fetch("http://127.0.0.1:7900/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          source: "codex_ui",
          route: "code",
          model: "qwen3-coder:30b",
          messages: [{ role: "user", content: trimmed }],
        }),
      });
      clearTimeout(timeout);
      const data = await res.json();
      const content = data?.message?.content || data?.error || JSON.stringify(data, null, 2);
      appendCoderHistory("CODER", content);
      setEditorText(content);
    } catch (err) {
      const e = `Error: ${String(err)}`;
      appendCoderHistory("ERROR", e);
      setEditorText(e);
    }
  }

  // ── Open file from jarvis-os or staging ───────────────────────────────────
  async function openJarvisFile(relPath: string) {
    setActiveFile(relPath);
    setEditorText(`Loading ${relPath}…`);
    try {
      const res  = await fetch("http://127.0.0.1:7900/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "codex_ui", route: "code", model: "qwen3-coder:30b",
          messages: [{ role: "user", content: `Read ${relPath} and return only the file content.` }] }),
      });
      const data = await res.json();
      setEditorText(data?.message?.content || JSON.stringify(data, null, 2));
    } catch (err) { setEditorText(`Failed: ${String(err)}`); }
  }

  async function openStagingFile(relPath: string, stage: "dev" | "tested" | "approved") {
    if (!activePlan) return;
    setActiveFile(`${stage}/${relPath}`);
    setEditorText(`Loading ${stage}/${relPath}…`);
    try {
      const res  = await fetch(`/api/plans/${activePlan}/read?file=${encodeURIComponent(relPath)}&stage=${stage}`);
      const data = await res.json();
      setEditorText(data?.content ?? data?.error ?? "");
    } catch (err) { setEditorText(`Failed: ${String(err)}`); }
  }

  // ── Approve plan ───────────────────────────────────────────────────────────
  async function approvePlan() {
    if (!activePlan || approving) return;
    setApproving(true);
    try {
      const res  = await fetch(`/api/plans/${activePlan}`, { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        appendCoderHistory("APPROVED", `Plan ${activePlan} promoted to staging/approved/`);
        pollActivePlan(activePlan);
      } else {
        appendCoderHistory("APPROVE ERROR", data.error || "Unknown error");
      }
    } catch (err) { appendCoderHistory("APPROVE ERROR", String(err)); }
    setApproving(false);
  }

  // ── Terminal send ──────────────────────────────────────────────────────────
  function sendTerminalInput() {
    if (!terminalInput.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "input", data: terminalInput + "\n" }));
    setTerminalInput("");
  }

  // ── Active plan summary ────────────────────────────────────────────────────
  const activePlanSummary = plans.find(p => p.plan_id === activePlan);
  const currentFiles      = activePlan ? stagingFiles[activeStage] : JARVIS_FILES;
  const gridColumns = showRight
    ? `${leftWidth}px 6px minmax(0,1fr) 6px ${rightWidth}px`
    : `${leftWidth}px 6px minmax(0,1fr)`;
  const gridRows = showTerminal ? `minmax(0,1fr) 6px ${terminalHeight}px` : "minmax(0,1fr)";

  return (
    <div
      className="w-full min-h-0 flex flex-col gap-2 overflow-hidden"
      style={{ height: `calc(100dvh - ${HEADER_OFFSET_PX}px)` }}
    >
      {/* ── Toolbar ── */}
      <div className="flex items-center gap-2 px-1 shrink-0 flex-wrap">
        {/* Plan picker */}
        <select
          value={activePlan ?? ""}
          onChange={e => { setActivePlan(e.target.value || null); setActiveFile(null); setEditorText(""); }}
          className="text-[9px] uppercase tracking-[1px] bg-black/40 border border-white/10 text-white/60 px-2 py-1 rounded-sm outline-none hover:border-[var(--accent)]/40 max-w-[260px]"
        >
          <option value="">— JARVIS OS (no plan) —</option>
          {plans.map(p => (
            <option key={p.plan_id} value={p.plan_id}>
              {p.plan_id} · {p.done}/{p.total} {p.has_approved ? "✓approved" : p.has_tested ? "tested" : "dev"}
            </option>
          ))}
        </select>

        {/* Stage selector (only when plan active) */}
        {activePlan && (
          <div className="flex gap-1">
            {(["dev", "tested", "approved"] as const).map(s => (
              <button
                key={s}
                onClick={() => setActiveStage(s)}
                className={`text-[8px] uppercase tracking-[2px] px-2 py-1 border rounded-sm transition-all ${
                  activeStage === s
                    ? "border-[var(--accent)]/60 text-[var(--accent)] bg-[var(--accent)]/10"
                    : "border-white/10 text-white/40 hover:text-[var(--accent)]"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        )}

        <button onClick={() => setShowFiles(v => !v)}    className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">{showFiles    ? "HIDE FILES" : "SHOW FILES"}</button>
        <button onClick={() => setShowTerminal(v => !v)} className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">{showTerminal ? "HIDE TERM"  : "SHOW TERM"}</button>
        <button onClick={() => setShowRight(v => !v)}    className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">{showRight    ? "HIDE SIDE" : "SHOW SIDE"}</button>
        <button onClick={() => setAgentExpanded(v => !v)} className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">{agentExpanded ? "NORMAL" : "EXPAND AGENT"}</button>
      </div>

      {/* ── Main grid ── */}
      <div
        className="flex-1 min-h-0 grid gap-3 overflow-hidden"
        style={{
          gridTemplateColumns: agentExpanded ? "minmax(0,1fr)" : gridColumns,
          gridTemplateRows:    agentExpanded ? "minmax(0,1fr)" : gridRows,
        }}
      >
        {/* LEFT — Agent command + log */}
        <HudPanel
          title="AGENT COMMAND"
          className={`${agentExpanded ? "col-start-1 row-start-1" : "col-start-1 row-start-1 row-span-3"} h-full min-h-0 overflow-hidden`}
        >
          <div className="p-3 h-full min-h-0 flex flex-col gap-3">
            <textarea
              value={agentInput}
              onChange={e => setAgentInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendAgentText(agentInput); }}
              className="h-28 shrink-0 bg-black/30 border border-white/[0.08] rounded-sm p-2 text-[11px] text-white/80 outline-none resize-none select-text"
              placeholder="Write coder command… Ctrl+Enter to send"
            />
            <button
              onClick={() => sendAgentText(agentInput)}
              className="shrink-0 text-[8px] tracking-[2px] uppercase px-3 py-2 rounded-sm bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/20"
            >
              SEND TO CODE MODEL
            </button>

            <div className="shrink-0 flex items-center justify-between text-[8px] uppercase tracking-[2px] text-white/30">
              <span>Agent logs</span><span>live</span>
            </div>
            <pre className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden font-mono text-[10px] leading-relaxed text-cyan-300/70 select-text bg-black/20 p-2 rounded-sm whitespace-pre-wrap break-words">
              {agentLog || "Waiting for coding loop events…\n"}
            </pre>
          </div>
        </HudPanel>

        {!agentExpanded && (
          <>
            <div className="col-start-2 row-start-1 row-span-3 cursor-col-resize bg-[var(--accent)]/10 hover:bg-[var(--accent)]/40 transition-colors rounded-sm h-full min-h-0" onMouseDown={() => startDrag("left")} />

            {/* CENTER — Editor / coder output */}
            <HudPanel title={activeFile || "EDITOR / CODER OUTPUT"} className="col-start-3 row-start-1 h-full min-h-0 overflow-hidden">
              <div className="p-3 h-full min-h-0 flex flex-col gap-3 text-[10px] select-text">
                {/* Plan action buttons (shown when response contains a plan) */}
                {isPlanMessage(editorText) && (
                  <div className="shrink-0 flex flex-col gap-2">
                    <div className="text-[8px] uppercase tracking-[2px] text-white/35">
                      Plan {extractPlanId(editorText) ?? ""}
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => sendAgentText(`proceed ${extractPlanId(editorText) ?? ""}`)} className="flex-1 px-3 py-2 rounded-sm bg-green-600/20 border border-green-500/40 text-green-300 hover:bg-green-600/30">Accept</button>
                      <button onClick={() => setAgentInput(`modify plan ${extractPlanId(editorText) ?? ""}:\n\n`)} className="flex-1 px-3 py-2 rounded-sm bg-yellow-600/20 border border-yellow-500/40 text-yellow-300 hover:bg-yellow-600/30">Modify</button>
                      <button onClick={() => sendAgentText("cancel")} className="flex-1 px-3 py-2 rounded-sm bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30">Cancel</button>
                    </div>
                  </div>
                )}

                <div className="shrink-0 flex items-center justify-between text-[8px] uppercase tracking-[2px] text-white/30">
                  <span>Output history</span>
                  <button onClick={() => setCoderHistory("")} className="text-white/35 hover:text-red-300">CLEAR</button>
                </div>
                <pre className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden font-mono text-[10px] leading-relaxed text-white/60 select-text bg-black/20 p-2 rounded-sm whitespace-pre-wrap break-words">
                  {coderHistory || "No coder output yet.\n"}
                  <div ref={coderHistoryEndRef} />
                </pre>
              </div>
            </HudPanel>

            {/* TERMINAL */}
            {showTerminal && (
              <>
                <div className="col-start-3 row-start-2 cursor-row-resize bg-[var(--accent)]/10 hover:bg-[var(--accent)]/40 transition-colors rounded-sm" onMouseDown={() => startDrag("terminal")} />
                <HudPanel title={ptyConnected ? "TERMINAL · CONNECTED" : "TERMINAL · OFFLINE"} className="col-start-3 row-start-3 h-full min-h-0 overflow-hidden">
                  <div className="p-3 h-full min-h-0 flex flex-col gap-2">
                    <pre className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden font-mono text-[10px] text-green-400/70 whitespace-pre-wrap break-words select-text bg-black/20 p-2 rounded-sm">
                      {terminalOutput || "Connecting to PTY on ws://localhost:4010…\n"}
                      <div ref={terminalEndRef} />
                    </pre>
                    <div className="shrink-0 flex gap-2">
                      <input
                        value={terminalInput}
                        onChange={e => setTerminalInput(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") sendTerminalInput(); }}
                        className="flex-1 bg-black/30 border border-white/[0.08] rounded-sm p-2 text-[10px] font-mono text-white/70 outline-none select-text"
                        placeholder="terminal command…"
                      />
                      <button onClick={sendTerminalInput} className="text-[8px] tracking-[2px] uppercase px-3 rounded-sm bg-green-400/10 border border-green-400/30 text-green-400/80 hover:bg-green-400/20">RUN</button>
                    </div>
                  </div>
                </HudPanel>
              </>
            )}

            {/* RIGHT — Files + Actions */}
            {showRight && (
              <>
                <div className="col-start-4 row-start-1 row-span-3 cursor-col-resize bg-[var(--accent)]/10 hover:bg-[var(--accent)]/40 transition-colors rounded-sm" onMouseDown={() => startDrag("right")} />

                <div className="col-start-5 row-start-1 row-span-3 grid grid-rows-[1fr_auto] gap-3 min-h-0 h-full overflow-hidden">
                  {/* File browser */}
                  {showFiles && (
                    <HudPanel title={activePlan ? `FILES · ${activePlan}` : "FILES · JARVIS OS"} className="min-h-0 overflow-hidden">
                      <div className="p-3 h-full min-h-0 overflow-y-auto select-text">
                        <div className="text-[8px] uppercase tracking-[2px] opacity-30 mb-2 break-all">
                          {activePlan ? `staging/${activeStage}/${activePlan}/` : rootDir}
                        </div>
                        <div className="space-y-0.5">
                          {activePlan
                            ? currentFiles.map(f => (
                              <button
                                key={f}
                                onClick={() => openStagingFile(f, activeStage)}
                                className={`block w-full text-left text-[10px] px-2 py-1 rounded-sm transition-all break-all ${
                                  activeFile === `${activeStage}/${f}`
                                    ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                                    : "text-white/40 hover:text-[var(--accent)] hover:bg-white/[0.03]"
                                }`}
                              >{f}</button>
                            ))
                            : JARVIS_FILES.map(f => (
                              <button
                                key={f}
                                onClick={() => openJarvisFile(f)}
                                className={`block w-full text-left text-[10px] px-2 py-1 rounded-sm transition-all break-all ${
                                  activeFile === f
                                    ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                                    : "text-white/40 hover:text-[var(--accent)] hover:bg-white/[0.03]"
                                }`}
                              >{f}</button>
                            ))
                          }
                          {activePlan && currentFiles.length === 0 && (
                            <div className="text-[9px] text-white/20 px-2 py-1">No files in {activeStage} yet</div>
                          )}
                        </div>
                      </div>
                    </HudPanel>
                  )}

                  {/* Actions panel */}
                  <HudPanel title="ACTIONS" className="overflow-hidden shrink-0">
                    <div className="p-3 text-[10px] select-text flex flex-col gap-2 max-h-72 overflow-y-auto">
                      {activePlan ? (
                        <>
                          {/* Plan summary */}
                          <div className="text-[8px] uppercase tracking-[2px] text-white/35 mb-1">
                            {activePlanSummary?.summary || activePlan}
                          </div>

                          {/* Step list */}
                          <div className="space-y-0.5 mb-2">
                            {planSteps.map(s => (
                              <div key={s.task_id} className={`flex gap-2 font-mono text-[9px] ${stepColor(s.status)}`}>
                                <span className="shrink-0">{stepIcon(s.status)} {s.task_id}.</span>
                                <span className="break-words">{s.task}</span>
                              </div>
                            ))}
                            {planSteps.length === 0 && <div className="text-white/20 text-[9px]">Loading steps…</div>}
                          </div>

                          {/* Approve button */}
                          {activePlanSummary?.has_tested && !activePlanSummary?.has_approved && (
                            <button
                              onClick={approvePlan}
                              disabled={approving}
                              className="w-full px-3 py-2 rounded-sm bg-green-600/20 border border-green-500/40 text-green-300 hover:bg-green-600/30 disabled:opacity-40 text-[9px] uppercase tracking-[2px]"
                            >
                              {approving ? "APPROVING…" : "APPROVE → PRODUCTION"}
                            </button>
                          )}
                          {activePlanSummary?.has_approved && (
                            <div className="text-green-400/70 text-[9px] uppercase tracking-[2px]">✓ Approved</div>
                          )}

                          {/* Proceed (re-run) */}
                          <button
                            onClick={() => sendAgentText(`proceed ${activePlan}`)}
                            className="w-full px-3 py-2 rounded-sm bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/20 text-[9px] uppercase tracking-[2px]"
                          >
                            PROCEED / RE-RUN
                          </button>
                        </>
                      ) : (
                        <>
                          {isPlanMessage(editorText) ? (
                            <div className="flex flex-col gap-2">
                              <div className="text-[8px] uppercase tracking-[2px] text-white/35">Plan detected · {extractPlanId(editorText)}</div>
                              <button onClick={() => sendAgentText(`proceed ${extractPlanId(editorText) ?? ""}`)} className="px-3 py-2 rounded-sm bg-green-600/20 border border-green-500/40 text-green-300 hover:bg-green-600/30">Accept / Proceed</button>
                              <button onClick={() => setAgentInput(`modify plan ${extractPlanId(editorText) ?? ""}:\n\n`)} className="px-3 py-2 rounded-sm bg-yellow-600/20 border border-yellow-500/40 text-yellow-300 hover:bg-yellow-600/30">Modify Plan</button>
                              <button onClick={() => sendAgentText("cancel")} className="px-3 py-2 rounded-sm bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30">Cancel</button>
                            </div>
                          ) : (
                            <div className="text-white/25">Select a plan above to see its steps and approve it.</div>
                          )}
                        </>
                      )}
                    </div>
                  </HudPanel>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
