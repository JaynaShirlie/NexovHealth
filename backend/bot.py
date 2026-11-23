"""Voice pipeline: caller audio -> ElevenLabs STT -> Gemini (tools) -> ElevenLabs TTS -> caller audio."""

import random
import time
from datetime import date, timedelta

from google.genai.types import HttpOptions, HttpRetryOptions
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import ErrorFrame, LLMRunFrame, TTSSpeakFrame
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.service_switcher import ServiceSwitcherStrategyManual
from pipecat.pipeline.task import PipelineParams
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMAssistantAggregatorParams,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.context.llm_context_summarization import LLMAutoContextSummarizationConfig
from pipecat.utils.errors import ErrorCategory
from pipecat.workers.runner import WorkerRunner

import config
import db
import tools
from speech_gate import SpeechGate

SYSTEM_PROMPT = """You are Aria, the phone receptionist for Nexov Health, a multi-speciality clinic.
Today is {today}. The clinic is open Monday to Saturday, 9 AM to 5 PM, with 30 minute appointments, bookable up to a week ahead.
Calendar (use these exact YYYY-MM-DD values for the date argument): {calendar}.
Specialities: Cardiology (heart), Dermatology (skin and hair), Pediatrics (children), Orthopedics (bones and joints), General Medicine (general physician), ENT (ear, nose, throat), Gynecology (women's health), Neurology (brain, nerves, headaches).
You are on a voice call: reply in one or two short, warm, natural sentences. No lists, no markdown, no emojis, no symbols.

You can, in any order and as many times as needed in one call: check a doctor's availability, book an appointment, look up the caller's existing appointments, and cancel an appointment.

Identity rules (strict):
- You know the caller ONLY by the 10 digit phone number they say out loud. There is no login, OTP or caller ID.
- Before every booking, lookup or cancellation, read the number back in words, in two groups, e.g. "nine eight seven six five, four three two one zero. Is that right?"
- Only after a clear yes, call the tool with phone_confirmed=true and the number as digits. If they say no, ask for it again.
- If you heard fewer than 10 digits, ask only for the missing part. Never guess or invent digits.
- If the caller already gave a number earlier in this call, don't ask them to say it again: read that number back and ask "Should I use this number?" A yes counts as confirmation.

Booking:
1. If the caller has not said what kind of doctor they need, ALWAYS ask first: "Which type of doctor or specialist are you looking for?" If they describe a symptom, suggest the matching specialist.
2. Ask which day suits them.
3. Call check_doctor_availability with the speciality (or doctor name) and day, then offer at most three times aloud.
   Always trust the tool over memory: slots change as people book and cancel, so check again whenever the caller asks about another day or doctor. Each result lists days_with_openings; if the chosen day is full, offer one of those days.
4. Once they choose, ask for their name and phone number, confirm the number, call book_appointment, then confirm the doctor, day and time.
Checking existing appointments: ask for the phone number, confirm it, call get_my_appointments, then tell them what is booked.
Cancelling: ask for the phone number, confirm it, call cancel_appointment, then say what was cancelled. If several come back, describe them briefly, ask which one, then call again with appointment_id.
After finishing a task, ask if there is anything else.

Style:
- A short holding line is played automatically while a tool runs, so do not say "let me check" yourself.
- Say dates and times naturally ("Tuesday the 24th at ten thirty in the morning").
- Never say slot ids, appointment ids or other internal numbers.
- If a tool returns an error, explain it simply and offer the next step.
- Only help with appointments. For medical questions, say you can't advise and offer to book a doctor. In an emergency, tell them to call 112.
- When the caller is done, say a short goodbye."""

# Spoken while a tool runs, so the caller never sits in silence during the extra LLM round trip.
HOLDING_LINES = {
    "check_doctor_availability": ["One moment, let me check.", "Sure, checking that now.", "Let me look that up."],
    "get_my_appointments": ["One moment, let me pull that up.", "Sure, checking your bookings."],
    "book_appointment": ["Great, booking that now.", "Perfect, one moment while I book that."],
    "cancel_appointment": ["Okay, cancelling that now.", "One moment while I cancel that."],
}

# Errors worth moving to the next model for. Free tiers count requests per model (and per provider),
# so a 429 on one usually leaves the next one available.
FAILOVER_ON = {ErrorCategory.RATE_LIMIT, ErrorCategory.QUOTA, ErrorCategory.SERVER, ErrorCategory.CONNECTIVITY}

# pc_id -> running pipeline, so the server can cap concurrent calls.
active_calls: dict[str, PipelineWorker] = {}


class LLMFailover(ServiceSwitcherStrategyManual):
    """Switch to the next model in the chain on rate limits, outages and stalls (round robin)."""

    async def handle_error(self, error: ErrorFrame):
        failed = error.processor or self._active_service
        if failed.is_usable and error.category not in FAILOVER_ON:
            return None
        i = self._services.index(self._active_service)
        for step in range(1, len(self._services)):
            candidate = self._services[(i + step) % len(self._services)]
            if candidate.is_usable:
                logger.warning(f"LLM {failed.name} failed ({error.category}); switching to {candidate.name}")
                return await self._set_active_if_available(candidate)
        return None


def system_instruction() -> str:
    today = config.today()
    days = [today + timedelta(days=i) for i in range(db.DAYS_AHEAD + 1)]
    calendar = "; ".join(f"{d.strftime('%A %d %B')} = {d.isoformat()}" + (" (closed)" if d.weekday() == 6 else "") for d in days)
    return SYSTEM_PROMPT.format(today=today.strftime("%A, %d %B %Y"), calendar=calendar)


