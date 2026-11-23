export type Slot = { id: number; start: string };
export type Doctor = { id: number; name: string; speciality: string; bio: string; initials: string; slots: Slot[] };
export type Appointment = {
  id: number; phone: string; patient_name: string; status: "booked" | "cancelled";
  doctor_name: string; speciality: string; initials: string; start: string; created_at: string;
};
export type Health = {
  ok: boolean; configured: boolean; missing: string[]; llm: string; active_calls: number; max_calls: number;
  clinic_now: string; timezone: string; // the server's clinic clock, so the dashboard and Aria agree on "today"
};
export type LiveEvent = { type: "booked" | "cancelled" | "reset"; appointment?: Appointment };

const get = async <T,>(url: string): Promise<T> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url);
  return r.json();
};

export const fetchHealth = () => get<Health>("/api/health");
export const fetchDoctors = () => get<Doctor[]>("/api/doctors");
export const fetchAppointments = () => get<Appointment[]>("/api/appointments");
export const resetDemo = () => fetch("/api/reset", { method: "POST" });

// ---- formatting ----
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
export const fmtDay = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
export const dayKey = (iso: string) => iso.slice(0, 10);
/** "2026-11-24" -> local midnight (avoids the UTC shift of new Date("2026-11-24")). */
export const dayDate = (key: string) => new Date(`${key}T00:00`);
export const todayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
export const fmtPhone = (p: string) => (p.length === 10 ? `+91 ${p.slice(0, 5)} ${p.slice(5)}` : p);
export const fmtClock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
