"""SQLite data layer: doctors, slots and appointments (all mock data)."""

import random
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta

import config

DAYS_AHEAD = 7
DAY_START, DAY_END = 9, 17  # 09:00 - 17:00, 30 minute slots

DOCTORS = [
    (1, "Dr. Ananya Sharma", "Cardiology", "Interventional cardiologist, 14 yrs", "AS"),
    (2, "Dr. Rohan Mehta", "Dermatology", "Skin, hair and allergy care, 9 yrs", "RM"),
    (3, "Dr. Priya Nair", "Pediatrics", "Child health and vaccination, 11 yrs", "PN"),
    (4, "Dr. Arjun Rao", "Orthopedics", "Joint and sports injury, 16 yrs", "AR"),
    (5, "Dr. Kavita Iyer", "General Medicine", "Family physician, 12 yrs", "KI"),
    (6, "Dr. Sameer Khan", "ENT", "Ear, nose and throat, 10 yrs", "SK"),
    (7, "Dr. Neha Kapoor", "Gynecology", "Women's health, 13 yrs", "NK"),
    (8, "Dr. Vikram Singh", "Neurology", "Headache and nerve disorders, 15 yrs", "VS"),
]

# Spoken words callers use -> speciality
SPECIALITY_HINTS = {
    "heart": "Cardiology", "cardio": "Cardiology", "chest": "Cardiology",
    "skin": "Dermatology", "derma": "Dermatology", "rash": "Dermatology", "hair": "Dermatology",
    "child": "Pediatrics", "kid": "Pediatrics", "baby": "Pediatrics", "paediatric": "Pediatrics",
    "pediatric": "Pediatrics",
    "bone": "Orthopedics", "joint": "Orthopedics", "ortho": "Orthopedics", "knee": "Orthopedics",
    "back pain": "Orthopedics", "fracture": "Orthopedics",
    "general": "General Medicine", "fever": "General Medicine", "physician": "General Medicine",
    "cold": "General Medicine", "checkup": "General Medicine",
    "ent": "ENT", "ear": "ENT", "nose": "ENT", "throat": "ENT",
    "women": "Gynecology", "gyn": "Gynecology", "pregnan": "Gynecology",
    "brain": "Neurology", "neuro": "Neurology", "headache": "Neurology", "migraine": "Neurology",
}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def init(reset: bool = False) -> None:
    with _lock:
        c = conn()
        if reset:
            c.executescript("DROP TABLE IF EXISTS appointments; DROP TABLE IF EXISTS slots; DROP TABLE IF EXISTS doctors;")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY, name TEXT, speciality TEXT, bio TEXT, initials TEXT);
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, doctor_id INTEGER, start TEXT,
                is_booked INTEGER DEFAULT 0, UNIQUE(doctor_id, start));
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, slot_id INTEGER, doctor_id INTEGER,
                phone TEXT, patient_name TEXT, status TEXT DEFAULT 'booked',
                created_at TEXT, cancelled_at TEXT);
            """
        )
        first_run = c.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0
        if first_run:
            c.executemany("INSERT INTO doctors VALUES (?,?,?,?,?)", DOCTORS)
        ensure_slots(first_run)
        c.commit()


def ensure_slots(first_run: bool = False) -> None:
    """Idempotently make sure the next DAYS_AHEAD days have slots."""
    c = conn()
    today = config.today()
    now = config.now()
    for offset in range(0, DAYS_AHEAD + 1):
        day = today + timedelta(days=offset)
        if day.weekday() == 6:  # Sunday closed
            continue
        for doc_id, *_ in DOCTORS:
            rng = random.Random(doc_id * 10_000 + day.toordinal())
            minutes = range(DAY_START * 60, DAY_END * 60, 30)
            for m in minutes:
                start = datetime(day.year, day.month, day.day, m // 60, m % 60)
                if start <= now + timedelta(hours=1):
                    continue
                busy = 1 if rng.random() < 0.3 else 0
                c.execute(
                    "INSERT OR IGNORE INTO slots (doctor_id, start, is_booked) VALUES (?,?,?)",
                    (doc_id, start.isoformat(timespec="minutes"), busy),
                )
    if first_run:
        _seed_appointments()


def _seed_appointments() -> None:
    c = conn()
    samples = [("9876500011", "Aarav Gupta", 5), ("9876500022", "Meera Joshi", 2), ("9876500033", "Kabir Das", 4)]
    for phone, name, doc in samples:
        row = c.execute(
            "SELECT id FROM slots WHERE doctor_id=? AND is_booked=0 ORDER BY start LIMIT 1 OFFSET 3", (doc,)
        ).fetchone()
        if row:
            c.execute("UPDATE slots SET is_booked=1 WHERE id=?", (row["id"],))
            c.execute(
                "INSERT INTO appointments (slot_id, doctor_id, phone, patient_name, created_at) VALUES (?,?,?,?,?)",
                (row["id"], doc, phone, name, config.now().isoformat(timespec="seconds")),
            )


# ---------- helpers ----------

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_REPEAT = {"double": 2, "triple": 3}


def spoken_to_digits(raw: str) -> str:
    """'nine eight double seven 6 5' -> '987765'. Digits pass through; other words are ignored."""
    out: list[str] = []
    repeat = 1
    for tok in re.findall(r"[a-z]+|\d", (raw or "").lower()):
        if tok in _REPEAT:
            repeat = _REPEAT[tok]
            continue
        d = tok if tok.isdigit() else _DIGIT_WORDS.get(tok)
        if d is not None:
            out.append(d * repeat)
        repeat = 1
    return "".join(out)


def normalize_phone(raw: str) -> str | None:
    """Return a clean 10 digit Indian mobile/landline number, or None when it is not valid."""
    digits = spoken_to_digits(raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _upcoming(d: date) -> date:
    """Callers mean the next occurrence: a date in the past (e.g. a wrong year from the LLM) rolls forward."""
    today = config.today()
    if d >= today:
        return d
    for year in (today.year, today.year + 1):
        try:
            candidate = d.replace(year=year)
        except ValueError:  # 29 Feb
            continue
        if candidate >= today:
            return candidate
    return d


def _day_of_month(day: int, month: int | None = None) -> date | None:
    today = config.today()
    month = month or today.month
    for year, mon in ((today.year, month), (today.year + (month // 12), month % 12 + 1)):
        try:
            d = date(year, mon, day)
        except ValueError:
            continue
        if d >= today or month != today.month:
            return _upcoming(d)
    return None


def parse_date(text: str | None) -> date | None:
    """Understands '2026-11-25', '25th', 'the 25th', 'Nov 25', '25 November', '25/11',
    'today', 'tomorrow', 'day after tomorrow' and weekday names."""
    if not text or not text.strip():
        return None
    t = text.strip().lower()
    today = config.today()
    if "day after tomorrow" in t:
        return today + timedelta(days=2)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if "today" in t:
        return today
    if m := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):
        try:
            return _upcoming(date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            return None
    if m := re.search(r"\b(\d{1,2})[/.](\d{1,2})\b", t):  # day/month, Indian order
        return _day_of_month(int(m[1]), int(m[2])) if 1 <= int(m[2]) <= 12 else None
    if m := re.search(r"\b([a-z]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", t):
        if m[1][:3] in _MONTHS:
            return _day_of_month(int(m[2]), _MONTHS[m[1][:3]])
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,})", t):
        if m[2][:3] in _MONTHS:
            return _day_of_month(int(m[1]), _MONTHS[m[2][:3]])
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", t):
        return _day_of_month(int(m[1]))
    for i, name in enumerate(_WEEKDAYS):
        if name in t or (len(t) >= 3 and t[:3] == name[:3]):
            delta = (i - today.weekday()) % 7
            return today + timedelta(days=delta or 7) if "next" in t and delta == 0 else today + timedelta(days=delta)
    return None


def booking_window() -> tuple[date, date]:
    today = config.today()
    return today, today + timedelta(days=DAYS_AHEAD)


def _doctor_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "speciality": r["speciality"], "bio": r["bio"], "initials": r["initials"]}


def find_doctors(doctor_name: str | None = None, speciality: str | None = None) -> list[dict]:
    rows = [dict(r) for r in conn().execute("SELECT * FROM doctors")]
    if doctor_name:
        q = re.sub(r"^dr\.?\s*", "", doctor_name.strip().lower())
        rows = [r for r in rows if q and (q in r["name"].lower())]
    if speciality:
        s = speciality.strip().lower()
        target = next((v for k, v in SPECIALITY_HINTS.items() if k in s), None)
        rows = [r for r in rows if s in r["speciality"].lower() or (target and r["speciality"] == target)]
    return rows


# ---------- queries used by REST API ----------

def list_doctors_with_slots() -> list[dict]:
    with _lock:
        c = conn()
        ensure_slots()
        c.commit()
        now = config.now().isoformat(timespec="minutes")
        out = []
        for d in c.execute("SELECT * FROM doctors ORDER BY id"):
            slots = [
                {"id": s["id"], "start": s["start"]}
                for s in c.execute(
                    "SELECT id, start FROM slots WHERE doctor_id=? AND is_booked=0 AND start>? ORDER BY start",
                    (d["id"], now),
                )
            ]
            out.append({**_doctor_dict(d), "slots": slots})
        return out


def list_appointments() -> list[dict]:
    with _lock:
        rows = conn().execute(
            """SELECT a.id, a.phone, a.patient_name, a.status, a.created_at, a.cancelled_at,
                      d.name AS doctor_name, d.speciality, d.initials, s.start
               FROM appointments a JOIN doctors d ON d.id=a.doctor_id JOIN slots s ON s.id=a.slot_id
               ORDER BY a.id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_appointment(appt_id: int) -> dict | None:
    for a in list_appointments():
        if a["id"] == appt_id:
            return a
    return None


