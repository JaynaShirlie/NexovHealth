import { useEffect, useLayoutEffect, useRef } from "react";
import type { Msg } from "./useCall";

/**
 * Chat-style transcript. It scrolls only its own box (never the page), and only follows new
 * messages while the reader is already at the bottom, so scrolling up to re-read isn't hijacked.
 */
export default function Transcript({ messages, compact = false }: { messages: Msg[]; compact?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const el = box.current!;
    const onScroll = () => { pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useLayoutEffect(() => {
    const el = box.current;
    if (el && pinned.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  return (
    <div ref={box} className={`transcript ${compact ? "compact" : ""}`} aria-live="polite">
      {messages.map((m) => (
        <div key={m.id} className={`bubble ${m.role} ${m.final ? "" : "interim"}`}>
          {!compact && <span className="who">{m.role === "bot" ? "Aria" : "Caller"}</span>}
          {m.text}
        </div>
      ))}
    </div>
  );
}