def make_groq(model: str) -> GroqLLMService:
    return GroqLLMService(
        api_key=config.GROQ_API_KEY,
        settings=GroqLLMService.Settings(model=model, system_instruction=system_instruction(), temperature=0.3),
    )


def make_gemini(model: str) -> GoogleLLMService:
    return GoogleLLMService(
        api_key=config.GOOGLE_API_KEY,
        settings=GoogleLLMService.Settings(
            model=model,
            system_instruction=system_instruction(),
            temperature=0.3,  # receptionist, not a poet: keeps tool use predictable
        ),
        # Re-issue a request with no first chunk after 4s; abandon a stalled stream after 10s.
        retry_timeout_secs=4.0,
        retry_on_timeout=True,
        stream_idle_timeout_secs=10.0,
        # Quick in-place retries for transient 500/503. 429 is handled by switching model instead.
        http_options=HttpOptions(
            retry_options=HttpRetryOptions(attempts=3, initial_delay=0.4, max_delay=2.0, http_status_codes=[500, 503])
        ),
    )


def build_services():
    stt = ElevenLabsRealtimeSTTService(
        api_key=config.ELEVENLABS_API_KEY,
        settings=ElevenLabsRealtimeSTTService.Settings(
            language=Language.EN,           # fixed language: no Thai/Russian guesses
            filter_background_audio=True,   # strip room noise before transcribing (fewer phantom sentences)
        ),
    )
    tts = ElevenLabsTTSService(
        api_key=config.ELEVENLABS_API_KEY,
        settings=ElevenLabsTTSService.Settings(voice=config.ELEVENLABS_VOICE_ID, model=config.ELEVENLABS_TTS_MODEL),
    )
    # Primary LLM first, the rest are automatic fallbacks (see LLMFailover).
    llms = [make_groq(m) if provider == "groq" else make_gemini(m)
            for provider, m in (entry.split(":", 1) for entry in config.llm_chain())]
    llm = LLMSwitcher(llms=llms, strategy_type=LLMFailover)
    for name, handler in tools.HANDLERS.items():
        llm.register_function(name, handler)

    for service in llms:
        @service.event_handler("on_function_calls_started")
        async def on_tool_start(service, function_calls):
            lines = HOLDING_LINES.get(function_calls[0].function_name)
            if lines:
                await service.push_frame(TTSSpeakFrame(random.choice(lines)))

    return stt, tts, llm


async def run_bot(connection: SmallWebRTCConnection) -> None:
    call_id = connection.pc_id
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    stt, tts, llm = build_services()

    context = LLMContext(tools=tools.tools)
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        # Turn-taking: Silero VAD detects speech and the turn ends after a 0.5s pause.
        # (The default smart-turn model held replies back up to 3s after short phrases.)
        user_params=LLMUserAggregatorParams(
            # Strict enough that breathing, fans or keyboard noise don't count as speech.
            vad_analyzer=SileroVADAnalyzer(params=VADParams(confidence=0.75, start_secs=0.25, stop_secs=0.2, min_volume=0.6)),
            user_turn_strategies=UserTurnStrategies(stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.5)]),
        ),
        # Long calls: once the history passes ~4k tokens, older turns are compressed into a summary,
        # so every request stays small and fast however long the caller talks.
        assistant_params=LLMAssistantAggregatorParams(
            enable_auto_context_summarization=True,
            auto_context_summarization_config=LLMAutoContextSummarizationConfig(
                max_context_tokens=4000, max_unsummarized_messages=None
            ),
        ),
    )

    pipeline = Pipeline([
        transport.input(),   # caller audio (WebRTC)
        stt,                 # ElevenLabs Scribe realtime
        SpeechGate(),        # drop transcripts VAD didn't hear as speech (STT hallucinations)
        user_agg,            # VAD + turn detection -> user message in context
        llm,                 # Gemini (with failover), may call tools
        tts,                 # ElevenLabs TTS
        transport.output(),  # audio back to the caller
        assistant_agg,       # what was actually spoken -> context (+ summarization)
    ])
    task = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        idle_timeout_secs=config.CALL_IDLE_TIMEOUT_SECS,
    )
    active_calls[call_id] = task

    # After a model switch, re-run the turn that failed so the caller still gets an answer.
    # If every model keeps failing, apologise instead of looping.
    switches: list[float] = []

    @llm.strategy.event_handler("on_service_switched")
    async def on_switched(_strategy, service):
        now = time.monotonic()
        switches[:] = [t for t in switches if now - t < 30] + [now]
        if len(switches) <= len(llm.llms):
            logger.info(f"Call {call_id}: retrying the turn on {service.name}")
            await task.queue_frames([LLMRunFrame()])
        else:
            await task.queue_frames([TTSSpeakFrame("Sorry, I'm having a little trouble right now. Could you say that again in a moment?")])

    @transport.event_handler("on_client_connected")
    async def on_connected(_transport, _client):
        logger.info(f"Call {call_id}: connected ({len(active_calls)} active)")
        context.add_message({"role": "user", "content": "(The call has just connected. Greet the caller briefly and ask how you can help.)"})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_transport, _client):
        logger.info(f"Call {call_id}: caller hung up")
        await task.cancel()

    try:
        await WorkerRunner(handle_sigint=False).run(task)
    except Exception:
        logger.exception(f"Call {call_id}: pipeline crashed")
    finally:
        active_calls.pop(call_id, None)
        logger.info(f"Call {call_id}: ended ({len(active_calls)} active)")
