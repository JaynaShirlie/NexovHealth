import { useEffect, useRef, useState } from "react";
import { LiveEvent, fmtClock, fmtDay, fmtPhone, fmtTime } from "./api";
import type { useCall } from "./useCall";
import Waveform from "./Waveform";
import Transcript from "./Transcript";

type Call = ReturnType<typeof useCall>;

const Icon = {
  mic: <svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0M12 17v4" /></svg>,
  micOff: <svg viewBox="0 0 24 24"><path d="M3 3l18 18M9 9v3a3 3 0 0 0 5.1 2.1M15 10V6a3 3 0 0 0-5.8-1M17 12a5 5 0 0 1-.6 2.4M12 17v4" /></svg>,
  end: <svg viewBox="0 0 24 24"><path d="M3 14.5c5-4.6 13-4.6 18 0l-2.4 2.3-3-1.5v-2.6c-2-.7-4.2-.7-6.2 0v2.6l-3 1.5Z" /></svg>,
};

export default function Phone({ call, lastEvent }: { call: Call; lastEvent: LiveEvent | null }) {
  const { status, messages, muted, seconds, duration, speaking, error, analysers } = call;
  const [card, setCard] = useState<LiveEvent | null>(null);
  const seen = useRef<LiveEvent | null>(null);

  useEffect(() => {
    if (!lastEvent || lastEvent === seen.current || status !== "connected") return;
    seen.current = lastEvent;
    setCard(lastEvent);
    const t = window.setTimeout(() => setCard(null), 12000);
    return () => clearTimeout(t);
  }, [lastEvent, status]);
  useEffect(() => { if (status === "ringing") setCard(null); }, [status]);

  if (status === "idle") return null;
  const a = card?.appointment;

  return (
    <div className="phone-layer" role="dialog" aria-label="Call with Aria">
      <div className="scrim" onClick={status === "ended" ? call.close : undefined} />
      <div className={`phone s-${status}`}>
        <div className="notch" />
        <div className="screen">
          <header className="ph-head">
            <div className={`ph-avatar ${speaking === "bot" ? "talk" : ""}`}>
              <span>A</span>
              {status === "ringing" && <i className="ring r1" />}
              {status === "ringing" && <i className="ring r2" />}
            </div>
            <div className="ph-name">Aria</div>
            <div className="ph-sub">
              {status === "ringing" && <span className="blink">Calling Nexov Health…</span>}
              {status === "connected" && <><span className="live-dot" /> {fmtClock(seconds)}</>}
              {status === "ended" && <>Call ended · {fmtClock(duration)}</>}
            </div>
          </header>

          {status === "connected" && (
            <>
              <Waveform analysers={analysers} active={!!speaking} />
              <Transcript messages={messages} compact />
              {a && (
                <div className={`confirm ${card?.type}`} key={a.id + card!.type}>
                  <div className="confirm-top">
                    <span className="tick">{card?.type === "booked" ? "✓" : "×"}</span>
                    <b>{card?.type === "booked" ? "Appointment booked" : "Appointment cancelled"}</b>
                  </div>
                  <div className="confirm-doc">{a.doctor_name}</div>
                  <div className="confirm-meta">{a.speciality} · {fmtDay(a.start)}, {fmtTime(a.start)}</div>
                  <div className="confirm-meta">{a.patient_name} · {fmtPhone(a.phone)}</div>
                </div>
              )}
              <div className="controls">
                <button className={`ctl ${muted ? "on" : ""}`} onClick={call.toggleMute} aria-pressed={muted}>
                  {muted ? Icon.micOff : Icon.mic}
                  <span>{muted ? "Unmute" : "Mute"}</span>
                </button>
                <button className="ctl end" onClick={call.end}>{Icon.end}<span>End</span></button>
              </div>
            </>
          )}

          {status === "ringing" && (
            <div className="controls single">
              <button className="ctl end" onClick={call.end}>{Icon.end}<span>Cancel</span></button>
            </div>
          )}

          {status === "ended" && (
            <div className="ended">
              {error && <p className="err">{error}</p>}
              {messages.length > 0 && <Transcript messages={messages} compact />}
              <div className="ended-actions">
                <button className="btn primary" onClick={call.start}>Call again</button>
                <button className="btn ghost-light" onClick={call.close}>Close</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
