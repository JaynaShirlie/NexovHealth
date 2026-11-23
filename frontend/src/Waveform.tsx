import { useEffect, useRef } from "react";
import type { Analysers } from "./useCall";

/** Bars that react to whichever side (caller or Aria) is louder. */
export default function Waveform({ analysers, active }: { analysers: React.MutableRefObject<Analysers>; active: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current!;
    const g = canvas.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    g.scale(dpr, dpr);
    const BARS = 27;
    const level = new Array(BARS).fill(0);
    const buf = new Uint8Array(64);
    let raf = 0;
    const read = (a: AnalyserNode | null) => {
      if (!a) return 0;
      a.getByteFrequencyData(buf);
      let s = 0;
      for (let i = 0; i < 24; i++) s += buf[i];
      return s / 24 / 255;
    };

    const draw = (t: number) => {
      const bot = read(analysers.current.bot), user = read(analysers.current.user);
      const botWins = bot >= user;
      const energy = active ? Math.max(bot, user) : 0;
      g.clearRect(0, 0, W, H);
      const bw = W / BARS;
      for (let i = 0; i < BARS; i++) {
        const mid = 1 - Math.abs(i - (BARS - 1) / 2) / ((BARS - 1) / 2); // taller in the middle
        const wob = 0.5 + 0.5 * Math.sin(t / 170 + i * 0.7);
        const target = 0.06 + energy * (0.35 + 0.65 * wob) * (0.35 + 0.65 * mid) * 1.8;
        level[i] += (target - level[i]) * 0.25;
        const h = Math.max(4, Math.min(1, level[i]) * H);
        g.fillStyle = botWins ? "#9FDDB8" : "#F2B38F";
        g.globalAlpha = active ? 0.95 : 0.35;
        const x = i * bw + bw * 0.18, w = bw * 0.64;
        g.beginPath();
        g.roundRect(x, (H - h) / 2, w, h, w / 2);
        g.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [analysers, active]);

  return <canvas ref={ref} className="wave" aria-hidden />;
}
