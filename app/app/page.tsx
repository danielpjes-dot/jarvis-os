"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { JarvisScene } from "./components/face/jarvis-scene";
import { ChatHistory } from "./components/chat-history";
import { InputBar } from "./components/input-bar";
import { ApprovalPanel } from "./components/approval-panel";
import { HudPanel } from "./components/hud-panel";
import { GpuMonitor } from "./components/gpu-monitor";
import { SystemLog } from "./components/system-log";
import { TimersWidget } from "./components/timers-widget";
import { SettingsPanel } from "./components/settings-panel";
import { RadioPlayer } from "./components/radio-player";
import { NetworkMap } from "./components/network-map";
import { ImageGenerator } from "./components/image-generator";
import { CodingWorkspace } from "./components/coding-workspace";

type JarvisState = "standby" | "listening" | "thinking" | "speaking" | "asking";

type UiPlacement =
  | "right-side-hud"
  | "right-center-hud"
  | "left-side-hud"
  | "center-overlay"
  | "tab"
  | "none";

type UiFormat =
  | "plain"
  | "news"
  | "table"
  | "card"
  | "status"
  | "media"
  | "list"
  | "coding"
  | "log";

interface HistoryEntry {
  role: "user" | "jarvis";
  text: string;
  emotion?: string;
  timestamp: number;
}

interface SkillUiResult {
  id: string;
  tool?: string;
  placement: UiPlacement;
  format: UiFormat;
  title?: string;
  subtitle?: string;
  summary?: string;
  markdown?: string;
  items?: any[];
  columns?: string[];
  ttl_seconds?: number;
  createdAt: number;
}

function stableSkillId(tool: string, placement: UiPlacement) {
  if (tool === "coding_review") return "coding_review";
  if (tool === "coding") return "coding_workspace";
  return `${placement}-${tool}`;
}

function HudClock() {
  const [time, setTime] = useState("");
  const [date, setDate] = useState("");

  useEffect(() => {
    function tick() {
      const now = new Date();
      setTime(
        now.toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
      setDate(
        now.toLocaleDateString("en-GB", {
          weekday: "short",
          day: "2-digit",
          month: "short",
          year: "numeric",
        })
      );
    }

    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="text-right">
      <div className="text-sm tabular-nums glow-text text-[var(--accent)]">
        {time}
      </div>
      <div className="text-[8px] tracking-[2px] uppercase opacity-30">
        {date}
      </div>
    </div>
  );
}

function BrainIndicator({
  brain,
  model,
}: {
  brain?: string;
  model?: string | null;
}) {
  const labels: Record<string, { label: string; color: string }> = {
    claude: { label: "CLAUDE", color: "#c080f0" },
    ollama_fast: { label: "QWEN 8B", color: "#40f080" },
    ollama_code: { label: "QWEN CODER 30B", color: "#40a0f0" },
    ollama_reason: { label: "QWEN 14B", color: "#f0c040" },
    ollama_deep: { label: "DEEP", color: "#f08040" },
  };

  let label = "UNKNOWN";
  let color = "#40a0f0";

  if (brain && labels[brain]) {
    label = labels[brain].label;
    color = labels[brain].color;
  } else if (model) {
    label = model.toUpperCase();

    const m = model.toLowerCase();
    if (m.includes("coder")) color = "#40a0f0";
    else if (m.includes("14b")) color = "#f0c040";
    else if (m.includes("8b")) color = "#40f080";
    else if (m.includes("gemma")) color = "#f08040";
  } else if (brain) {
    label = brain.toUpperCase();
  }

  return (
    <div className="flex items-center gap-2">
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: color, boxShadow: `0 0 6px ${color}60` }}
      />
      <span className="text-[9px] tracking-[2px] uppercase" style={{ color }}>
        {label}
      </span>
    </div>
  );
}

function StateIndicator({
  state,
  pendingApprovals,
}: {
  state: JarvisState;
  pendingApprovals: number;
}) {
  const stateLabel: Record<string, string> = {
    standby: "STANDBY",
    listening: "LISTENING",
    thinking: "PROCESSING",
    speaking: "SPEAKING",
    asking: "AWAITING APPROVAL",
  };

  const stateColor: Record<string, string> = {
    standby: "#40f080",
    listening: "#f03c3c",
    thinking: "#f0c040",
    speaking: "#40a0f0",
    asking: "#f0c040",
  };

  const color = stateColor[state] || "#40a0f0";

  return (
    <div className={`flex items-center gap-2 state-${state}`}>
      <span
        className="w-2 h-2 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}80` }}
      />
      <span
        className="text-[10px] tracking-[3px] uppercase font-medium"
        style={{ color }}
      >
        {stateLabel[state]}
      </span>

      {pendingApprovals > 0 && (
        <span
          className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[8px]"
          style={{ background: `${color}20`, color }}
        >
          {pendingApprovals}
        </span>
      )}
    </div>
  );
}

