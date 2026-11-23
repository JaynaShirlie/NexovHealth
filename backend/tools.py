"""LLM tools (function calling). Registered on the LLM service inside the Pipecat pipeline."""

import functools

from loguru import logger

import db
import events
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

check_availability_schema = FunctionSchema(
    name="check_doctor_availability",
    description=(
        "Look up open appointment slots for a speciality or a named doctor, optionally on a date. "
        "You must know which type of doctor or specialist the caller wants (or a doctor's name) before calling."
    ),
    properties={
        "doctor_name": {"type": "string", "description": "Doctor's name, e.g. 'Sharma'. Optional."},
        "speciality": {"type": "string", "description": "Speciality or symptom area, e.g. 'cardiology', 'skin'. Optional."},
        "date": {"type": "string", "description": "YYYY-MM-DD taken from the calendar in your instructions. Optional."},
    },
    required=[],
)

book_schema = FunctionSchema(
    name="book_appointment",
    description=(
        "Book a slot for the caller. Only call after the caller picked a slot, gave their name, "
        "and CONFIRMED the phone number after you read it back digit by digit."
    ),
    properties={
        "slot_id": {"type": "integer", "description": "slot_id returned by check_doctor_availability."},
        "phone_number": {"type": "string", "description": "The 10 digit phone number the caller said."},
        "patient_name": {"type": "string", "description": "The caller's name."},
        "phone_confirmed": {"type": "boolean", "description": "True only if the caller said yes to your read-back of the number."},
    },
    required=["slot_id", "phone_number", "patient_name", "phone_confirmed"],
)

lookup_schema = FunctionSchema(
    name="get_my_appointments",
    description=(
        "List the caller's upcoming booked appointments, found by phone number. Only call after the caller "
        "CONFIRMED the number you read back."
    ),
    properties={
        "phone_number": {"type": "string", "description": "The 10 digit phone number the caller said."},
        "phone_confirmed": {"type": "boolean", "description": "True only if the caller said yes to your read-back of the number."},
    },
    required=["phone_number", "phone_confirmed"],
)

cancel_schema = FunctionSchema(
    name="cancel_appointment",
    description=(
        "Cancel the caller's existing appointment, found by phone number. Only call after the caller "
        "CONFIRMED the number you read back. If they have several, ask which one and pass appointment_id."
    ),
    properties={
        "phone_number": {"type": "string", "description": "The 10 digit phone number the caller said."},
        "phone_confirmed": {"type": "boolean", "description": "True only if the caller said yes to your read-back of the number."},
        "appointment_id": {"type": "integer", "description": "Only needed when the caller has several appointments."},
    },
    required=["phone_number", "phone_confirmed"],
)

tools = ToolsSchema(standard_tools=[check_availability_schema, book_schema, lookup_schema, cancel_schema])


async def check_doctor_availability(params: FunctionCallParams):
    args = params.arguments
    if not (args.get("speciality") or args.get("doctor_name")):
        await params.result_callback({"found": False, "message": "Ask the caller which type of doctor or specialist they are looking for."})
        return
    day = db.parse_date(args.get("date"))
    if args.get("date") and not day:
        await params.result_callback({"found": False, "message": "Could not understand the date. Ask the caller again."})
        return
    await params.result_callback(db.availability(args.get("doctor_name"), args.get("speciality"), day))


async def book_appointment(params: FunctionCallParams):
    args = params.arguments
    if not args.get("phone_confirmed"):
        await params.result_callback({"success": False, "error": "Read the number back and get a yes first."})
        return
    phone = db.normalize_phone(args.get("phone_number", ""))
    if not phone:
        await params.result_callback({"success": False, "error": "Phone number must be 10 digits. Ask the caller to repeat it."})
        return
    name = " ".join((args.get("patient_name") or "").split())[:60]
    if not name:
        await params.result_callback({"success": False, "error": "Ask for the caller's name first."})
        return
    result = db.book(int(args["slot_id"]), phone, name)
    if result["success"]:
        appt = db.get_appointment(result["appointment_id"])
        events.publish({"type": "booked", "appointment": appt})
        result["summary"] = f"{appt['doctor_name']} ({appt['speciality']}), {db.spoken_when(appt['start'])}"
    await params.result_callback(result)


async def _confirmed_phone(params: FunctionCallParams) -> str | None:
    """Shared identity check: the number must be read back, confirmed, and 10 digits long."""
    args = params.arguments
    if not args.get("phone_confirmed"):
        await params.result_callback({"success": False, "error": "Read the number back and get a yes first."})
        return None
    phone = db.normalize_phone(args.get("phone_number", ""))
    if not phone:
        await params.result_callback({"success": False, "error": "Phone number must be 10 digits. Ask the caller to repeat it."})
    return phone


async def get_my_appointments(params: FunctionCallParams):
    phone = await _confirmed_phone(params)
    if not phone:
        return
    active = db.active_for_phone(phone)
    await params.result_callback({
        "success": True,
        "count": len(active),
        "appointments": [{"appointment_id": a["id"], "doctor": a["doctor_name"], "speciality": a["speciality"],
                          "when": db.spoken_when(a["start"])} for a in sorted(active, key=lambda a: a["start"])],
    })


async def cancel_appointment(params: FunctionCallParams):
    args = params.arguments
    if not args.get("phone_confirmed"):
        await params.result_callback({"success": False, "error": "Read the number back and get a yes first."})
        return
    phone = db.normalize_phone(args.get("phone_number", ""))
    if not phone:
        await params.result_callback({"success": False, "error": "Phone number must be 10 digits. Ask the caller to repeat it."})
        return
    active = db.active_for_phone(phone)
    if not active:
        await params.result_callback({"success": False, "error": "No active appointment found for that number."})
        return
    wanted = args.get("appointment_id")
    if wanted:
        active = [a for a in active if a["id"] == int(wanted)]
    if len(active) > 1:
        await params.result_callback({
            "success": False,
            "error": "Several appointments found. Ask which one.",
            "appointments": [{"appointment_id": a["id"], "doctor": a["doctor_name"], "when": db.spoken_when(a["start"])} for a in active],
        })
        return
    if not active:
        await params.result_callback({"success": False, "error": "That appointment id does not belong to this number."})
        return
    appt = active[0]
    db.cancel(appt["id"])
    events.publish({"type": "cancelled", "appointment": db.get_appointment(appt["id"])})
    await params.result_callback({"success": True, "cancelled": f"{appt['doctor_name']}, {db.spoken_when(appt['start'])}"})


def safe(handler):
    """A tool must always answer the LLM; an unhandled exception would leave the caller in silence."""

    @functools.wraps(handler)
    async def wrapper(params: FunctionCallParams):
        logger.info(f"Tool {params.function_name}({params.arguments})")
        try:
            await handler(params)
        except Exception:
            logger.exception(f"Tool {params.function_name} failed")
            await params.result_callback(
                {"success": False, "error": "A system error occurred. Apologise and offer to try again."}
            )

    return wrapper


HANDLERS = {
    "check_doctor_availability": safe(check_doctor_availability),
    "book_appointment": safe(book_appointment),
    "get_my_appointments": safe(get_my_appointments),
    "cancel_appointment": safe(cancel_appointment),
}
