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
import { MicVAD } from "@ricky0123/vad-web";



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
  const [reactServerReady, setReactServerReady] = useState(false);
  const [reactServerHealth, setReactServerHealth] = useState<any>(null);
  const [ollamaServerReady, setOllamaServerReady] = useState(false);
  const [ollamaServerHealth, setOllamaServerHealth] = useState<any>(null);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [brain, setBrain] = useState("claude");
  const [liveBrain, setLiveBrain] = useState("unknown");
  const [liveModel, setLiveModel] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<string>("jarvis");
  const [openTabs, setOpenTabs] = useState<{ id: string; label: string }[]>([]);
  const [kokoroReady, setKokoroReady] = useState(false);
  const [llamaCppReady, setLlamaCppReady] = useState(false);

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
  const videoRef = useRef<HTMLVideoElement>(null);
  const waveformCanvasRef = useRef<HTMLCanvasElement>(null);
  const waveformRafRef = useRef<number>(0);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const micSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const streamNextTimeRef = useRef(0);
  const speakingStartedAtRef = useRef(0);
  const ignoreIncomingAudioRef = useRef(false);
  const parlourWsRef = useRef<WebSocket | null>(null);
  const vadRef = useRef<any>(null);
  const [cameraEnabled, setCameraEnabled] = useState(true);
  const [micEnabled, setMicEnabled] = useState(true);
  const [muted, setMuted] = useState(false);

const micEnabledRef = useRef(true);
const mutedRef = useRef(false);
  const [parlourConnected, setParlourConnected] = useState(false);
  const ambientPhaseRef = useRef(0);
  const BAR_COUNT = 40;
  const BAR_GAP = 3;
  const [micActive, setMicActive] = useState(false);
  const waveformModeRef = useRef<"idle" | "user" | "ai">("idle");
useEffect(() => {
  micEnabledRef.current = micEnabled;
}, [micEnabled]);

useEffect(() => {
  mutedRef.current = muted;
}, [muted]);
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

    async function checkLocalAiServices() {
      try {
        const kokoro = await fetch("http://127.0.0.1:5100/tts/health", {
          cache: "no-store",
        });
        if (active) setKokoroReady(kokoro.ok);
      } catch {
        if (active) setKokoroReady(false);
      }

      try {
        const llama = await fetch("http://127.0.0.1:8081/health", {
          cache: "no-store",
        });
        if (active) setLlamaCppReady(llama.ok);
      } catch {
        if (active) setLlamaCppReady(false);
      }
    }

    checkLocalAiServices();
    const id = setInterval(checkLocalAiServices, 5000);

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

async function pollBrain() {
  try {
    const res = await fetch("http://127.0.0.1:11434/api/ps", {
      cache: "no-store",
    });

    const data = await res.json();
    if (!active) return;

    const models = data?.models || [];
    const activeModel = models[0] || null;

    setOllamaServerReady(res.ok);
    setOllamaServerHealth(data);

    if (activeModel) {
      const name = activeModel.name || activeModel.model || "unknown";
      const details = activeModel.details || {};

      setBrain(name);
      setLiveModel(
        `${details.family || ""} ${details.parameter_size || ""}`.trim() || name
      );
    } else {
      setBrain("unknown");
      setLiveModel(null);
    }
  } catch {
    if (!active) return;

    setOllamaServerReady(false);
    setOllamaServerHealth(null);
    setBrain("unknown");
    setLiveModel(null);
  }
}

  pollBrain();
  const id = setInterval(pollBrain, 5000);

  return () => {
    active = false;
    clearInterval(id);
  };
}, []);

