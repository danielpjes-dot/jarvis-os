"use client";

import { useEffect, useRef, useState } from "react";
import { HudPanel } from "./hud-panel";

export function CodingWorkspace({ projectDir }: { projectDir?: string }) {
  const rootDir = projectDir || "/mnt/e/coding/jarvis-os";

  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [editorText, setEditorText] = useState("");
  const [agentInput, setAgentInput] = useState("");
  const [terminalOutput, setTerminalOutput] = useState("");
  const [terminalInput, setTerminalInput] = useState("");
  const [ptyConnected, setPtyConnected] = useState(false);
  const [agentLog, setAgentLog] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const terminalEndRef = useRef<HTMLDivElement | null>(null);

  const files = [
    "scripts/react_server.py",
    "scripts/watcher.py",
    "skills/coding.py",
    "app/page.tsx",
    "config/models-config.json",
  ];
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

        return `[${time}] ${type.toUpperCase()} ${msg}${route ? ` route=${route}` : ""}${model ? ` model=${model}` : ""}${iter}${tools}`;
      });

      setAgentLog(lines.join("\n"));
    } catch {
      // keep previous log
    }
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

  async function sendAgentCommand() {
    const text = agentInput.trim();
    if (!text) return;

    setEditorText("Running coder...\n");
    setAgentInput("");

    const res = await fetch("http://127.0.0.1:7900/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source: "codex_ui",
            route: "code",
            model: "qwen3-coder:30b",
            messages: [{ role: "user", content: text }],
          }),
        });

    const data = await res.json();

    const content =
          data?.message?.content ||
          data?.error ||
          JSON.stringify(data, null, 2);

    setEditorText(content);
    }

  async function openFile(path: string) {
    setActiveFile(path);

    await fetch("http://localhost:4000/api/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: `read file ${rootDir}/${path}` }),
    });

    setEditorText(`// Requested file through JARVIS:\n// ${path}\n\nWaiting for coding skill response...`);
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

  return (
    <div className="h-full w-full grid grid-cols-[260px_1fr_360px] grid-rows-[1fr_220px] gap-3">
      <HudPanel title="FILES" className="row-span-2 overflow-hidden">
        <div className="p-3 h-full overflow-y-auto select-text">
          <div className="text-[8px] uppercase tracking-[2px] opacity-30 mb-3">
            {rootDir}
          </div>

          <div className="space-y-1">
            {files.map((file) => (
              <button
                key={file}
                onClick={() => openFile(file)}
                className={`block w-full text-left text-[10px] px-2 py-1 rounded-sm transition-all ${
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

      <HudPanel title={activeFile || "CODER OUTPUT"} className="overflow-hidden">
        <textarea
          value={editorText}
          onChange={(e) => setEditorText(e.target.value)}
          spellCheck={false}
          className="w-full h-full min-h-[420px] bg-black/20 text-[11px] font-mono text-white/80 p-4 outline-none resize-none select-text whitespace-pre overflow-y-auto"
          placeholder="Coder output will appear here (patches, diffs, fixes)..."
        />
      </HudPanel>

      <HudPanel title="AGENT">
        <div className="p-3 h-full flex flex-col gap-3">
          <pre className="flex-1 overflow-y-auto font-mono text-[10px] leading-relaxed text-cyan-300/70 select-text bg-black/20 p-2 rounded-sm whitespace-pre-wrap">
            {agentLog || "Waiting for coding loop events...\n"}
          </pre>

          <textarea
            value={agentInput}
            onChange={(e) => setAgentInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendAgentCommand();
            }}
            className="h-24 bg-black/30 border border-white/[0.08] rounded-sm p-2 text-[10px] text-white/70 outline-none resize-none select-text"
            placeholder="Ask coding agent... Ctrl+Enter to send"
          />

          <button
            onClick={sendAgentCommand}
            className="text-[8px] tracking-[2px] uppercase px-3 py-2 rounded-sm bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/20"
          >
            SEND TO CODE MODEL
          </button>
        </div>
      </HudPanel>

      <HudPanel title={ptyConnected ? "TERMINAL · CONNECTED" : "TERMINAL · OFFLINE"}>
        <div className="p-3 h-full flex flex-col gap-2">
          <pre className="flex-1 overflow-y-auto font-mono text-[10px] text-green-400/70 whitespace-pre-wrap select-text bg-black/20 p-2 rounded-sm">
            {terminalOutput || "Connecting to PTY on ws://localhost:4010...\n"}
            <div ref={terminalEndRef} />
          </pre>

          <div className="flex gap-2">
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

      <HudPanel title="ACTIONS">
        <div className="p-3 text-[10px] opacity-45 select-text">
          Pending diffs, approvals, test results, and git status will appear here.
        </div>
      </HudPanel>
    </div>
  );
}