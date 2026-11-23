import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Appointment, Doctor, dayDate, dayKey, fmtClock, fmtPhone, fmtTime, resetDemo, todayKey } from "./api";
import { useCall } from "./useCall";
import { useLive } from "./useLive";
import Phone from "./Phone";
import Transcript from "./Transcript";

/* ---------- icons (inline, 1.8px strokes) ---------- */
const I = {
  grid: <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />,
  steth: <path d="M6 3v6a5 5 0 0 0 10 0V3M11 14v2a5 5 0 0 0 10 0v-2M21 12a2 2 0 1 0 0-.01" />,
  cal: <path d="M4 6h16v14H4zM4 10h16M8 3v5M16 3v5" />,
  wave: <path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2" />,
  phone: <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />,
  reset: <path d="M4 4v6h6M20 20v-6h-6M5.5 15a7 7 0 0 0 12.3 2.2M18.5 9A7 7 0 0 0 6.2 6.8" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  users: <path d="M16 20v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20M9.5 10.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M21 20v-1.5a4 4 0 0 0-3-3.9M15.5 3.6a3.5 3.5 0 0 1 0 6.8" />,
};
const Icon = ({ d, className = "" }: { d: ReactNode; className?: string }) => (
  <svg className={`ic ${className}`} viewBox="0 0 24 24" aria-hidden>{d}</svg>
);

const NAV = [
  { id: "overview", label: "Overview", icon: I.grid },
  { id: "availability", label: "Availability", icon: I.steth },
  { id: "appointments", label: "Appointments", icon: I.cal },
  { id: "agent", label: "Voice agent", icon: I.wave },
];

/* ---------- sections ---------- */