const handleSend = useCallback(async (text: string) => {
  setHistory((h) => [...h, { role: "user", text, timestamp: Date.now() }]);
  setState("thinking");

  try {
    const res = await fetch("http://127.0.0.1:7900/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: "react",
        route: "live",
        messages: [{ role: "user", content: text }],
        stream: false,
      }),
    });

    const data = await res.json();
    const reply = data?.message?.content || "";

    setOutput(reply);
    setHistory((h) => [...h, { role: "jarvis", text: reply, timestamp: Date.now() }]);
    setState("standby");
  } catch {
    setOutput("Connection error. Is the ReAct server running on port 7900?");
    setState("standby");
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
      const dataArray = new Uint8Array(
      new ArrayBuffer(analyser.frequencyBinCount)
      );
      const check = () => {
        if (recorder.state === "inactive") return;
        const dataArray = new Uint8Array(
          new ArrayBuffer(analyser.frequencyBinCount)
        );
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

// 2. Replace the entire startAlwaysOn / stopAlwaysOn / handleVoiceToggle block
// and add all new functions. Insert after the stopAlwaysOn definition:

  // ── Audio context ──
const ensureAudioCtx = useCallback(() => {
  if (!audioCtxRef.current) {
    audioCtxRef.current = new AudioContext();
    const analyser = audioCtxRef.current.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.75;
    analyserRef.current = analyser;
  }
}, []);



  // ── Waveform ──
const getStateColor = useCallback(() => {
  if (waveformModeRef.current === "user") return "#4ade80"; // green mic
  if (waveformModeRef.current === "ai") return "#f59e0b";   // orange AI

  const colors: Record<string, string> = {
    listening: "#4ade80",
    thinking: "#f59e0b",
    speaking: "#f59e0b",
    standby: "#3a3d46",
    asking: "#f0c040",
  };

  return colors[stateRef.current] || "#3a3d46";
}, []);

  const drawWaveform = useCallback(() => {
    const canvas = waveformCanvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rect = canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    const dpr = window.devicePixelRatio || 1;

    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const barWidth = (w - (BAR_COUNT - 1) * BAR_GAP) / BAR_COUNT;
    ctx.fillStyle = getStateColor();

    let dataArray: Uint8Array<ArrayBuffer> | null = null;

    if (analyserRef.current) {
      dataArray = new Uint8Array(new ArrayBuffer(analyserRef.current.frequencyBinCount));
      analyserRef.current.getByteFrequencyData(dataArray);
    }

    for (let i = 0; i < BAR_COUNT; i++) {
      let amplitude = 0;

      if (dataArray) {
        const binIndex = Math.floor((i / BAR_COUNT) * dataArray.length * 0.6);
        amplitude = dataArray[binIndex] / 255;
      }

      if (!dataArray || amplitude < 0.02) {
        ambientPhaseRef.current += 0.0001;
        const drift = Math.sin(ambientPhaseRef.current * 3 + i * 0.4) * 0.5 + 0.5;
        amplitude = 0.03 + drift * 0.04;
      }

      const barH = Math.max(2, amplitude * (h - 4));
      const x = i * (barWidth + BAR_GAP);
      const y = (h - barH) / 2;
      const r = Math.min(barWidth / 2, barH / 2, 3);

      ctx.globalAlpha = 0.3 + amplitude * 0.7;
      ctx.beginPath();

      if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, barWidth, barH, r);
      } else {
        ctx.rect(x, y, barWidth, barH);
      }

      ctx.fill();
    }

    ctx.globalAlpha = 1;
    waveformRafRef.current = requestAnimationFrame(drawWaveform);
  }, [getStateColor]);

  useEffect(() => {
    waveformRafRef.current = requestAnimationFrame(drawWaveform);
    return () => cancelAnimationFrame(waveformRafRef.current);
  }, [drawWaveform]);

  // ── Streaming TTS playback ──
  const stopPlayback = useCallback(() => {
    for (const src of streamSourcesRef.current) {
      try { src.stop(); } catch {}
    }
    streamSourcesRef.current = [];
    streamNextTimeRef.current = 0;
  }, []);
  const playAudioBlob = useCallback(async (base64Audio: string, mime = "audio/wav") => {
    if (mutedRef.current) return;

    stopPlayback();
    ensureAudioCtx();

  const audio = new Audio(`data:${mime};base64,${base64Audio}`);
  waveformModeRef.current = "ai";
  setState("speaking");
  setAiSpeaking(true);

  audio.onended = () => {
    waveformModeRef.current = "idle";
    setState("listening");
    setAiSpeaking(false);
  };

  await audio.play();
}, [stopPlayback, ensureAudioCtx]);
  const startStreamPlayback = useCallback((_sampleRate = 24000) => {
    stopPlayback();
    ensureAudioCtx();
    streamNextTimeRef.current = audioCtxRef.current!.currentTime + 0.05;
    speakingStartedAtRef.current = Date.now();
    setState("speaking");
  }, [stopPlayback, ensureAudioCtx]);

  const queueAudioChunk = useCallback((base64Pcm: string) => {
    ensureAudioCtx();
    if (mutedRef.current) return;
    const ctx = audioCtxRef.current!;
    const analyser = analyserRef.current!;

    const bin = atob(base64Pcm);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const safeBuffer = bytes.buffer.slice(
      bytes.byteOffset,
      bytes.byteOffset + bytes.byteLength
    ) as ArrayBuffer;

    const int16 = new Int16Array(safeBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const audioBuffer = ctx.createBuffer(1, float32.length, 24000);
    audioBuffer.getChannelData(0).set(float32);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);
    source.connect(analyser);

    const startAt = Math.max(streamNextTimeRef.current, ctx.currentTime);
    source.start(startAt);
    streamNextTimeRef.current = startAt + audioBuffer.duration;
    streamSourcesRef.current.push(source);

    source.onended = () => {
      const idx = streamSourcesRef.current.indexOf(source);
      if (idx !== -1) streamSourcesRef.current.splice(idx, 1);
      if (streamSourcesRef.current.length === 0 && stateRef.current === "speaking") {
        setState("listening");
      }
    };
  }, [ensureAudioCtx]);

  // ── Camera ──
  const captureFrame = useCallback(() => {
    if (!cameraEnabled || !videoRef.current?.videoWidth) return null;
    const canvas = document.createElement("canvas");
    const scale = 320 / videoRef.current.videoWidth;
    canvas.width = 320;
    canvas.height = videoRef.current.videoHeight * scale;
    canvas.getContext("2d")!.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.7).split(",")[1];
  }, [cameraEnabled]);

  // ── float32 WAV encoder ──
  const float32ToWavBase64 = useCallback((samples: Float32Array): string => {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const w = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    w(0,"RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8,"WAVE"); w(12,"fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true);
    v.setUint16(34, 16, true); w(36,"data"); v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    const bytes = new Uint8Array(buf);
    let bin = ""; for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }, []);


  const connectParlour = useCallback(() => {
    const ws = new WebSocket("ws://127.0.0.1:7900/ws");
    parlourWsRef.current = ws;

    
    ws.onopen = () => {
      console.log("[WS] connected");
      setParlourConnected(true);
    };

    ws.onclose = () => {
      setParlourConnected(false);
      setTimeout(connectParlour, 3000);
    };
    ws.onmessage = ({ data }) => {
      console.log("[WS] message", data);
      const msg = JSON.parse(data);

      if (msg.type === "text") {
        const text = msg.text || "";
        setOutput(text);
        setHistory(h => [...h, { role: "jarvis", text, timestamp: Date.now() }]);
        if (msg.transcription) {
          setHistory(h => {
            const copy = [...h];
            // update last user message with real transcription
            for (let i = copy.length - 1; i >= 0; i--) {
              if (copy[i].role === "user") {
                copy[i] = { ...copy[i], text: msg.transcription };
                break;
              }
            }
            return copy;
          });
        }
      } else if (msg.type === "tts_blob") {
          if (ignoreIncomingAudioRef.current) {
            ignoreIncomingAudioRef.current = false;
            return;
          }

          playAudioBlob(msg.audio, msg.mime || "audio/wav");

        } else if (msg.type === "tts") {
          console.log("[TTS] received", msg.audio?.length);

          if (ignoreIncomingAudioRef.current) {
            ignoreIncomingAudioRef.current = false;
            return;
          }

          waveformModeRef.current = "ai";

          startStreamPlayback(msg.sample_rate || 24000);

          for (const chunk of msg.audio || []) {
            if (chunk?.audio) {
              queueAudioChunk(chunk.audio);
            }
          }
        } else if (msg.type === "audio_start") {
        if (ignoreIncomingAudioRef.current) return;
        startStreamPlayback(msg.sample_rate || 24000);
      } else if (msg.type === "audio_chunk") {
        if (ignoreIncomingAudioRef.current) return;
        queueAudioChunk(msg.audio);
      } else if (msg.type === "audio_end") {
        if (ignoreIncomingAudioRef.current) {
          ignoreIncomingAudioRef.current = false;
          stopPlayback();
          setState("listening");
        }
      }
    };
  }, [startStreamPlayback, queueAudioChunk, stopPlayback]);
  // ── VAD init ──
  useEffect(() => {
    let mediaStream: MediaStream | null = null;
    let audioStream: MediaStream | null = null;
    let videoStream: MediaStream | null = null;

    async function initVAD() {
  if (vadRef.current) return;

  let audioStream: MediaStream | null = null;
  let videoStream: MediaStream | null = null;

  try {
    // 1. Mic first. This is required.
    audioStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    // 2. Camera optional. If denied/busy, continue audio-only.
    try {
      videoStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" },
      });

      if (videoRef.current) {
        videoRef.current.srcObject = videoStream;
      }
    } catch (e) {
      console.warn("Camera denied/busy, continuing audio-only:", e);
    }

    mediaStream = new MediaStream([
      ...audioStream.getAudioTracks(),
      ...(videoStream ? videoStream.getVideoTracks() : []),
    ]);

    ensureAudioCtx();

    if (audioCtxRef.current?.state === "suspended") {
      await audioCtxRef.current.resume();
    }

    if (audioCtxRef.current && analyserRef.current) {
      micSourceRef.current =
        audioCtxRef.current.createMediaStreamSource(audioStream);

      micSourceRef.current.connect(analyserRef.current);
    }

    alwaysOnRef.current = true;
    setMicActive(true);
    setState("listening");

    connectParlour();

    const myvad = await MicVAD.new({
      getStream: async () =>
        new MediaStream(audioStream!.getAudioTracks()),

      positiveSpeechThreshold: 0.5,
      negativeSpeechThreshold: 0.25,
      redemptionMs: 600,
      minSpeechMs: 300,
      preSpeechPadMs: 300,
      onnxWASMBasePath: "/vad/",
      baseAssetPath: "/vad/",

      onSpeechStart: () => {
        if (!micEnabledRef.current) return;
        const BARGE_IN_GRACE_MS = 800;
        console.log("[VAD] speech start");

        waveformModeRef.current = "user";

        if (stateRef.current === "speaking") {
          if (Date.now() - speakingStartedAtRef.current < BARGE_IN_GRACE_MS) {
            return;
          }

          stopPlayback();
          ignoreIncomingAudioRef.current = true;
          parlourWsRef.current?.send(JSON.stringify({ type: "interrupt" }));
          setState("listening");
        }
      },

onSpeechEnd: (audio: Float32Array) => {
  if (!micEnabledRef.current) {
    waveformModeRef.current = "idle";
    setState("standby");
    return;
  }

  console.log("[VAD] speech end", audio.length);

  const ws = parlourWsRef.current;
  console.log("[WS] exists", !!ws, "state", ws?.readyState);

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.log("[WS] not connected, cannot send audio");
    setState("listening");
    return;
  }

  const wavBase64 = float32ToWavBase64(audio);
  console.log("[WS] wav length", wavBase64.length);

  const imageBase64 = captureFrame();

  setState("thinking");

  setHistory((h) => [
    ...h,
    { role: "user", text: "…", timestamp: Date.now() },
  ]);

  ws.send(
    JSON.stringify({
      type: "audio",
      audio: wavBase64,
      ...(imageBase64 ? { image: imageBase64 } : {}),
    })
  );

  console.log("[WS] sent audio");
},
    });

    vadRef.current = myvad;
    myvad.start();

    const syncVad = () => {
      if (vadRef.current) {
        vadRef.current.setOptions?.({
          positiveSpeechThreshold:
            stateRef.current === "speaking" ? 0.92 : 0.5,
        });
      }

      setTimeout(syncVad, 1000);
    };

    syncVad();
  } catch (e) {
    console.warn("VAD/mic init failed:", e);
  }
}

    initVAD();

    return () => {
      const vad = vadRef.current;
      vadRef.current = null;

      try {
        vad?.pause?.();
      } catch {}

      // Do NOT call destroy() in React dev/StrictMode.
      // It can throw: cannot release session. invalid session id
      // vad?.destroy?.();

      mediaStream?.getTracks().forEach((t) => t.stop());
      parlourWsRef.current?.close();
      parlourWsRef.current = null;
      stopPlayback();
      alwaysOnRef.current = false;
      setMicActive(false);
    };
  }, [connectParlour, float32ToWavBase64, captureFrame, stopPlayback, ensureAudioCtx]);

  // Disconnect mic from analyser when not listening
  //useEffect(() => {
  //  if (state !== "listening" && micSourceRef.current && analyserRef.current) {
  //    try { micSourceRef.current.disconnect(analyserRef.current); } catch {}
  //  }
  //}, [state]);
  function setAiSpeaking(isSpeaking: boolean) {
  if (isSpeaking) {
    vadRef.current?.pause?.();
    waveformModeRef.current = "ai";
    setState("speaking");
    return;
  }

  waveformModeRef.current = "idle";

  if (micEnabledRef.current) {
    vadRef.current?.start?.();
    setMicActive(true);
    setState("listening");
  } else {
    setMicActive(false);
    setState("standby");
  }
}
function handleVoiceToggle() {
  setMicEnabled((current) => {
    const next = !current;

    if (next) {
      vadRef.current?.start?.();
      setMicActive(true);
      setState("listening");
    } else {
      vadRef.current?.pause?.();
      setMicActive(false);

      waveformModeRef.current = "idle";
      setState("standby");

      if (stateRef.current === "speaking") {
        stopPlayback();
      }
    }

    return next;
  });
}
function handleCameraToggle() {
  setCameraEnabled((enabled) => !enabled);
}

