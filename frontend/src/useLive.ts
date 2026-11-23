import { useCallback, useEffect, useRef, useState } from "react";
import { Appointment, Doctor, Health, LiveEvent, fetchAppointments, fetchDoctors, fetchHealth } from "./api";

/** Dashboard data. Refreshes instantly on server-sent events from the voice tools. */
export function useLive() {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [flash, setFlash] = useState<Record<number, "booked" | "cancelled">>({});
  const [lastEvent, setLastEvent] = useState<LiveEvent | null>(null);
  const [online, setOnline] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const timers = useRef<number[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [d, a, h] = await Promise.all([fetchDoctors(), fetchAppointments(), fetchHealth()]);
      setDoctors(d);
      setAppointments(a);
      setHealth(h);
      setOnline(true);
    } catch {
      setOnline(false);
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const poll = window.setInterval(refresh, 15000);
    const es = new EventSource("/api/events");
    es.onmessage = (m) => {
      const ev: LiveEvent = JSON.parse(m.data);
      refresh();
      if (ev.type === "reset") return;
      setLastEvent({ ...ev });
      const id = ev.appointment?.id;
      if (id) {
        setFlash((f) => ({ ...f, [id]: ev.type as "booked" | "cancelled" }));
        timers.current.push(window.setTimeout(() => setFlash((f) => { const n = { ...f }; delete n[id]; return n; }), 4200));
      }
    };
    es.onerror = () => setOnline(false);
    es.onopen = () => setOnline(true);
    return () => {
      clearInterval(poll);
      es.close();
      timers.current.forEach(clearTimeout);
    };
  }, [refresh]);

  return { doctors, appointments, flash, lastEvent, online, health, refresh };
}
