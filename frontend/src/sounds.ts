/** Ring and end-call tones, synthesised with WebAudio (no asset files). */
let ctx: AudioContext | null = null;
let ringTimer: number | null = null;

export const audioCtx = () => (ctx ??= new AudioContext());

function tone(freqs: number[], start: number, dur: number, gain = 0.08) {
  const c = audioCtx();
  const g = c.createGain();
  g.gain.setValueAtTime(0, c.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, c.currentTime + start + 0.02);
  g.gain.setValueAtTime(gain, c.currentTime + start + dur - 0.05);
  g.gain.linearRampToValueAtTime(0, c.currentTime + start + dur);
  g.connect(c.destination);
  freqs.forEach((f) => {
    const o = c.createOscillator();
    o.type = "sine";
    o.frequency.value = f;
    o.connect(g);
    o.start(c.currentTime + start);
    o.stop(c.currentTime + start + dur + 0.02);
  });
}

export function startRing() {
  stopRing();
  const burst = () => { tone([440, 480], 0, 0.9); tone([440, 480], 1.1, 0.9); };
  burst();
  ringTimer = window.setInterval(burst, 3200);
}
export function stopRing() {
  if (ringTimer) clearInterval(ringTimer);
  ringTimer = null;
}
export function playConnected() { tone([660], 0, 0.12, 0.06); tone([880], 0.14, 0.16, 0.06); }
export function playEnd() { tone([480], 0, 0.18, 0.07); tone([360], 0.2, 0.18, 0.07); tone([260], 0.4, 0.28, 0.07); }
