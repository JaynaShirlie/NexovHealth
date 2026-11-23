import { useCallback, useEffect, useRef, useState } from "react";
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { fetchHealth } from "./api";
import { audioCtx, playConnected, playEnd, startRing, stopRing } from "./sounds";

export type CallStatus = "idle" | "ringing" | "connected" | "ended";
/** A transcript bubble. Bot bubbles collect the sentences (segments) of one reply. */
export type Msg = { id: number; role: "user" | "bot"; text: string; final: boolean; segs?: Record<number, string> };
export type Analysers = { bot: AnalyserNode | null; user: AnalyserNode | null };

const CONNECT_TIMEOUT_MS = 30000;
const MIN_RING_MS = 2400; // let the ring be heard even when the connection is fast

function analyser(stream: MediaStream): AnalyserNode {
  const ac = audioCtx();
  const a = ac.createAnalyser();
  a.fftSize = 128;
  ac.createMediaStreamSource(stream).connect(a);
  return a;
}

export function useCall() {
  const [status, setStatus] = useState<CallStatus>("idle");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [speaking, setSpeaking] = useState<"bot" | "user" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);

  const client = useRef<PipecatClient | null>(null);
  const audioEl = useRef<HTMLAudioElement | null>(null);
  const analysers = useRef<Analysers>({ bot: null, user: null });
  const nextId = useRef(1);
  const secondsRef = useRef(0);
  const mutedRef = useRef(false);
  // Every call gets a generation number; callbacks and timers from an older call are ignored.
  const gen = useRef(0);
  const live = useRef(false);
  const connectTimer = useRef<number | null>(null);

  useEffect(() => {
    if (status !== "connected") return;
    secondsRef.current = 0;
    setSeconds(0);
    const t = window.setInterval(() => { secondsRef.current += 1; setSeconds(secondsRef.current); }, 1000);
    return () => clearInterval(t);
  }, [status]);

  // Hang up cleanly if the tab is closed or reloaded mid-call (frees the server-side bot at once).
  useEffect(() => {
    const bye = () => { client.current?.disconnect().catch(() => {}); };
    window.addEventListener("pagehide", bye);
    return () => { window.removeEventListener("pagehide", bye); bye(); };
  }, []);

  const addUser = useCallback((text: string, final: boolean) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === "user" && !last.final) return [...prev.slice(0, -1), { ...last, text, final }];
      return [...prev, { id: nextId.current++, role: "user", text, final }];
    });
  }, []);

  const addBot = useCallback((seg: number, text: string, done: boolean) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      const base = last?.role === "bot" ? last : null;
      const segs = { ...(base?.segs ?? {}), [seg]: text };
      const msg: Msg = {
        id: base?.id ?? nextId.current++, role: "bot", segs,
        text: Object.keys(segs).map(Number).sort((a, b) => a - b).map((k) => segs[k]).join(" "),
        final: done,
      };
      return base ? [...prev.slice(0, -1), msg] : [...prev, msg];
    });
  }, []);

  const finish = useCallback((message?: string) => {
    if (!live.current) return;
    live.current = false;
    if (connectTimer.current) clearTimeout(connectTimer.current);
    stopRing();
    playEnd();
    setDuration(secondsRef.current);
    if (message) setError(message);
    setSpeaking(null);
    setStatus("ended");
    analysers.current = { bot: null, user: null };
    audioEl.current?.pause();
    client.current?.disconnect().catch(() => {});
  }, []);

  const start = useCallback(async () => {
    const my = ++gen.current;
    const mine = () => my === gen.current && live.current;
    live.current = true;
    setMessages([]);
    setError(null);
    setMuted(false);
    mutedRef.current = false;
    setSeconds(0);
    secondsRef.current = 0;
    setStatus("ringing");
    const startedAt = Date.now();
    audioCtx().resume();
    startRing();

    // Preflight: give a precise reason instead of ringing into the void.
    try {
      const h = await fetchHealth();
      if (!h.configured) return finish(`The agent is not configured: add ${h.missing.join(" and ")} to backend/.env.`);
      if (h.active_calls >= h.max_calls) return finish("All lines are busy. Try again in a moment.");
    } catch {
      return finish("Can't reach the clinic server. Is the backend running?");
    }
    if (!mine()) return;

    const audio = new Audio();
    audio.autoplay = true;
    audioEl.current = audio;

    const c = new PipecatClient({
      transport: new SmallWebRTCTransport({ webrtcRequestParams: { endpoint: "/api/offer" } }),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onBotReady: async () => {
          await new Promise((r) => setTimeout(r, Math.max(0, MIN_RING_MS - (Date.now() - startedAt))));
          if (!mine()) return;
          if (connectTimer.current) clearTimeout(connectTimer.current);
          stopRing();
          playConnected();
          setStatus("connected");
        },
        onDisconnected: () => { if (my === gen.current) finish(); },
        onDeviceError: () => { if (mine()) finish("Microphone blocked. Allow mic access and try again."); },
        onError: () => { if (mine()) finish("The call dropped. Please try again."); },
        onBotStartedSpeaking: () => { if (mine()) setSpeaking("bot"); },
        onBotStoppedSpeaking: () => { if (mine()) setSpeaking((s) => (s === "bot" ? null : s)); },
        onUserStartedSpeaking: () => { if (mine()) setSpeaking("user"); },
        onUserStoppedSpeaking: () => { if (mine()) setSpeaking((s) => (s === "user" ? null : s)); },
        onUserTranscript: (d) => { if (mine() && d.text?.trim()) addUser(d.text.trim(), !!d.final); },
        onBotOutput: (d) => {
          // One sentence arrives as "new", then word-progress updates, then "completed".
          const type = String(d.output_type ?? d.aggregated_by ?? "sentence");
          if (!mine() || ["word", "token", "backchannel"].includes(type) || !d.text?.trim()) return;
          addBot(d.segment_id ?? -1, d.text.trim(), d.spoken_status !== "new" && d.spoken_status !== "in-progress");
        },
        onTrackStarted: (track, p) => {
          if (!mine() || track.kind !== "audio") return;
          const stream = new MediaStream([track]);
          if (p?.local) {
            analysers.current.user = analyser(stream);
          } else {
            audio.srcObject = stream;
            analysers.current.bot = analyser(stream);
          }
        },
      },
    });
    client.current = c;
    connectTimer.current = window.setTimeout(() => {
      if (mine()) finish("The agent did not answer. Check the backend log and API keys.");
    }, CONNECT_TIMEOUT_MS);
    try {
      await c.connect();
    } catch (e) {
      if (mine()) finish(/429|busy/i.test(String(e)) ? "All lines are busy. Try again in a moment." : "Could not connect the call. Check your mic and network.");
    }
  }, [addUser, addBot, finish]);

  const end = useCallback(() => finish(), [finish]);

  const toggleMute = useCallback(() => {
    mutedRef.current = !mutedRef.current;
    client.current?.enableMic(!mutedRef.current);
    setMuted(mutedRef.current);
  }, []);

  // Closing the phone keeps the transcript, so the dashboard can show the last call.
  const close = useCallback(() => {
    setStatus("idle");
    setError(null);
  }, []);

  return { status, messages, muted, seconds, duration, speaking, error, analysers, start, end, toggleMute, close };
}