# ---------- operations used by the voice tools ----------

def availability(doctor_name: str | None, speciality: str | None, day: date | None, limit_per_doctor: int = 4) -> dict:
    with _lock:
        c = conn()
        ensure_slots()
        c.commit()
        docs = find_doctors(doctor_name, speciality)
        if not docs:
            return {"found": False, "message": "No matching doctor. Available specialities: "
                    + ", ".join(sorted({d[2] for d in DOCTORS}))}
        def query(on_day: date | None) -> list[dict]:
            now = config.now().isoformat(timespec="minutes")
            results = []
            for d in docs:
                sql = "SELECT id, start FROM slots WHERE doctor_id=? AND is_booked=0 AND start>?"
                args: list = [d["id"], now]
                if on_day:
                    sql += " AND start LIKE ?"
                    args.append(on_day.isoformat() + "%")
                sql += " ORDER BY start LIMIT ?"
                args.append(limit_per_doctor)
                slots = []
                for s in c.execute(sql, args):
                    dt = datetime.fromisoformat(s["start"])
                    # Compact on purpose: every byte here is re-sent to the LLM on each later turn.
                    slots.append({"slot_id": s["id"], "when": f"{dt.strftime('%a %d %b')} {_fmt_time(dt)}"})
                open_days = [datetime.fromisoformat(r["day"]).strftime("%a %d %b") for r in c.execute(
                    "SELECT DISTINCT substr(start, 1, 10) AS day FROM slots WHERE doctor_id=? AND is_booked=0 AND start>? ORDER BY day",
                    (d["id"], now))]
                results.append({"doctor": d["name"], "speciality": d["speciality"], "slots": slots, "days_with_openings": open_days})
            return results

        first, last = booking_window()
        if day and not (first <= day <= last):
            return {"found": True, "requested_day_full": True,
                    "message": f"We only take bookings from {first.strftime('%a %d %b')} to {last.strftime('%a %d %b')}. These are the nearest options.",
                    "doctors": query(None)}
        results = query(day)
        if day and not any(r["slots"] for r in results):
            reason = "The clinic is closed on Sundays." if day.weekday() == 6 else f"No free slots on {day.strftime('%A %d %B')}."
            return {"found": True, "requested_day_full": True, "message": reason + " These are the nearest options.",
                    "doctors": query(None)}
        return {"found": True, "doctors": results}


