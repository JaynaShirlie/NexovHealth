"""FastAPI app: WebRTC signalling for the voice bot, plus REST and Server-Sent Events for the dashboard."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import config

config.setup_logging()

import db  # noqa: E402
import events  # noqa: E402
from bot import active_calls, run_bot  # noqa: E402
from fastapi import BackgroundTasks, FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from loguru import logger  # noqa: E402
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection  # noqa: E402
from pipecat.transports.smallwebrtc.request_handler import (  # noqa: E402
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    if config.missing_keys():
        logger.warning(f"Missing {', '.join(config.missing_keys())}: calls are disabled until they are set in backend/.env")
    logger.info(f"Ready on http://localhost:{config.PORT}  (LLM chain {config.llm_chain()}, max {config.MAX_CONCURRENT_CALLS} calls)")
    yield
    for task in list(active_calls.values()):
        await task.cancel()


app = FastAPI(title="Nexov Health Voice Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])
webrtc_handler = SmallWebRTCRequestHandler()


# ---------- health ----------
@app.get("/api/health")
async def health():
    missing = config.missing_keys()
    return {
        "ok": True,
        "configured": not missing,
        "missing": missing,
        "llm": config.llm_chain()[0].split(":", 1)[1] if config.llm_chain() else None,
        "active_calls": len(active_calls),
        "max_calls": config.MAX_CONCURRENT_CALLS,
        "clinic_now": config.now().isoformat(timespec="minutes"),
        "timezone": config.CLINIC_TIMEZONE,
    }


# ---------- voice (WebRTC signalling) ----------
@app.post("/api/offer")
async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
    if config.missing_keys():
        raise HTTPException(503, f"Missing {', '.join(config.missing_keys())} in backend/.env")
    is_renegotiation = request.pc_id is not None and request.pc_id in active_calls
    if not is_renegotiation and len(active_calls) >= config.MAX_CONCURRENT_CALLS:
        raise HTTPException(429, "All lines are busy. Try again in a moment.")

    async def on_connection(connection: SmallWebRTCConnection):
        background_tasks.add_task(run_bot, connection)

    return await webrtc_handler.handle_web_request(request=request, webrtc_connection_callback=on_connection)


@app.patch("/api/offer")
async def ice_candidate(request: SmallWebRTCPatchRequest):
    await webrtc_handler.handle_patch_request(request)
    return {"status": "success"}


# ---------- dashboard data ----------
@app.get("/api/doctors")
async def doctors():
    return db.list_doctors_with_slots()


@app.get("/api/appointments")
async def appointments():
    return db.list_appointments()


@app.post("/api/reset")
async def reset():
    """Demo helper: restore the sample data."""
    db.init(reset=True)
    events.publish({"type": "reset"})
    return {"status": "ok"}


@app.get("/api/events")
async def stream_events():
    """Server-Sent Events: the voice tools publish 'booked' / 'cancelled' here."""
    q = events.subscribe()

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            events.unsubscribe(q)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# Serve the built dashboard (npm run build in /frontend) from the same origin.
dist = Path(__file__).parent.parent / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