function handleMuteToggle() {
  setMuted((m) => {
    const next = !m;

    if (next) {
      stopPlayback();
      parlourWsRef.current?.send(JSON.stringify({ type: "interrupt" }));
      setState(micEnabledRef.current ? "listening" : "standby");
    }

    return next;
  });
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
            {kokoroReady ? "KOKORO TTS ACTIVE" : "TEXT MODE"} &middot; {llamaCppReady ? "LLAMA.CPP LIVE" : "OLLAMA FALLBACK"} &middot; LOCAL AI ASSISTANT
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
                    kokoroReady ? "bg-green-400" : "bg-red-400/50"
                  }`}
                />
                <span className="text-[9px] tracking-[2px] uppercase opacity-50">
                  {kokoroReady ? "KOKORO TTS ONLINE" : "TTS OFFLINE"}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                <span className="text-[9px] tracking-[2px] uppercase opacity-50">
                  VAD + PARLOR WS
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

                <div className="absolute bottom-16 left-1/2 -translate-x-1/2 w-64 h-10 z-10 pointer-events-none">
                  <canvas
                    ref={waveformCanvasRef}
                    className="w-full h-full"
                    style={{
                      opacity: state === "standby" ? 0.3 : 0.85,
                      transition: "opacity 0.5s",
                    }}
                  />
                </div>

                <button
                  type="button"
                  className="absolute bottom-3 left-3 z-10 rounded-lg overflow-hidden border border-white/10 bg-black/40"
                  style={{ width: 120, height: 90, opacity: cameraEnabled ? 0.85 : 0.2 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setCameraEnabled((c) => !c);
                  }}
                  title={cameraEnabled ? "Disable camera frame" : "Enable camera frame"}
                >
                  <video
                    ref={videoRef}
                    autoPlay
                    muted
                    playsInline
                    className="w-full h-full object-cover scale-x-[-1]"
                  />
                </button>

                {state === "listening" && (
                  <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
                    <div className="text-red-400 text-[10px] tracking-[4px] uppercase state-listening flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
                      LISTENING &mdash; VAD ACTIVE
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
                    : "VAD/parlor offline or camera muted"}{" "}
                  &middot; Type below for text
                </p>
                  <div className="absolute bottom-3 left-15 flex gap-2 z-10">
<button
  onClick={handleMuteToggle}
  title={muted ? "Voice Output Muted" : "Voice Output Enabled"}
  className={`
    relative w-10 h-10 rounded-full border
    flex items-center justify-center
    transition-all duration-300
    ${
      muted
        ? "border-red-400/60 bg-red-500/10 text-red-400"
        : "border-green-400/60 bg-green-500/10 text-green-400 shadow-[0_0_12px_rgba(74,222,128,0.25)]"
    }
  `}
>
  {muted ? (
    <>
      {/* speaker */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19" />
        <line x1="22" y1="2" x2="2" y2="22" />
      </svg>

      <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-red-400" />
    </>
  ) : (
    <>
      {/* speaker on */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19" />
        <path d="M15.5 8.5a5 5 0 0 1 0 7" />
        <path d="M18.5 5.5a9 9 0 0 1 0 13" />
      </svg>

      <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-green-400 animate-pulse" />
    </>
  )}
</button>

<button
  onClick={handleCameraToggle}
  title={cameraEnabled ? "Camera Enabled" : "Camera Disabled"}
  className={`
    relative w-10 h-10 rounded-full border
    flex items-center justify-center
    transition-all duration-300
    ${
      cameraEnabled
        ? "border-green-400/60 bg-green-500/10 text-green-400 shadow-[0_0_12px_rgba(74,222,128,0.25)]"
        : "border-red-400/60 bg-red-500/10 text-red-400"
    }
  `}
>
  {cameraEnabled ? (
    <>
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M23 7l-7 5 7 5V7z" />
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
      </svg>

      <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-green-400 animate-pulse" />
    </>
  ) : (
    <>
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M23 7l-7 5 7 5V7z" />
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
        <line x1="22" y1="2" x2="2" y2="22" />
      </svg>

      <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-red-400" />
    </>
  )}</button>
  <button
   type="button"
  onClick={handleVoiceToggle}
  title={micEnabled ? "Microphone Enabled" : "Microphone Disabled"}
  className={`
    relative w-10 h-10 rounded-full border
    flex items-center justify-center
    transition-all duration-300
    ${
      micEnabled
        ? "border-green-400/60 bg-green-500/10 text-green-400 shadow-[0_0_12px_rgba(74,222,128,0.25)]"
        : "border-red-400/60 bg-red-500/10 text-red-400"
    }
  `}
>
  {micEnabled ? (
    <>
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
      </svg>

      <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-green-400 animate-pulse" />
    </>
  ) : (
    <>
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />

        {/* disable slash */}
        <line x1="22" y1="2" x2="2" y2="22" />
      </svg>

      <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-red-400" />
    </>
  )}

</button>
       
      
</div>
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
                { name: "REACT SERVER (7900)", status: reactServerReady },
                { name: "OLLAMA", status: Boolean(reactServerHealth?.ollama_ready) },
                { name: "LLAMA.CPP (8081)", status: llamaCppReady },
                { name: "KOKORO TTS (5100)", status: kokoroReady },
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