function ArcReactorRing() {
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-[1]">
      <svg
        width="320"
        height="320"
        viewBox="0 0 320 320"
        className="reactor-pulse opacity-40"
      >
        <circle
          cx="160"
          cy="160"
          r="155"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.5"
          opacity="0.2"
        />
        <circle
          cx="160"
          cy="160"
          r="148"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.8"
          strokeDasharray="6 14"
          opacity="0.25"
          className="reactor-ring"
        />
        <circle
          cx="160"
          cy="160"
          r="140"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.3"
          opacity="0.15"
        />

        {Array.from({ length: 36 }).map((_, i) => {
          const angle = (i * 10 * Math.PI) / 180;
          const r1 = 152;
          const r2 = i % 3 === 0 ? 158 : 155;
          const cos = Math.round(Math.cos(angle) * 1000) / 1000;
          const sin = Math.round(Math.sin(angle) * 1000) / 1000;

          return (
            <line
              key={i}
              x1={160 + r1 * cos}
              y1={160 + r1 * sin}
              x2={160 + r2 * cos}
              y2={160 + r2 * sin}
              stroke="var(--accent)"
              strokeWidth={i % 3 === 0 ? "0.8" : "0.4"}
              opacity={i % 3 === 0 ? "0.3" : "0.15"}
            />
          );
        })}

        <polygon
          points="160,90 221,125 221,195 160,230 99,195 99,125"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.4"
          opacity="0.08"
        />
      </svg>
    </div>
  );
}

function HudLine({ className = "" }: { className?: string }) {
  return <div className={`hud-divider hud-sweep ${className}`} />;
}

function getResultText(item: SkillUiResult): string {
  if (item.summary) return item.summary;
  if (item.markdown) return item.markdown;

  if (item.items?.length) {
    return item.items
      .map((x) => x?.title || x?.name || JSON.stringify(x))
      .join("\n");
  }

  return "";
}