function Availability({ doctors, today }: { doctors: Doctor[]; today: string }) {
  const days = useMemo(() => {
    const set = new Set<string>();
    doctors.forEach((d) => d.slots.forEach((s) => set.add(dayKey(s.start))));
    return [...set].sort().slice(0, 7);
  }, [doctors]);
  const [day, setDay] = useState<string | null>(null);
  const [spec, setSpec] = useState("All");
  const active = day && days.includes(day) ? day : days[0];
  const specs = useMemo(() => ["All", ...new Set(doctors.map((d) => d.speciality))], [doctors]);
  const rows = doctors
    .filter((d) => spec === "All" || d.speciality === spec)
    .map((d) => ({ d, slots: d.slots.filter((s) => dayKey(s.start) === active) }));

  return (
    <section className="card" id="availability">
      <header className="card-head">
        <div>
          <h2>Doctor availability</h2>
          <p className="sub">Open slots update live as Aria books and cancels.</p>
        </div>
        <select className="select" value={spec} onChange={(e) => setSpec(e.target.value)} aria-label="Filter by speciality">
          {specs.map((s) => <option key={s} value={s}>{s === "All" ? "All specialities" : s}</option>)}
        </select>
      </header>

      <div className="days" role="tablist" aria-label="Day">
        {days.map((k) => {
          const dt = dayDate(k);
          return (
            <button key={k} role="tab" aria-selected={k === active} className={k === active ? "on" : ""} onClick={() => setDay(k)}>
              <span>{k === today ? "Today" : dt.toLocaleDateString("en-US", { weekday: "short" })}</span>
              <b>{dt.getDate()}</b>
              <small>{dt.toLocaleDateString("en-US", { month: "short" })}</small>
            </button>
          );
        })}
      </div>

      <ul className="sched">
        {doctors.length === 0 && <li className="empty">Loading schedule…</li>}
        {rows.map(({ d, slots }) => (
          <li key={d.id} className="sched-row">
            <div className="who">
              <span className="avatar">{d.initials}</span>
              <div>
                <div className="name">{d.name}</div>
                <div className="meta">{d.speciality}</div>
              </div>
            </div>
            <div className="slots">
              {slots.length === 0
                ? <span className="muted">No openings this day</span>
                : slots.map((s) => <span key={s.id} className="slot">{fmtTime(s.start)}</span>)}
            </div>
            <div className="count">{slots.length > 0 && <>{slots.length}<small> open</small></>}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

type Tab = "upcoming" | "cancelled" | "all";

function Appointments({ items, flash, now }: { items: Appointment[]; flash: Record<number, "booked" | "cancelled">; now: string }) {
  const [tab, setTab] = useState<Tab>("upcoming");
  const upcoming = items.filter((a) => a.status === "booked" && a.start >= now).sort((a, b) => a.start.localeCompare(b.start));
  const cancelled = items.filter((a) => a.status === "cancelled");
  const list = tab === "upcoming" ? upcoming : tab === "cancelled" ? cancelled : items;
  const tabs: [Tab, string][] = [["upcoming", `Upcoming · ${upcoming.length}`], ["cancelled", `Cancelled · ${cancelled.length}`], ["all", "All"]];

  return (
    <section className="card" id="appointments">
      <header className="card-head">
        <div>
          <h2>Appointments</h2>
          <p className="sub">Patients are identified by the phone number they give Aria.</p>
        </div>
        <div className="seg" role="tablist">
          {tabs.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </header>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>Patient</th><th>Doctor</th><th>Date & time</th><th>Status</th></tr>
          </thead>
          <tbody>
            {list.length === 0 && <tr><td colSpan={4} className="empty">No appointments here yet.</td></tr>}
            {list.map((a) => {
              const d = new Date(a.start);
              return (
                <tr key={a.id} className={`${a.status} ${flash[a.id] ? "flash-" + flash[a.id] : ""}`}>
                  <td data-label="Patient">
                    <div className="name">{a.patient_name}</div>
                    <div className="meta mono">{fmtPhone(a.phone)}</div>
                  </td>
                  <td data-label="Doctor">
                    <div className="doc-cell"><span className="avatar sm">{a.initials}</span>
                      <div><div className="name">{a.doctor_name}</div><div className="meta">{a.speciality}</div></div>
                    </div>
                  </td>
                  <td data-label="When">
                    <div className="name">{d.toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short" })}</div>
                    <div className="meta">{fmtTime(a.start)}</div>
                  </td>
                  <td data-label="Status"><span className={`badge ${a.status}`}>{a.status === "booked" ? "Confirmed" : "Cancelled"}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Browser fallback for "YYYY-MM-DDTHH:MM" when the server clock isn't known yet. */
function localNow() {
  const d = new Date();
  return `${todayKey()}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/* ---------- page ---------- */

export default function App() {
  const call = useCall();
  const { doctors, appointments, flash, lastEvent, online, health } = useLive();
  const ready = online && !!health?.configured;
  const inCall = call.status !== "idle";
  const live = call.status === "ringing" || call.status === "connected";
  const [nav, setNav] = useState("overview");

  // Clinic clock from the server keeps "today" identical for Aria and the dashboard.
  const now = health?.clinic_now ?? localNow();
  const today = now.slice(0, 10);
  const upcoming = appointments.filter((a) => a.status === "booked" && a.start >= now).length;
  const cancelled = appointments.filter((a) => a.status === "cancelled").length;
  // "Next open day": today if slots remain, otherwise the first day that has any.
  const nextDay = doctors.flatMap((d) => d.slots.map((s) => dayKey(s.start))).sort()[0] ?? today;
  const onDuty = doctors.filter((d) => d.slots.some((s) => dayKey(s.start) === nextDay)).length;
  const nextDayLabel = nextDay === today ? "today" : `${dayDate(nextDay).toLocaleDateString("en-US", { weekday: "short" })} ${dayDate(nextDay).getDate()}`;
  const dateLabel = dayDate(today).toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" });

  // On phones and tablets the call screen covers the page: freeze the page behind it.
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 1099px)").matches;
    document.body.style.overflow = inCall && narrow ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [inCall]);

  const go = (id: string) => {
    setNav(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const status = ready ? { cls: "up", text: "Online" } : online ? { cls: "warn", text: "Not configured" } : { cls: "down", text: "Offline" };

  return (
    <div className={`shell ${inCall ? "in-call" : ""}`}>
      <aside className="side">
        <div className="brand">
          <span className="mark"><svg viewBox="0 0 32 32"><path d="M16 8v16M8 16h16" /></svg></span>
          <div><b>Nexov Health</b><small>Front desk</small></div>
        </div>
        <nav className="nav" aria-label="Sections">
          {NAV.map((n) => (
            <button key={n.id} className={nav === n.id ? "on" : ""} onClick={() => go(n.id)}>
              <Icon d={n.icon} />{n.label}
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="agent-mini">
            <span className="ava">A<i className={status.cls} /></span>
            <div><b>Aria</b><small>Voice agent · {status.text}</small></div>
          </div>
          <button className="link" onClick={() => resetDemo()}><Icon d={I.reset} />Reset demo data</button>
        </div>
      </aside>

      <main className="main" id="overview">
        <header className="top">
          <div>
            <p className="date">{dateLabel}</p>
            <h1>Front desk</h1>
          </div>
          <button className="btn primary" onClick={call.start} disabled={inCall}>
            <Icon d={I.phone} />Call Aria
          </button>
        </header>

        <section className="kpis" aria-label="Summary">
          <div className="kpi"><span className="kpi-ic green"><Icon d={I.cal} /></span><div><small>Upcoming appointments</small><b>{upcoming}</b></div></div>
          <div className="kpi"><span className="kpi-ic blue"><Icon d={I.users} /></span><div><small>Doctors available {nextDayLabel}</small><b>{onDuty}<em>/{doctors.length}</em></b></div></div>
          <div className="kpi"><span className="kpi-ic rose"><Icon d={I.x} /></span><div><small>Cancellations</small><b>{cancelled}</b></div></div>
        </section>

        <Availability doctors={doctors} today={today} />
        <Appointments items={appointments} flash={flash} now={now} />
      </main>

      <aside className="rail" id="agent">
        <section className="card agent">
          <div className="agent-top">
            <span className="ava lg">A<i className={status.cls} /></span>
            <div>
              <h2>Aria</h2>
              <p className="sub">AI receptionist · English</p>
            </div>
            <span className={`pill ${status.cls}`}>{status.text}</span>
          </div>
          <ul className="caps">
            <li><Icon d={I.check} />Checks doctor availability</li>
            <li><Icon d={I.check} />Books, looks up and cancels</li>
            <li><Icon d={I.check} />Confirms the caller's phone number</li>
          </ul>
          <button className="btn primary block" onClick={call.start} disabled={inCall || !ready}>
            <Icon d={I.phone} />{ready ? "Start a test call" : "Agent unavailable"}
          </button>
        </section>

        <section className="card tr-card">
          <header className="card-head tight">
            <h2>{live || call.messages.length === 0 ? "Live transcript" : "Last call"}</h2>
            {live
              ? <span className="pill live"><i />Live</span>
              : call.messages.length > 0 && <span className="pill">{fmtClock(call.duration)}</span>}
          </header>
          {call.messages.length === 0
            ? <div className="empty-tr"><Icon d={I.wave} /><p>{live ? "Say hello to Aria…" : "The conversation appears here during a call and stays after it ends."}</p></div>
            : <Transcript messages={call.messages} />}
        </section>
      </aside>

      <Phone call={call} lastEvent={lastEvent} />
    </div>
  );
}
