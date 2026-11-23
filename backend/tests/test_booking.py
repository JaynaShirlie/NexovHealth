"""Tests for the data layer and the three voice tools (no network, no API keys needed).

Run from backend/:  python -m pytest -q
"""

import asyncio
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import db  # noqa: E402
import events  # noqa: E402
import tools  # noqa: E402


class FakeParams:
    """Stands in for Pipecat's FunctionCallParams."""

    def __init__(self, name, arguments):
        self.function_name = name
        self.arguments = arguments
        self.result = None

    async def result_callback(self, result, **_):
        self.result = result


def call(name, **arguments):
    p = FakeParams(name, arguments)
    asyncio.run(tools.HANDLERS[name](p))
    return p.result


@pytest.fixture(autouse=True)
def fresh_db():
    db.init(reset=True)


def first_open_slot(speciality="dermatology"):
    res = call("check_doctor_availability", speciality=speciality)
    return next(s for d in res["doctors"] for s in d["slots"])


# ---------- phone numbers ----------

@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "9876543210"),
    ("98765 43210", "9876543210"),
    ("+91 98765-43210", "9876543210"),
    ("09876543210", "9876543210"),
    ("nine eight seven six five four three two one zero", "9876543210"),
    ("nine eight double seven six five four three two one", "9877654321"),
    ("triple nine eight seven six five four three two", "9998765432"),
    ("12345", None),
    ("", None),
])
def test_normalize_phone(raw, expected):
    assert db.normalize_phone(raw) == expected


# ---------- availability ----------

def test_availability_by_speciality_and_symptom():
    assert call("check_doctor_availability", speciality="Cardiology")["doctors"][0]["doctor"] == "Dr. Ananya Sharma"
    assert call("check_doctor_availability", speciality="my skin has a rash")["doctors"][0]["speciality"] == "Dermatology"


def test_availability_by_doctor_name():
    res = call("check_doctor_availability", doctor_name="Dr. Mehta")
    assert [d["doctor"] for d in res["doctors"]] == ["Dr. Rohan Mehta"]
    assert res["doctors"][0]["slots"]


def test_unknown_doctor_lists_specialities():
    res = call("check_doctor_availability", doctor_name="House")
    assert res["found"] is False and "Cardiology" in res["message"]


def test_sunday_falls_back_to_nearest_slots():
    sunday = db.config.today() + timedelta(days=(6 - db.config.today().weekday()) % 7 or 7)
    res = call("check_doctor_availability", speciality="ENT", date=sunday.isoformat())
    assert res["requested_day_full"] is True and "Sundays" in res["message"]
    assert res["doctors"][0]["slots"]


def test_bad_date_is_rejected():
    res = call("check_doctor_availability", speciality="ENT", date="the day after the blue moon")
    assert res["found"] is False and "date" in res["message"]


def test_availability_requires_a_specialist():
    res = call("check_doctor_availability", date="tomorrow")
    assert res["found"] is False and "specialist" in res["message"]


def test_slots_are_compact_and_limited():
    res = call("check_doctor_availability", speciality="Cardiology")
    slots = res["doctors"][0]["slots"]
    assert 0 < len(slots) <= 4 and set(slots[0]) == {"slot_id", "when"}


# ---------- booking ----------

def test_booking_requires_confirmed_phone():
    slot = first_open_slot()
    res = call("book_appointment", slot_id=slot["slot_id"], phone_number="9876543210", patient_name="Asha", phone_confirmed=False)
    assert res["success"] is False


def test_booking_requires_valid_phone_and_name():
    slot = first_open_slot()
    assert call("book_appointment", slot_id=slot["slot_id"], phone_number="12345", patient_name="Asha", phone_confirmed=True)["success"] is False
    assert call("book_appointment", slot_id=slot["slot_id"], phone_number="9876543210", patient_name="  ", phone_confirmed=True)["success"] is False


def test_book_then_slot_is_gone_and_event_published():
    q = events.subscribe()
    slot = first_open_slot()
    res = call("book_appointment", slot_id=slot["slot_id"], phone_number="98765 43210", patient_name="Asha Verma", phone_confirmed=True)
    assert res["success"] is True and "Dermatology" in res["summary"]
    appt = db.get_appointment(res["appointment_id"])
    assert appt["phone"] == "9876543210" and appt["status"] == "booked"
    assert '"booked"' in q.get_nowait()
    # same slot cannot be booked twice
    again = call("book_appointment", slot_id=slot["slot_id"], phone_number="9123456789", patient_name="Ravi", phone_confirmed=True)
    assert again["success"] is False
    events.unsubscribe(q)


# ---------- looking up existing appointments ----------

def test_lookup_lists_the_callers_upcoming_appointments():
    derm = first_open_slot("Dermatology")
    ent = next(s for s in call("check_doctor_availability", speciality="ENT")["doctors"][0]["slots"] if s["when"] != derm["when"])
    for slot in (derm, ent):  # different times: one caller can't hold two appointments at the same time
        assert call("book_appointment", slot_id=slot["slot_id"], phone_number="9876543210", patient_name="Asha", phone_confirmed=True)["success"]
    res = call("get_my_appointments", phone_number="98765 43210", phone_confirmed=True)
    assert res["success"] is True and res["count"] == 2
    assert {a["speciality"] for a in res["appointments"]} == {"Dermatology", "ENT"}