function SkillUiCard({ item }: { item: SkillUiResult }) {
  if (!item) return null;

  if (
    item.tool === "coding_review" &&
    (!item.items || item.items.length === 0) &&
    !item.summary &&
    !item.markdown
  ) {
    return null;
  }

  if (item.format === "coding") {
    return (
      <div className="h-full w-full min-h-0 overflow-hidden">
        <CodingWorkspace
          projectDir={
            (item as any).project_dir ||
            item.summary?.replace("Coding workspace opened for ", "") ||
            "/mnt/e/coding/jarvis-os"
          }
        />
      </div>
    );
  }

  if (item.format === "news") {
    return (
      <HudPanel title={item.title || "NEWS"} className="min-h-full overflow-visible">
        <div className="p-4 select-text space-y-3">
          {item.summary && (
            <div className="text-[10px] opacity-50 mb-3">{item.summary}</div>
          )}

          {(item.items || []).map((story: any) => (
            <div
              key={story.id || story.url || story.title}
              className="border border-white/[0.06] bg-black/20 rounded-sm p-3"
            >
              <div className="text-[11px] text-white/80 font-medium leading-relaxed">
                {story.id ? `${story.id}. ` : ""}
                {story.title}
              </div>

              {story.source && (
                <div className="text-[8px] tracking-[2px] uppercase opacity-35 mt-1">
                  {story.source}
                </div>
              )}

              {story.published && (
                <div className="text-[8px] opacity-25 mt-1">
                  {story.published}
                </div>
              )}

              {story.story && (
                <div className="text-[10px] opacity-45 mt-2 leading-relaxed">
                  {story.story}
                </div>
              )}

              {story.url && (
                <a
                  href={story.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block mt-2 text-[8px] tracking-[2px] uppercase text-[var(--accent)] opacity-70 hover:opacity-100 hover:underline"
                >
                  OPEN STORY
                </a>
              )}
            </div>
          ))}
        </div>
      </HudPanel>
    );
  }

  if (item.format === "table") {
    const rows = item.items || [];
    const columns =
      item.columns?.length
        ? item.columns
        : rows[0] && typeof rows[0] === "object"
          ? Object.keys(rows[0])
          : ["value"];

    return (
      <HudPanel title={item.title || "TABLE"} className="h-full overflow-hidden">
        <div className="p-3 h-full overflow-auto select-text">
          {item.summary && (
            <div className="text-[9px] opacity-45 mb-2">{item.summary}</div>
          )}

          <table className="w-full text-[8px]">
            <thead>
              <tr className="border-b border-white/[0.08]">
                {columns.map((c: string) => (
                  <th
                    key={c}
                    className="text-left py-1 pr-2 uppercase tracking-[1px] opacity-40"
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {rows.slice(0, 50).map((row: any, i: number) => (
                <tr key={i} className="border-b border-white/[0.04]">
                  {columns.map((c: string) => (
                    <td key={c} className="py-1 pr-2 opacity-55">
                      {typeof row === "object"
                        ? String(row?.[c] ?? "")
                        : String(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </HudPanel>
    );
  }

  if (item.format === "list") {
    return (
      <HudPanel title={item.title || "LIST"} className="h-full overflow-hidden">
        <div className="p-3 h-full overflow-y-auto space-y-1 select-text">
          {item.summary && (
            <div className="text-[9px] opacity-45 mb-2">{item.summary}</div>
          )}

          {(item.items || []).slice(0, 30).map((x: any, idx: number) => (
            <div key={idx} className="text-[9px] opacity-50 leading-relaxed">
              {typeof x === "string"
                ? x
                : x.title || x.name || JSON.stringify(x)}
            </div>
          ))}
        </div>
      </HudPanel>
    );
  }

  return (
    <HudPanel
      title={item.title || item.tool?.toUpperCase() || "RESULT"}
      className="h-full overflow-hidden"
    >
      <div className="p-3 h-full overflow-y-auto select-text">
        {item.subtitle && (
          <div className="text-[8px] uppercase tracking-[2px] opacity-30 mb-1">
            {item.subtitle}
          </div>
        )}

        <div className="text-[9px] leading-relaxed opacity-55 whitespace-pre-wrap">
          {getResultText(item) || item.summary || JSON.stringify(item, null, 2)}
        </div>
      </div>
    </HudPanel>
  );
}

function normalizeLegacySkillResult(event: any): SkillUiResult | null {
  const result = event?.data?.result;
  const tool = event?.data?.tool || "skill";

  if (!result) return null;

  const ui = result.ui;

  if (ui) {
    const placement: UiPlacement = ui.placement || "right-side-hud";

    return {
      id: ui.id || stableSkillId(tool, placement),
      tool,
      placement,
      format: ui.format || "plain",
      title: ui.title,
      subtitle: ui.subtitle,
      summary: ui.summary,
      markdown: ui.markdown,
      items: ui.items || [],
      columns: ui.columns || [],
      ttl_seconds: ui.ttl_seconds,
      createdAt: Date.now(),
    };
  }

  if (typeof result === "string") {
    return {
      id: stableSkillId(tool, "right-side-hud"),
      tool,
      placement: "right-side-hud",
      format: "plain",
      title: tool.toUpperCase(),
      summary: result,
      createdAt: Date.now(),
    };
  }

  return {
    id: stableSkillId(tool, "right-side-hud"),
    tool,
    placement: "right-side-hud",
    format: "card",
    title: tool.toUpperCase(),
    summary:
      result?.speech?.text ||
      result?.summary ||
      JSON.stringify(result, null, 2),
    items: Array.isArray(result?.items) ? result.items : [],
    createdAt: Date.now(),
  };
}

export default function JarvisPage() {
  const [state, setState] = useState<JarvisState>("standby");
  const [emotion, setEmotion] = useState("neutral");
  const [output, setOutput] = useState("Systems online. Ready for input.");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [ttsAvailable, setTtsAvailable] = useState(false);
  const [reactServerReady, setReactServerReady] = useState(false);
  const [reactServerHealth, setReactServerHealth] = useState<any>(null);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [brain, setBrain] = useState("claude");
  const [liveBrain, setLiveBrain] = useState("unknown");
  const [liveModel, setLiveModel] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("jarvis");
  const [openTabs, setOpenTabs] = useState<{ id: string; label: string }[]>([]);

  const [rightHudItems, setRightHudItems] = useState<SkillUiResult[]>([]);
  const [leftHudItems, setLeftHudItems] = useState<SkillUiResult[]>([]);
  const [centerOverlay, setCenterOverlay] = useState<SkillUiResult | null>(null);
  const [tabResults, setTabResults] = useState<Record<string, SkillUiResult>>({});

  const historyEndRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const stateRef = useRef(state);
  const lastSpokenRef = useRef("");
  const lastEventTsRef = useRef(0);
  const lastNetworkScanRef = useRef(0);
  const awakeUntilRef = useRef(0);
  const alwaysOnRef = useRef(false);

  const [micActive, setMicActive] = useState(false);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const openTab = useCallback((id: string, label: string) => {
    setOpenTabs((prev) =>
      prev.find((t) => t.id === id) ? prev : [...prev, { id, label }]
    );
    setActiveTab(id);
  }, []);

  const closeTab = useCallback((id: string) => {
    setOpenTabs((prev) => prev.filter((t) => t.id !== id));
    setActiveTab((cur) => (cur === id ? "jarvis" : cur));
  }, []);
  
  const handleSkillUiResult = useCallback(
    (item: SkillUiResult | null) => {
      if (!item || item.placement === "none") return;

      const normalizedItem: SkillUiResult = {
        ...item,
        id: item.tool ? stableSkillId(item.tool, item.placement) : item.id,
        createdAt: Date.now(),
      };

      const upsert = (prev: SkillUiResult[]) => {
        const withoutOld = prev.filter(
          (x) => x.id !== normalizedItem.id && x.tool !== normalizedItem.tool
        );

        return [normalizedItem, ...withoutOld].slice(0, 6);
      };

      if (
        normalizedItem.placement === "right-side-hud" ||
        normalizedItem.placement === "right-center-hud"
      ) {
        setRightHudItems(upsert);
        return;
      }

      if (normalizedItem.placement === "left-side-hud") {
        setLeftHudItems(upsert);
        return;
      }

      if (normalizedItem.placement === "center-overlay") {
        setCenterOverlay(normalizedItem);
        return;
      }

      if (normalizedItem.placement === "tab") {
        const tabId = normalizedItem.tool || normalizedItem.id;
        setTabResults((prev) => ({ ...prev, [tabId]: normalizedItem }));
        openTab(
          tabId,
          (normalizedItem.title || normalizedItem.tool || "RESULT").toUpperCase()
        );
      }
    },
    [openTab]
  );

  useEffect(() => {
    fetch("/api/tts")
      .then((r) => r.json())
      .then((d) => setTtsAvailable(Boolean(d.available)))
      .catch(() => {});
  }, []);
useEffect(() => {
  let active = true;

  async function pollBrain() {
    try {
      const res = await fetch("/api/brain", { cache: "no-store" });
      const data = await res.json();

      if (!active) return;

      setLiveBrain(data?.brain || "unknown");
      setLiveModel(data?.model || null);
    } catch {
      if (!active) return;
      setLiveBrain("unknown");
      setLiveModel(null);
    }
  }

  pollBrain();
  const id = setInterval(pollBrain, 3000);

  return () => {
    active = false;
    clearInterval(id);
  };
}, []);
  useEffect(() => {
  let active = true;

  async function checkReactServer() {
    try {
      const res = await fetch("http://127.0.0.1:7900/api/health", {
        cache: "no-store",
      });

      const data = await res.json();

      if (!active) return;

      setReactServerReady(data?.status === "ok");
      setReactServerHealth(data);
    } catch {
      if (!active) return;

      setReactServerReady(false);
      setReactServerHealth(null);
    }
  }

  checkReactServer();
  const id = setInterval(checkReactServer, 5000);

  return () => {
    active = false;
    clearInterval(id);
  };
}, []);

  useEffect(() => {
    let active = true;

    const check = async () => {
      try {
        const res = await fetch("/api/network", { cache: "no-store" });
        const data = await res.json();

        if (!active) return;

        if (
          data.scan_time &&
          data.scan_time > lastNetworkScanRef.current &&
          lastNetworkScanRef.current > 0
        ) {
          openTab("network", "NETWORK");
        }

        if (data.scan_time) lastNetworkScanRef.current = data.scan_time;
      } catch {}
    };

    check();
    const id = setInterval(check, 5000);

    return () => {
      active = false;
      clearInterval(id);
    };
  }, [openTab]);

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const res = await fetch("http://localhost:4000/api/state");
        const data = await res.json();

        if (!active) return;

        if (data.brain) setBrain(data.brain);

        const validStates = ["standby", "thinking", "speaking", "listening"];
        if (validStates.includes(data.state)) setState(data.state as JarvisState);

        if (data.emotion) setEmotion(data.emotion);

        if (data.lastOutput && data.lastOutput !== output) {
          setOutput(data.lastOutput);

          setHistory((h) => {
            const last = h[h.length - 1];
            if (last?.role === "jarvis" && last.text === data.lastOutput) {
              return h;
            }

            return [
              ...h,
              {
                role: "jarvis",
                text: data.lastOutput,
                timestamp: Date.now(),
              },
            ];
          });

          const BROWSER_TTS = false;

          if (BROWSER_TTS && data.lastOutput !== lastSpokenRef.current) {
            lastSpokenRef.current = data.lastOutput;
          }
        }
      } catch {}
    }

    poll();
    const id = setInterval(poll, 500);

    return () => {
      active = false;
      clearInterval(id);
    };
  }, [output]);

  const handleSend = useCallback(async (text: string) => {
    setHistory((h) => [...h, { role: "user", text, timestamp: Date.now() }]);

    try {
      await fetch("http://localhost:4000/api/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
    } catch {
      setOutput("Connection error. Is the bridge server running?");
    }
  }, []);

  function audioBufferToWav(buffer: AudioBuffer): Blob {
    const numChannels = 1;
    const sampleRate = buffer.sampleRate;
    const samples = buffer.getChannelData(0);
    const dataLength = samples.length * 2;
    const arrayBuffer = new ArrayBuffer(44 + dataLength);
    const view = new DataView(arrayBuffer);

    function writeStr(offset: number, s: string) {
      for (let i = 0; i < s.length; i++) {
        view.setUint8(offset + i, s.charCodeAt(i));
      }
    }

    writeStr(0, "RIFF");
    view.setUint32(4, 36 + dataLength, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * 2, true);
    view.setUint16(32, numChannels * 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, dataLength, true);

    let offset = 44;

    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }

    return new Blob([arrayBuffer], { type: "audio/wav" });
  }

  const WAKE_WORDS = [
    "hey jarvis",
    "ok jarvis",
    "jarvis",
    "hey travis",
    "hey jervis",
    "hey charvis",
  ];

  const AWAKE_TIMEOUT = 60_000;

  function hasWakeWord(text: string): boolean {
    const lower = text.toLowerCase();
    return WAKE_WORDS.some((w) => lower.includes(w));
  }

  function stripWakeWord(text: string): string {
    const lower = text.toLowerCase();

    for (const wake of WAKE_WORDS) {
      const idx = lower.indexOf(wake);

      if (idx !== -1 && idx < 20) {
        return text
          .slice(idx + wake.length)
          .replace(/^[,.\s]+/, "")
          .trim();
      }
    }

    return text;
  }

  function captureUtterance(
    stream: MediaStream,
    analyser: AnalyserNode
  ): Promise<string> {
    return new Promise((resolve) => {
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };

      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: recorder.mimeType });

        try {
          const arrayBuf = await blob.arrayBuffer();
          const decodeCtx = new AudioContext({ sampleRate: 16000 });
          const audioBuf = await decodeCtx.decodeAudioData(arrayBuf);
          const wavBlob = audioBufferToWav(audioBuf);

          decodeCtx.close();

          const res = await fetch("/api/transcribe", {
            method: "POST",
            body: wavBlob,
          });

          const data = await res.json();
          resolve(data.echo ? "" : data.text || "");
        } catch {
          resolve("");
        }
      };

      recorder.start();

      let silentFrames = 0;
      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      const check = () => {
        if (recorder.state === "inactive") return;

        analyser.getByteFrequencyData(dataArray);

        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

        if (avg < 5) {
          silentFrames++;

          if (silentFrames > 8) {
            recorder.stop();
            return;
          }
        } else {
          silentFrames = 0;
        }

        setTimeout(check, 300);
      };

      setTimeout(check, 800);

      setTimeout(() => {
        if (recorder.state !== "inactive") recorder.stop();
      }, 15000);
    });
  }

  function waitForSpeech(
    analyser: AnalyserNode,
    timeoutMs = 30000
  ): Promise<boolean> {
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    const start = Date.now();

    return new Promise((resolve) => {
      const check = () => {
        if (!alwaysOnRef.current) {
          resolve(false);
          return;
        }

        if (Date.now() - start > timeoutMs) {
          resolve(true);
          return;
        }

        analyser.getByteFrequencyData(dataArray);

        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

        if (avg > 8) {
          resolve(true);
          return;
        }

        setTimeout(check, 100);
      };

      check();
    });
  }

  const startAlwaysOn = useCallback(async () => {
    if (alwaysOnRef.current) return;

    alwaysOnRef.current = true;
    setMicActive(true);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();

      analyser.fftSize = 512;
      source.connect(analyser);

      while (alwaysOnRef.current) {
        if (
          stateRef.current === "thinking" ||
          stateRef.current === "speaking"
        ) {
          await new Promise((r) => setTimeout(r, 500));
          continue;
        }

        const hasSpeech = await waitForSpeech(analyser);
        if (!hasSpeech) break;

        const text = await captureUtterance(stream, analyser);
        if (!text || text.length < 3) continue;

        const now = Date.now();
        const isAwake = now < awakeUntilRef.current;

        if (hasWakeWord(text)) {
          awakeUntilRef.current = now + AWAKE_TIMEOUT;
          const command = stripWakeWord(text);

          if (command && command.length > 2) handleSend(command);
        } else if (isAwake) {
          handleSend(text);
          awakeUntilRef.current = now + AWAKE_TIMEOUT;
        }

        await new Promise((r) => setTimeout(r, 500));
      }

      stream.getTracks().forEach((t) => t.stop());
      audioCtx.close();
    } catch {}

    alwaysOnRef.current = false;
    setMicActive(false);
    setState("standby");
  }, [handleSend]);

  const stopAlwaysOn = useCallback(() => {
    alwaysOnRef.current = false;
  }, []);

  useEffect(() => {
    historyEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  function handleVoiceToggle() {
    if (alwaysOnRef.current) stopAlwaysOn();
    else startAlwaysOn();
  }

  const isProcessing = state === "thinking" || state === "speaking";
const activeBrain =
  brain && brain !== "unknown" && brain !== "-"
    ? brain
    : liveBrain;

const activeModel =
  liveModel ||
  reactServerHealth?.models?.code ||
  reactServerHealth?.planner_model ||
  null;
  return (
    <main className="h-screen w-screen overflow-hidden bg-[var(--background)] hud-grid scan-lines select-none relative">
      <ApprovalPanel
        onApprovalChange={(count) => {
          setPendingApprovals(count);

          if (count > 0) setState("asking");
          else setState((s) => (s === "asking" ? "standby" : s));
        }}
      />

      <header className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-6 py-3">
        <div>
          <h1 className="text-sm tracking-[6px] uppercase glow-text text-[var(--accent)] font-bold">
            J.A.R.V.I.S
          </h1>
          <div className="text-[7px] tracking-[3px] uppercase opacity-25 mt-0.5">
            {ttsAvailable ? "ORPHEUS TTS ACTIVE" : "TEXT MODE"} &middot; LOCAL
            AI ASSISTANT
          </div>
        </div>

        <StateIndicator state={state} pendingApprovals={pendingApprovals} />

        <div className="flex items-center gap-6">
          <BrainIndicator brain={activeBrain} model={activeModel} />
          <div className="w-px h-6 bg-[var(--panel-border)]" />
          <HudClock />

          <button
            onClick={() => setSettingsOpen(true)}
            className="w-7 h-7 flex items-center justify-center rounded-full opacity-30 hover:opacity-70 transition-opacity"
            title="Settings"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="1.5"
            >
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </div>
      </header>

      <HudLine className="absolute top-[52px] left-0 right-0 z-20" />

      <div className="absolute inset-0 top-[53px] bottom-0 flex">
        <aside className="w-[260px] flex-shrink-0 flex flex-col gap-3 p-3 overflow-y-auto scrollbar-hud z-10">
          <RadioPlayer />

          {leftHudItems.map((item) => (
            <div key={item.id} className="relative group">
              <button
                onClick={() =>
                  setLeftHudItems((prev) =>
                    prev.filter((x) => x.id !== item.id)
                  )
                }
                className="absolute top-2 right-2 z-20 text-[10px] text-white/20 hover:text-red-400 opacity-0 group-hover:opacity-100"
              >
                ×
              </button>
              <SkillUiCard item={item} />
            </div>
          ))}

          <GpuMonitor />

          <HudPanel title="EMOTION STATE">
            <div className="p-3 flex items-center gap-3">
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-lg bg-[var(--accent)]/10 text-[var(--accent)]">
                {emotion === "happy"
                  ? "✓"
                  : emotion === "thinking"
                    ? "?"
                    : emotion === "serious"
                      ? "!"
                      : emotion === "confused"
                        ? "~"
                        : "•"}
              </div>

              <div>
                <div className="text-[10px] tracking-[2px] uppercase text-[var(--foreground)] opacity-60">
                  {emotion.toUpperCase()}
                </div>
                <div className="text-[8px] tracking-[1px] opacity-25">
                  EMOTION VECTOR
                </div>
              </div>
            </div>
          </HudPanel>

          <HudPanel title="AUDIO SYSTEM">
            <div className="p-3">
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    ttsAvailable ? "bg-green-400" : "bg-red-400/50"
                  }`}
                />
                <span className="text-[9px] tracking-[2px] uppercase opacity-50">
                  {ttsAvailable ? "ORPHEUS TTS ONLINE" : "TTS OFFLINE"}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                <span className="text-[9px] tracking-[2px] uppercase opacity-50">
                  WHISPER STT
                </span>
              </div>
            </div>
          </HudPanel>
        </aside>

        <div className="flex-1 relative flex flex-col min-w-0">
          {openTabs.length > 0 && (
            <div className="flex items-center gap-1 px-4 pt-2 pb-1 z-10">
              <button
                onClick={() => setActiveTab("jarvis")}
                className={`text-[8px] tracking-[3px] uppercase px-3 py-1.5 rounded-sm transition-all ${
                  activeTab === "jarvis"
                    ? "text-[var(--accent)] bg-[var(--accent)]/10 border border-[var(--accent)]/30"
                    : "text-white/20 hover:text-white/40 border border-transparent"
                }`}
              >
                JARVIS
              </button>

              {openTabs.map((tab) => (
                <div key={tab.id} className="flex items-center">
                  <button
                    onClick={() => setActiveTab(tab.id)}
                    className={`text-[8px] tracking-[3px] uppercase px-3 py-1.5 rounded-l-sm transition-all ${
                      activeTab === tab.id
                        ? "text-[var(--accent)] bg-[var(--accent)]/10 border border-[var(--accent)]/30 border-r-0"
                        : "text-white/20 hover:text-white/40 border border-transparent"
                    }`}
                  >
                    {tab.label}
                  </button>

                  <button
                    onClick={() => closeTab(tab.id)}
                    className={`text-[8px] px-1.5 py-1.5 rounded-r-sm transition-all ${
                      activeTab === tab.id
                        ? "text-white/30 hover:text-red-400 bg-[var(--accent)]/10 border border-[var(--accent)]/30 border-l-0"
                        : "text-white/10 hover:text-red-400 border border-transparent"
                    }`}
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>
          )}

          {activeTab === "jarvis" && (
            <>
              <div
                className="flex-1 relative cursor-pointer min-h-0"
                onClick={handleVoiceToggle}
              >
                <ArcReactorRing />
                <JarvisScene
                  emotion={emotion}
                  speaking={state === "speaking"}
                  thinking={state === "thinking"}
                />

                {state === "listening" && (
                  <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
                    <div className="text-red-400 text-[10px] tracking-[4px] uppercase state-listening flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
                      LISTENING &mdash; CLICK TO STOP
                    </div>
                  </div>
                )}
              </div>

              <div className="flex-shrink-0 px-6 pb-4 pt-2 z-10 relative">
                <HudLine className="mb-3" />

                <div className="text-center mb-3">
                  <p className="text-sm leading-relaxed opacity-75 max-w-xl mx-auto data-flicker select-text">
                    {output}
                  </p>
                </div>

                {history.length > 0 && (
                  <div className="mb-3">
                    <button
                      onClick={() => setChatOpen((o) => !o)}
                      className="text-[8px] tracking-[2px] uppercase text-[var(--accent)] opacity-30 hover:opacity-60 transition-opacity cursor-pointer mx-auto block mb-2"
                    >
                      {chatOpen ? "HIDE HISTORY" : `SHOW HISTORY (${history.length})`}
                    </button>

                    {chatOpen && (
                      <div className="max-w-xl mx-auto">
                        <HudPanel className="mb-2">
                          <div className="p-2 select-text">
                            <ChatHistory history={history} />
                            <div ref={historyEndRef} />
                          </div>
                        </HudPanel>
                      </div>
                    )}
                  </div>
                )}

                <p className="text-[8px] text-white/15 tracking-[2px] text-center mb-2 uppercase">
                  {micActive
                    ? 'Listening… say "Hey JARVIS"'
                    : "Click face to start voice"}{" "}
                  &middot; Type below for text
                </p>

                <div className="max-w-xl mx-auto">
                  <InputBar
                    onSend={handleSend}
                    disabled={isProcessing}
                    listening={state === "listening"}
                    onVoiceToggle={handleVoiceToggle}
                  />
                </div>
              </div>
            </>
          )}

          {activeTab === "codex" && (
            <div className="flex-1 min-h-0 overflow-hidden p-4">
              <CodingWorkspace projectDir="/mnt/e/coding/jarvis-os" />
            </div>
          )}

          {activeTab === "network" && (
            <div className="flex-1 overflow-y-auto p-6">
              <NetworkMap onScanComplete={() => openTab("network", "NETWORK")} />
            </div>
          )}

          {activeTab === "logs" && (
            <div className="flex-1 overflow-y-auto p-6">
              <SystemLog />
            </div>
          )}

          {activeTab === "imagegen" && (
            <div className="flex-1 overflow-y-auto p-6 flex items-center justify-center">
              <ImageGenerator />
            </div>
          )}

          {tabResults[activeTab] &&
            (tabResults[activeTab].format === "coding" ? (
              <div className="flex-1 min-h-0 overflow-hidden p-4">
                <SkillUiCard item={tabResults[activeTab]} />
              </div>
            ) : (
              <div className="flex-1 min-h-0 overflow-hidden p-4">
                <div className="h-full min-h-0 overflow-y-auto scrollbar-tab select-text pr-2">
                  <SkillUiCard item={tabResults[activeTab]} />
                </div>
              </div>
            ))}
        </div>

        <aside className="w-[280px] flex-shrink-0 flex flex-col gap-3 p-3 overflow-y-auto scrollbar-hud z-10">
          <TimersWidget />

          {rightHudItems.map((item) => (
            <div key={item.id} className="relative group">
              <button
                onClick={() =>
                  setRightHudItems((prev) =>
                    prev.filter((x) => x.id !== item.id)
                  )
                }
                className="absolute top-2 right-2 z-20 text-[10px] text-white/20 hover:text-red-400 opacity-0 group-hover:opacity-100"
              >
                ×
              </button>

              <SkillUiCard item={item} />
            </div>
          ))}

          <div className="flex flex-wrap gap-1.5 px-1">
            {[
              { id: "network", label: "NETWORK" },
              { id: "logs", label: "LOGS" },
              { id: "imagegen", label: "IMAGE GEN" },
              { id: "codex", label: "CODEX" },
            ].map((item) => (
              <button
                key={item.id}
                onClick={() => openTab(item.id, item.label)}
                className="text-[7px] tracking-[2px] uppercase px-2.5 py-1 rounded-sm bg-white/[0.02] border border-white/[0.06] text-white/25 hover:text-[var(--accent)] hover:border-[var(--accent)]/30 transition-all"
              >
                {item.label}
              </button>
            ))}
          </div>

<div className="p-3 space-y-2.5">
  <div className="flex justify-between items-center">
    <span className="text-[9px] tracking-[2px] uppercase opacity-40">
      BRAIN 
    </span>
    <BrainIndicator brain={activeBrain} model={activeModel} />
  </div>

  <div className="hud-divider" />

  <div className="flex justify-between items-center">
    <span className="text-[9px] tracking-[2px] uppercase opacity-40">
      CODE MODEL
    </span>
    <span className="text-[9px] tracking-[1px] uppercase text-[var(--accent)] opacity-60">
      {reactServerHealth?.models?.code || "UNKNOWN"}
    </span>
  </div>

  <div className="hud-divider" />

  <div className="flex justify-between items-center">
    <span className="text-[9px] tracking-[2px] uppercase opacity-40">
      PLANNER
    </span>
    <span className="text-[9px] tracking-[1px] uppercase text-[var(--accent)] opacity-60">
      {reactServerHealth?.planner_model || "UNKNOWN"}
    </span>
  </div>

  <div className="hud-divider" />

  <div className="flex justify-between items-center">
    <span className="text-[9px] tracking-[2px] uppercase opacity-40">
      STATE
    </span>
    <StateIndicator state={state} pendingApprovals={0} />
  </div>

  <div className="hud-divider" />

  <div className="flex justify-between items-center">
    <span className="text-[9px] tracking-[2px] uppercase opacity-40">
      EMOTION
    </span>
    <span className="text-[10px] tracking-[2px] uppercase text-[var(--accent)] opacity-60">
      {emotion}
    </span>
  </div>

  <div className="hud-divider" />

  <div className="flex justify-between items-center">
    <span className="text-[9px] tracking-[2px] uppercase opacity-40">
      MESSAGES
    </span>
    <span className="text-[10px] tabular-nums text-[var(--accent)] opacity-60">
      {history.length}
    </span>
  </div>
</div>

          <HudPanel title="CONNECTIONS">
            <div className="p-3 space-y-2">
              {[
                { name: "NEXT.JS SERVER", status: true },
                { name: "BRIDGE (4000)", status: true },
                { name: "REACT SERVER (7900)", status: reactServerReady },
                { name: "OLLAMA", status: Boolean(reactServerHealth?.ollama_ready) },
                { name: "TTS ENGINE", status: ttsAvailable },
              ].map((conn) => (
                <div key={conn.name} className="flex items-center gap-2">
                  <span
                    className={`w-1 h-1 rounded-full ${
                      conn.status ? "bg-green-400" : "bg-white/15"
                    }`}
                  />
                  <span
                    className={`text-[9px] tracking-[2px] uppercase ${
                      conn.status ? "opacity-50" : "opacity-20"
                    }`}
                  >
                    {conn.name}
                  </span>
                </div>
              ))}
            </div>
          </HudPanel>

          <div className="flex-1" />

          <div className="text-[7px] tracking-[1px] opacity-10 font-mono px-2 pb-2 leading-relaxed data-flicker">
            SYS.KERNEL.V4.2.1
            <br />
            MEM.ALLOC.OK
            <br />
            NET.BRIDGE.ACTIVE
            <br />
            VAULT.SYNC.NOMINAL
            <br />
            SEC.CLEARANCE.ALPHA
          </div>
        </aside>
      </div>

      {centerOverlay && (
        <div className="absolute inset-0 z-40 flex items-center justify-center pointer-events-none">
          <div className="w-[560px] pointer-events-auto">
            <SkillUiCard item={centerOverlay} />

            <button
              onClick={() => setCenterOverlay(null)}
              className="mt-2 text-[8px] tracking-[2px] uppercase text-[var(--accent)] opacity-40 hover:opacity-80"
            >
              CLOSE
            </button>
          </div>
        </div>
      )}

      <div className="absolute top-1 left-1 w-4 h-4 border-t border-l border-[var(--accent)] opacity-15 z-30 pointer-events-none" />
      <div className="absolute top-1 right-1 w-4 h-4 border-t border-r border-[var(--accent)] opacity-15 z-30 pointer-events-none" />
      <div className="absolute bottom-1 left-1 w-4 h-4 border-b border-l border-[var(--accent)] opacity-15 z-30 pointer-events-none" />
      <div className="absolute bottom-1 right-1 w-4 h-4 border-b border-r border-[var(--accent)] opacity-15 z-30 pointer-events-none" />

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </main>
  );
}