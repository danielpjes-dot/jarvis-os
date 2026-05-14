"use client";

import { useEffect, useRef, useState } from "react";
import { HudPanel } from "./hud-panel";


const HEADER_OFFSET_PX = 172;

export function CodingWorkspace({ projectDir }: { projectDir?: string }) {
  const rootDir = projectDir || "/mnt/e/coding/jarvis-os";

  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [editorText, setEditorText] = useState("");
  const [agentInput, setAgentInput] = useState("");
  const [agentLog, setAgentLog] = useState("");
  const [coderHistory, setCoderHistory] = useState("");
  const coderHistoryEndRef = useRef<HTMLDivElement | null>(null);
  const [terminalOutput, setTerminalOutput] = useState("");
  const [terminalInput, setTerminalInput] = useState("");
  const [ptyConnected, setPtyConnected] = useState(false);

  const [leftWidth, setLeftWidth] = useState(420);
  const [rightWidth, setRightWidth] = useState(300);
  const [terminalHeight, setTerminalHeight] = useState(220);

  const [showFiles, setShowFiles] = useState(true);
  const [showRight, setShowRight] = useState(true);
  const [showTerminal, setShowTerminal] = useState(true);
  const [agentExpanded, setAgentExpanded] = useState(false);

  const dragRef = useRef<"left" | "right" | "terminal" | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const terminalEndRef = useRef<HTMLDivElement | null>(null);

  const files = [
    "scripts/react_server.py",
    "scripts/watcher.py",
    "skills/coding_qwen3_coder.py",
    "app/page.tsx",
    "config/models-config.json",
  ];

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragRef.current) return;

      if (dragRef.current === "left") {
        setLeftWidth(Math.max(300, Math.min(720, e.clientX - 250)));
      }

      if (dragRef.current === "right") {
        setRightWidth(
          Math.max(220, Math.min(600, window.innerWidth - e.clientX - 15))
        );
      }

      if (dragRef.current === "terminal") {
        setTerminalHeight(
          Math.max(120, Math.min(420, window.innerHeight - e.clientY - 20))
        );
      }
    }

    function onUp() {
      dragRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);

    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  useEffect(() => {
    let alive = true;

    async function pollCodingLog() {
      try {
        const res = await fetch("http://127.0.0.1:7900/api/coding-log");
        const data = await res.json();

        if (!alive) return;

        const lines = (data.events || []).map((e: any) => {
          const time = e.time || "";
          const type = e.type || "event";
          const msg = e.message || "";
          const d = e.data || {};
          const model = d.model || d.resolved_model || "";
          const route = d.route || d.resolved_route || "";
          const iter = d.iteration ? ` iter=${d.iteration}` : "";
          const tools = d.tools?.length ? ` tools=${d.tools.join(",")}` : "";

          return `[${time}] ${type.toUpperCase()} ${msg}${
            route ? ` route=${route}` : ""
          }${model ? ` model=${model}` : ""}${iter}${tools}`;
        });

        setAgentLog(lines.join("\n"));
      } catch {}
    }

    pollCodingLog();
    const timer = setInterval(pollCodingLog, 1000);

    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;

    try {
      ws = new WebSocket("ws://localhost:4010");
      wsRef.current = ws;

      ws.onopen = () => {
        setPtyConnected(true);
        setTerminalOutput((prev) => prev + "[PTY connected]\n");
        ws?.send(JSON.stringify({ type: "cwd", cwd: rootDir }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === "output") {
            setTerminalOutput((prev) => (prev + msg.data).slice(-30000));
          } else if (msg.type === "exit") {
            setTerminalOutput((prev) => prev + `\n[PTY exited: ${msg.code}]\n`);
            setPtyConnected(false);
          } else if (msg.type === "error") {
            setTerminalOutput((prev) => prev + `\n[PTY error: ${msg.error}]\n`);
          }
        } catch {
          setTerminalOutput((prev) => (prev + String(event.data)).slice(-30000));
        }
      };

      ws.onerror = () => {
        setTerminalOutput((prev) => prev + "[PTY connection error]\n");
        setPtyConnected(false);
      };

      ws.onclose = () => {
        setTerminalOutput((prev) => prev + "[PTY disconnected]\n");
        setPtyConnected(false);
      };
    } catch {
      setTerminalOutput((prev) => prev + "[PTY unavailable]\n");
      setPtyConnected(false);
    }

    return () => {
      ws?.close();
      wsRef.current = null;
    };
  }, [rootDir]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [terminalOutput]);
  useEffect(() => {
    coderHistoryEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [coderHistory]);
function isPlanMessage(text: string) {
  return text.includes("PLAN_ID:") && text.includes("WAITING_FOR:");
}
function appendCoderHistory(title: string, content: string) {
  const time = new Date().toLocaleTimeString();

  setCoderHistory((prev) =>
    [
      prev,
      `\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
      `[${time}] ${title}`,
      `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
      content || "(empty response)",
    ]
      .filter(Boolean)
      .join("\n")
      .slice(-80000)
  );
}

function summarizeCoderOutput(text: string) {
  if (!text) return "No output.";

  if (isPlanMessage(text)) {
    return "Plan created. Waiting for Accept / Proceed.";
  }

  if (text.includes("APPLY FAILED")) {
    return "Patch was generated but apply failed.";
  }

  if (text.includes("--- FILE:")) {
    const files = [...text.matchAll(/--- FILE:\s*(.+)/g)].map((m) => m[1].trim());
    return files.length
      ? `Patch returned for: ${files.slice(0, 5).join(", ")}`
      : "Patch returned.";
  }

  if (text.toLowerCase().includes("step") && text.toLowerCase().includes("complete")) {
    return text.split("\n").slice(0, 8).join("\n");
  }

  return text.split("\n").slice(0, 10).join("\n");
}
function extractPlanId(text: string) {
  const match = text.match(/PLAN_ID:\s*([a-zA-Z0-9_-]+)/);
  return match?.[1] ?? null;
}
  function startDrag(side: "left" | "right" | "terminal") {
    dragRef.current = side;
    document.body.style.cursor =
      side === "terminal" ? "row-resize" : "col-resize";
    document.body.style.userSelect = "none";
  }
async function sendAgentText(text: string) {
  const trimmed = text.trim();
  if (!trimmed) return;

  appendCoderHistory("USER COMMAND", trimmed);

  setEditorText((prev) =>
    prev
      ? `${prev}\n\n[Running coder...]\n`
      : "Running coder...\n"
  );

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
    const content =
      data?.message?.content || data?.error || JSON.stringify(data, null, 2);

    const summary = summarizeCoderOutput(content);

    appendCoderHistory("CODER SUMMARY", summary);
    appendCoderHistory("CODER OUTPUT", content);

    setEditorText(content);
  } catch (err) {
    const errorText = `Coder request failed:\n\n${String(err)}`;

    appendCoderHistory("CODER ERROR", errorText);
    setEditorText(errorText);
  }
}
  async function sendAgentCommand() { await sendAgentText(agentInput);
  }

  async function openFile(path: string) {
    setActiveFile(path);
    setEditorText(`Loading ${path}...\n`);

    try {
      const res = await fetch("http://127.0.0.1:7900/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "codex_ui",
          route: "code",
          model: "qwen3-coder:30b",
          paths: [path],
          messages: [
            {
              role: "user",
              content: `Read ${path} and return only the file content.`,
            },
          ],
        }),
      });

      const data = await res.json();
      setEditorText(data?.message?.content || JSON.stringify(data, null, 2));
    } catch (err) {
      setEditorText(`Failed to open file:\n${String(err)}`);
    }
  }

  function sendTerminalInput() {
    const text = terminalInput;
    if (!text.trim()) return;

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setTerminalOutput((prev) => prev + "\n[PTY not connected]\n");
      return;
    }

    wsRef.current.send(JSON.stringify({ type: "input", data: text + "\n" }));
    setTerminalInput("");
  }

  const gridColumns = showRight
    ? `${leftWidth}px 6px minmax(0,1fr) 6px ${rightWidth}px`
    : `${leftWidth}px 6px minmax(0,1fr)`;

  const gridRows = showTerminal
    ? `minmax(0,1fr) 6px ${terminalHeight}px`
    : "minmax(0,1fr)";

  return (
    <div
      className="w-full min-h-0 flex flex-col gap-2 overflow-hidden"
      style={{ height: `calc(100dvh - ${HEADER_OFFSET_PX}px)` }}
    >
      <div className="flex items-center gap-2 px-1 shrink-0">
        <button onClick={() => setShowFiles((v) => !v)} className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">
          {showFiles ? "HIDE FILES" : "SHOW FILES"}
        </button>
        <button onClick={() => setShowTerminal((v) => !v)} className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">
          {showTerminal ? "HIDE TERMINAL" : "SHOW TERMINAL"}
        </button>
        <button onClick={() => setShowRight((v) => !v)} className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">
          {showRight ? "HIDE SIDE" : "SHOW SIDE"}
        </button>
        <button onClick={() => setAgentExpanded((v) => !v)} className="text-[8px] px-2 py-1 border border-white/10 text-white/50 hover:text-[var(--accent)]">
          {agentExpanded ? "NORMAL AGENT" : "EXPAND AGENT"}
        </button>
      </div>

      <div
        className="flex-1 min-h-0 grid gap-3 overflow-hidden"
        style={{
          gridTemplateColumns: agentExpanded ? "minmax(0,1fr)" : gridColumns,
          gridTemplateRows: agentExpanded ? "minmax(0,1fr)" : gridRows,
        }}
      >
        <HudPanel
          title="AGENT COMMAND"
          className={`${agentExpanded ? "col-start-1 row-start-1" : "col-start-1 row-start-1 row-span-3"} h-full min-h-0 overflow-hidden`}
        >
          <div className="p-3 h-full min-h-0 flex flex-col gap-3">
            <textarea
              value={agentInput}
              onChange={(e) => setAgentInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  sendAgentCommand();
                }
              }}
              className="h-32 shrink-0 bg-black/30 border border-white/[0.08] rounded-sm p-2 text-[11px] text-white/80 outline-none resize-none select-text"
              placeholder="Write coder command here... Ctrl+Enter to send"
            />

            <button
              onClick={sendAgentCommand}
              className="shrink-0 text-[8px] tracking-[2px] uppercase px-3 py-2 rounded-sm bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/20"
            >
              SEND TO CODE MODEL
            </button>

            <div className="shrink-0 flex items-center justify-between text-[8px] uppercase tracking-[2px] text-white/30">
              <span>Agent logs</span>
              <span>live</span>
            </div>

            <pre className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden font-mono text-[10px] leading-relaxed text-cyan-300/70 select-text bg-black/20 p-2 rounded-sm whitespace-pre-wrap break-words">
              {agentLog || "Waiting for coding loop events...\n"}
            </pre>
          </div>
        </HudPanel>

        {!agentExpanded && (
          <>
            <div
              className="col-start-2 row-start-1 row-span-3 cursor-col-resize bg-[var(--accent)]/10 hover:bg-[var(--accent)]/40 transition-colors rounded-sm h-full min-h-0"
              onMouseDown={() => startDrag("left")}
            />

            <HudPanel
              title={activeFile || "EDITOR / CODER OUTPUT"}
              className="col-start-3 row-start-1 h-full min-h-0 overflow-hidden"
            >
              <div className="p-3 h-full min-h-0 flex flex-col gap-3 text-[10px] select-text">
                <div className="shrink-0">
                  {isPlanMessage(editorText) ? (
                    <div className="flex flex-col gap-2">
                      <div className="text-[8px] uppercase tracking-[2px] text-white/35">
                        Plan detected {extractPlanId(editorText) ? `· ${extractPlanId(editorText)}` : ""}
                      </div>

                      <button
                        onClick={() => sendAgentText("proceed")}
                        className="px-3 py-2 rounded-sm bg-green-600/20 border border-green-500/40 text-green-300 hover:bg-green-600/30"
                      >
                        Accept / Proceed
                      </button>

                      <button
                        onClick={() => {
                          const text = `Modify this plan:\n\n${editorText}`;
                          setAgentInput(text);
                          appendCoderHistory("PLAN SENT TO MODIFY BOX", text);
                        }}
                        className="px-3 py-2 rounded-sm bg-yellow-600/20 border border-yellow-500/40 text-yellow-300 hover:bg-yellow-600/30"
                      >
                        Modify Plan
                      </button>

                      <button
                        onClick={() => sendAgentText("cancel")}
                        className="px-3 py-2 rounded-sm bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="text-white/35">
                      No active plan detected.
                    </div>
                  )}
                </div>

                <div className="shrink-0 flex items-center justify-between text-[8px] uppercase tracking-[2px] text-white/30">
                  <span>Output history</span>
                  <button
                    onClick={() => setCoderHistory("")}
                    className="text-[8px] text-white/35 hover:text-red-300"
                  >
                    CLEAR
                  </button>
                </div>

                <pre className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden font-mono text-[10px] leading-relaxed text-white/60 select-text bg-black/20 p-2 rounded-sm whitespace-pre-wrap break-words">
                  {coderHistory || "No coder output history yet.\n"}
                  <div ref={coderHistoryEndRef} />
                </pre>
              </div>
            </HudPanel>

            {showTerminal && (
              <>
                <div
                  className="col-start-3 row-start-2 cursor-row-resize bg-[var(--accent)]/10 hover:bg-[var(--accent)]/40 transition-colors rounded-sm"
                  onMouseDown={() => startDrag("terminal")}
                />

                <HudPanel
                  title={ptyConnected ? "TERMINAL · CONNECTED" : "TERMINAL · OFFLINE"}
                  className="col-start-3 row-start-3 h-full min-h-0 overflow-hidden"
                >
                  <div className="p-3 h-full min-h-0 flex flex-col gap-2">
                    <pre className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden font-mono text-[10px] text-green-400/70 whitespace-pre-wrap break-words select-text bg-black/20 p-2 rounded-sm">
                      {terminalOutput || "Connecting to PTY on ws://localhost:4010...\n"}
                      <div ref={terminalEndRef} />
                    </pre>

                    <div className="shrink-0 flex gap-2">
                      <input
                        value={terminalInput}
                        onChange={(e) => setTerminalInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") sendTerminalInput();
                        }}
                        className="flex-1 bg-black/30 border border-white/[0.08] rounded-sm p-2 text-[10px] font-mono text-white/70 outline-none select-text"
                        placeholder="terminal command..."
                      />

                      <button
                        onClick={sendTerminalInput}
                        className="text-[8px] tracking-[2px] uppercase px-3 rounded-sm bg-green-400/10 border border-green-400/30 text-green-400/80 hover:bg-green-400/20"
                      >
                        RUN
                      </button>
                    </div>
                  </div>
                </HudPanel>
              </>
            )}

            {showRight && (
              <>
                <div
                  className="col-start-4 row-start-1 row-span-3 cursor-col-resize bg-[var(--accent)]/10 hover:bg-[var(--accent)]/40 transition-colors rounded-sm"
                  onMouseDown={() => startDrag("right")}
                />

                <div className="col-start-5 row-start-1 row-span-3 grid grid-rows-[1fr_1fr] gap-3 min-h-0 h-full overflow-hidden">
                  {showFiles && (
                    <HudPanel title="FILES" className="h-full min-h-0 overflow-hidden">
                      <div className="p-3 h-full min-h-0 overflow-y-auto select-text">
                        <div className="text-[8px] uppercase tracking-[2px] opacity-30 mb-3 break-all">
                          {rootDir}
                        </div>

                        <div className="space-y-1">
                          {files.map((file) => (
                            <button
                              key={file}
                              onClick={() => openFile(file)}
                              className={`block w-full text-left text-[10px] px-2 py-1 rounded-sm transition-all break-all ${
                                activeFile === file
                                  ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                                  : "text-white/35 hover:text-[var(--accent)] hover:bg-white/[0.03]"
                              }`}
                            >
                              {file}
                            </button>
                          ))}
                        </div>
                      </div>
                    </HudPanel>
                  )}

                  <HudPanel title="ACTIONS" className="h-full min-h-0 overflow-hidden">
  <div className="p-3 h-full min-h-0 overflow-y-auto text-[10px] select-text">
    {isPlanMessage(editorText) ? (
      <div className="flex flex-col gap-2">
        <div className="text-[8px] uppercase tracking-[2px] text-white/35">
          Plan detected {extractPlanId(editorText) ? `· ${extractPlanId(editorText)}` : ""}
        </div>

       <button
          onClick={() => sendAgentText("proceed")}
          className="px-3 py-2 rounded-sm bg-green-600/20 border border-green-500/40 text-green-300 hover:bg-green-600/30"
        >
          Accept / Proceed
        </button>

        <button
          onClick={() => {
            const text = `Modify this plan:\n\n${editorText}`;
            setAgentInput(text);
          }}
          className="px-3 py-2 rounded-sm bg-yellow-600/20 border border-yellow-500/40 text-yellow-300 hover:bg-yellow-600/30"
        >
          Modify Plan
        </button>

        <button
          onClick={() => sendAgentText("cancel")}
          className="px-3 py-2 rounded-sm bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30"
        >
          Cancel
        </button>
      </div>
    ) : (
      <div className="text-white/35">
        No active plan detected.
      </div>
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