def book(slot_id: int, phone: str, patient_name: str) -> dict:
    with _lock:
        c = conn()
        slot = c.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()
        if not slot:
            return {"success": False, "error": "That slot does not exist."}
        if slot["start"] <= config.now().isoformat(timespec="minutes"):
            return {"success": False, "error": "That time has already passed. Offer another slot."}
        dup = c.execute(
            "SELECT 1 FROM appointments a JOIN slots s ON s.id=a.slot_id "
            "WHERE a.phone=? AND a.status='booked' AND s.start=?", (phone, slot["start"])
        ).fetchone()
        if dup:
            return {"success": False, "error": "Caller already has an appointment at that time."}
        # Atomic claim: only succeeds if nobody booked the slot in the meantime.
        if c.execute("UPDATE slots SET is_booked=1 WHERE id=? AND is_booked=0", (slot_id,)).rowcount != 1:
            return {"success": False, "error": "That slot was just taken. Offer another slot."}
        cur = c.execute(
            "INSERT INTO appointments (slot_id, doctor_id, phone, patient_name, created_at) VALUES (?,?,?,?,?)",
            (slot_id, slot["doctor_id"], phone, patient_name, config.now().isoformat(timespec="seconds")),
        )
        c.commit()
        return {"success": True, "appointment_id": cur.lastrowid}


def active_for_phone(phone: str) -> list[dict]:
    """Upcoming booked appointments for a phone number (past ones can't be changed)."""
    now = config.now().isoformat(timespec="minutes")
    return [a for a in list_appointments() if a["phone"] == phone and a["status"] == "booked" and a["start"] > now]


def cancel(appt_id: int) -> None:
    with _lock:
        c = conn()
        row = c.execute("SELECT slot_id FROM appointments WHERE id=?", (appt_id,)).fetchone()
        c.execute("UPDATE appointments SET status='cancelled', cancelled_at=? WHERE id=?",
                  (config.now().isoformat(timespec="seconds"), appt_id))
        if row:
            c.execute("UPDATE slots SET is_booked=0 WHERE id=?", (row["slot_id"],))
        c.commit()


def spoken_when(iso_start: str) -> str:
    dt = datetime.fromisoformat(iso_start)
    return f"{dt.strftime('%A, %d %B')} at {_fmt_time(dt)}"