def test_lookup_requires_confirmation_and_handles_no_bookings():
    assert call("get_my_appointments", phone_number="9876543210", phone_confirmed=False)["success"] is False
    res = call("get_my_appointments", phone_number="9000000000", phone_confirmed=True)
    assert res["success"] is True and res["count"] == 0


# ---------- cancelling ----------

def test_cancel_frees_the_slot():
    slot = first_open_slot()
    call("book_appointment", slot_id=slot["slot_id"], phone_number="9876543210", patient_name="Asha", phone_confirmed=True)
    res = call("cancel_appointment", phone_number="nine eight seven six five four three two one zero", phone_confirmed=True)
    assert res["success"] is True
    assert not db.active_for_phone("9876543210")
    assert first_open_slot()["slot_id"] == slot["slot_id"]  # slot is open again


def test_cancel_requires_confirmation_and_existing_booking():
    assert call("cancel_appointment", phone_number="9876543210", phone_confirmed=False)["success"] is False
    assert call("cancel_appointment", phone_number="9000000000", phone_confirmed=True)["success"] is False


def test_cancel_with_several_appointments_asks_which():
    res = call("check_doctor_availability", speciality="neurology")
    slots = res["doctors"][0]["slots"][:2]
    for s in slots:
        call("book_appointment", slot_id=s["slot_id"], phone_number="9876543210", patient_name="Asha", phone_confirmed=True)
    res = call("cancel_appointment", phone_number="9876543210", phone_confirmed=True)
    assert res["success"] is False and len(res["appointments"]) == 2
    target = res["appointments"][1]["appointment_id"]
    res = call("cancel_appointment", phone_number="9876543210", phone_confirmed=True, appointment_id=target)
    assert res["success"] is True and len(db.active_for_phone("9876543210")) == 1


def test_cannot_cancel_someone_elses_appointment():
    seeded = db.list_appointments()[0]  # belongs to a sample caller
    res = call("cancel_appointment", phone_number="9876543210", phone_confirmed=True, appointment_id=seeded["id"])
    assert res["success"] is False


# ---------- robustness ----------

def test_tool_exception_still_answers_llm():
    res = call("book_appointment", slot_id="not-a-number", phone_number="9876543210", patient_name="A", phone_confirmed=True)
    assert res == {"success": False, "error": "A system error occurred. Apologise and offer to try again."}


# ---------- dates: the agent must search the day the caller meant ----------

def _target():
    """A bookable day two to three days ahead (skips Sunday)."""
    d = db.config.today() + timedelta(days=2)
    return d + timedelta(days=1) if d.weekday() == 6 else d


@pytest.mark.parametrize("fmt", [
    lambda d: d.isoformat(),
    lambda d: d.replace(year=d.year - 1).isoformat(),          # LLM guessed last year
    lambda d: f"{d.day}th",
    lambda d: f"the {d.day}th",
    lambda d: d.strftime("%b ") + str(d.day),                  # "Nov 25"
    lambda d: f"{d.day} " + d.strftime("%B"),                  # "25 November"
    lambda d: f"{d.strftime('%A')} the {d.day}th",             # "Wednesday the 25th"
    lambda d: f"{d.day}/{d.month}",
    lambda d: d.strftime("%A"),
])
def test_parse_date_formats(fmt):
    d = _target()
    assert db.parse_date(fmt(d)) == d


def test_relative_dates():
    assert db.parse_date("today") == db.config.today()
    assert db.parse_date("tomorrow") == db.config.today() + timedelta(days=1)
    assert db.parse_date("day after tomorrow") == db.config.today() + timedelta(days=2)


def test_availability_on_a_named_day_returns_that_days_slots():
    d = _target()
    res = call("check_doctor_availability", doctor_name="Rohan Mehta", date=f"{d.strftime('%A')} the {d.day}th")
    doc = res["doctors"][0]
    assert "requested_day_full" not in res and doc["slots"]
    assert all(s["when"].startswith(d.strftime("%a %d %b")) for s in doc["slots"])
    assert d.strftime("%a %d %b") in doc["days_with_openings"]


def test_booked_slot_disappears_from_availability_and_returns_after_cancel():
    d = _target()
    slots = call("check_doctor_availability", speciality="Dermatology", date=d.isoformat())["doctors"][0]["slots"]
    taken = slots[0]
    call("book_appointment", slot_id=taken["slot_id"], phone_number="9876543210", patient_name="Asha", phone_confirmed=True)
    after = call("check_doctor_availability", speciality="Dermatology", date=d.isoformat())["doctors"][0]["slots"]
    assert taken["slot_id"] not in [s["slot_id"] for s in after]
    call("cancel_appointment", phone_number="9876543210", phone_confirmed=True)
    again = call("check_doctor_availability", speciality="Dermatology", date=d.isoformat())["doctors"][0]["slots"]
    assert taken["slot_id"] in [s["slot_id"] for s in again]


def test_date_outside_booking_window_offers_nearest():
    res = call("check_doctor_availability", speciality="ENT", date=(db.config.today() + timedelta(days=30)).isoformat())
    assert res["requested_day_full"] is True and "only take bookings" in res["message"]
