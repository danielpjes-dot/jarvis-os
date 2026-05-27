"use client";

import { useEffect, useRef, useState } from "react";
import { MicVAD } from "@ricky0123/vad-web";
import * as ort from "onnxruntime-web";

type Props = {
  wsUrl?: string;
};

export default function Parlor({
  wsUrl = "ws://127.0.0.1:8000/ws",
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const waveformCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const vadRef = useRef<any>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);

  const mediaStreamRef = useRef<MediaStream | null>(null);

  const streamSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const streamNextTimeRef = useRef(0);

  const [connected, setConnected] = useState(false);
  const [cameraEnabled, setCameraEnabled] = useState(true);
  const [messages, setMessages] = useState<
    { role: "user" | "assistant"; text: string }[]
  >([]);

  const [state, setState] = useState<
    "loading" | "listening" | "processing" | "speaking"
  >("loading");

  // ─────────────────────────────────────────────
  // Audio
  // ─────────────────────────────────────────────

  function ensureAudioCtx() {
    if (!audioCtxRef.current) {
      const ctx = new AudioContext();

      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.75;

      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
    }
  }

  // ─────────────────────────────────────────────
  // Waveform
  // ─────────────────────────────────────────────

  useEffect(() => {
    const canvas = waveformCanvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Keep non-null aliases for nested functions.
    // TypeScript does not always preserve null narrowing inside closures.
    const canvasEl: HTMLCanvasElement = canvas;
    const ctx2d: CanvasRenderingContext2D = ctx;

    let raf = 0;

    function resize() {
      const rect = canvasEl.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;

      canvasEl.width = rect.width * dpr;
      canvasEl.height = rect.height * dpr;

      // Reset transform before scaling, otherwise every resize compounds the scale.
      ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    resize();
    window.addEventListener("resize", resize);

    const BAR_COUNT = 40;
    const BAR_GAP = 3;

    function draw() {
      const rect = canvasEl.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;

      ctx2d.clearRect(0, 0, w, h);

      const barWidth = (w - (BAR_COUNT - 1) * BAR_GAP) / BAR_COUNT;

      let dataArray: Uint8Array<ArrayBuffer> | null = null;

      const analyser = analyserRef.current;
      if (analyser) {
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(dataArray);
      }

      for (let i = 0; i < BAR_COUNT; i++) {
        let amplitude = 0.04;

        if (dataArray) {
          const binIndex = Math.floor(
            (i / BAR_COUNT) * dataArray.length * 0.6
          );

          amplitude = dataArray[binIndex] / 255;
        }

        const barH = Math.max(2, amplitude * (h - 4));

        const x = i * (barWidth + BAR_GAP);
        const y = (h - barH) / 2;

        ctx2d.fillStyle =
          state === "speaking"
            ? "#818cf8"
            : state === "processing"
              ? "#f59e0b"
              : "#4ade80";

        ctx2d.globalAlpha = 0.3 + amplitude * 0.7;

        ctx2d.beginPath();

        const r = Math.min(barWidth / 2, barH / 2, 3);

        if (typeof ctx2d.roundRect === "function") {
          ctx2d.roundRect(x, y, barWidth, barH, r);
        } else {
          ctx2d.rect(x, y, barWidth, barH);
        }

        ctx2d.fill();
      }

      raf = requestAnimationFrame(draw);
    }

    draw();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [state]);

  // ─────────────────────────────────────────────
  // Playback
  // ─────────────────────────────────────────────

  function stopPlayback() {
    for (const src of streamSourcesRef.current) {
      try {
        src.stop();
      } catch {}
    }

    streamSourcesRef.current = [];
    streamNextTimeRef.current = 0;
  }

  function startPlayback() {
    ensureAudioCtx();

    const ctx = audioCtxRef.current!;

    if (ctx.state === "suspended") {
      ctx.resume();
    }

    streamNextTimeRef.current = ctx.currentTime + 0.05;

    setState("speaking");
  }

  function queueAudioChunk(base64Pcm: string, sampleRate = 24000) {
    ensureAudioCtx();

    const ctx = audioCtxRef.current!;
    const analyser = analyserRef.current!;

    const bin = atob(base64Pcm);

    const bytes = new Uint8Array(bin.length);

    for (let i = 0; i < bin.length; i++) {
      bytes[i] = bin.charCodeAt(i);
    }

    const int16 = new Int16Array(bytes.buffer);

    const float32 = new Float32Array(int16.length);

    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, sampleRate);

    audioBuffer.getChannelData(0).set(float32);

    const source = ctx.createBufferSource();

    source.buffer = audioBuffer;

    source.connect(ctx.destination);
    source.connect(analyser);

    const startAt = Math.max(
      streamNextTimeRef.current,
      ctx.currentTime
    );

    source.start(startAt);

    streamNextTimeRef.current =
      startAt + audioBuffer.duration;

    streamSourcesRef.current.push(source);

    source.onended = () => {
      streamSourcesRef.current =
        streamSourcesRef.current.filter((s) => s !== source);

      if (
        streamSourcesRef.current.length === 0 &&
        state === "speaking"
      ) {
        setState("listening");
      }
    };
  }

  // ─────────────────────────────────────────────
  // WAV
  // ─────────────────────────────────────────────

  function float32ToWavBase64(samples: Float32Array) {
    const buf = new ArrayBuffer(44 + samples.length * 2);

    const v = new DataView(buf);

    const w = (o: number, s: string) => {
      for (let i = 0; i < s.length; i++) {
        v.setUint8(o + i, s.charCodeAt(i));
      }
    };

    w(0, "RIFF");

    v.setUint32(4, 36 + samples.length * 2, true);

    w(8, "WAVE");
    w(12, "fmt ");

    v.setUint32(16, 16, true);
    v.setUint16(20, 1, true);
    v.setUint16(22, 1, true);

    v.setUint32(24, 16000, true);
    v.setUint32(28, 32000, true);

    v.setUint16(32, 2, true);
    v.setUint16(34, 16, true);

    w(36, "data");

    v.setUint32(40, samples.length * 2, true);

    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));

      v.setInt16(
        44 + i * 2,
        s < 0 ? s * 0x8000 : s * 0x7fff,
        true
      );
    }

    const bytes = new Uint8Array(buf);

    let bin = "";

    for (let i = 0; i < bytes.length; i++) {
      bin += String.fromCharCode(bytes[i]);
    }

    return btoa(bin);
  }

  // ─────────────────────────────────────────────
  // Main init
  // ─────────────────────────────────────────────

  useEffect(() => {
    let mounted = true;

    async function init() {
      try {
        ensureAudioCtx();

        const mediaStream =
          await navigator.mediaDevices.getUserMedia({
            video: {
              width: 640,
              height: 480,
              facingMode: "user",
            },
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          });

        mediaStreamRef.current = mediaStream;

        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
        }

        const ws = new WebSocket(wsUrl);

        wsRef.current = ws;

        ws.onopen = () => {
          if (!mounted) return;

          setConnected(true);
          setState("listening");
        };

        ws.onclose = () => {
          setConnected(false);
        };

        ws.onmessage = ({ data }) => {
          const msg = JSON.parse(data);

          if (msg.type === "text") {
            setMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                text: msg.text,
              },
            ]);
          }

          if (msg.type === "audio_start") {
            startPlayback();
          }

          if (msg.type === "audio_chunk") {
            queueAudioChunk(
              msg.audio,
              msg.sample_rate || 24000
            );
          }

          if (msg.type === "audio_end") {
          }
        };

        const myvad = await MicVAD.new({
          getStream: async () =>
            new MediaStream(mediaStream.getAudioTracks()),

          positiveSpeechThreshold: 0.5,
          negativeSpeechThreshold: 0.25,

          redemptionMs: 600,
          minSpeechMs: 300,
          preSpeechPadMs: 300,

          baseAssetPath: "/vad/",
          onnxWASMBasePath: "/vad/",

          onSpeechStart: () => {
            if (state !== "speaking") {
              setState("listening");
            }
          },

          onSpeechEnd: (audio: Float32Array) => {
            if (
              !wsRef.current ||
              wsRef.current.readyState !== WebSocket.OPEN
            ) {
              return;
            }

            setState("processing");

            setMessages((prev) => [
              ...prev,
              {
                role: "user",
                text: "🎤 Voice input",
              },
            ]);

            wsRef.current.send(
              JSON.stringify({
                audio: float32ToWavBase64(audio),
              })
            );
          },
        });

        vadRef.current = myvad;

        myvad.start();

        setState("listening");
      } catch (e) {
        console.error(e);
      }
    }

    init();

    return () => {
      mounted = false;

      try {
        vadRef.current?.pause?.();
      } catch {}

      wsRef.current?.close();

      mediaStreamRef.current
        ?.getTracks()
        .forEach((t) => t.stop());

      stopPlayback();
    };
  }, [wsUrl]);

  return (
    <div className="w-full h-full flex flex-col items-center justify-center bg-black text-white overflow-hidden">
      <div className="w-full max-w-5xl flex flex-col items-center px-4 py-4 gap-4 h-full">
        <div className="flex items-center gap-3 text-xs uppercase tracking-[3px] opacity-70">
          <div
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-green-400" : "bg-red-400"
            }`}
          />

          <span>{connected ? "Connected" : "Disconnected"}</span>

          <span className="opacity-40">
            {state.toUpperCase()}
          </span>
        </div>

        <div className="relative w-full max-w-3xl aspect-video rounded-3xl overflow-hidden border border-white/10">
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className="w-full h-full object-cover scale-x-[-1]"
          />

          <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
        </div>

        <div className="w-full max-w-xl h-16">
          <canvas
            ref={waveformCanvasRef}
            className="w-full h-full"
          />
        </div>

        <div className="flex-1 w-full max-w-3xl overflow-y-auto flex flex-col gap-2 px-2">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm ${
                m.role === "user"
                  ? "self-end bg-green-500/10"
                  : "self-start bg-white/5"
              }`}
            >
              {m.text}
            </div>
          ))}
        </div>

        <div className="flex items-center gap-3 pb-4">
          <button
            onClick={() =>
              setCameraEnabled((c) => !c)
            }
            className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs uppercase tracking-[2px]"
          >
            {cameraEnabled ? "Camera On" : "Camera Off"}
          </button>
        </div>
      </div>
    </div>
  );
}