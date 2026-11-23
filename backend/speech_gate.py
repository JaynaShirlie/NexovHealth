"""Drops speech-to-text output that wasn't preceded by real speech.

Speech recognisers sometimes "hear" whole sentences in near-silence or steady noise
("I got an A in that class"). Silero VAD is a separate, stricter judge of whether a person
is actually talking, so a transcript is only let through if VAD heard speech in that window.
"""

import time

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# A final transcript can arrive shortly after VAD says speech ended (STT latency).
GRACE_SECS = 2.0


class SpeechGate(FrameProcessor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._speaking = False
        self._last_stop = float("-inf")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # VAD runs in the user aggregator after us; its frames are broadcast, so they reach us going upstream.
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._speaking = True
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._speaking = False
            self._last_stop = time.monotonic()
        elif isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)) and direction == FrameDirection.DOWNSTREAM:
            if not self._speaking and time.monotonic() - self._last_stop > GRACE_SECS:
                if isinstance(frame, TranscriptionFrame):
                    logger.info(f"Ignored transcript with no detected speech: {frame.text!r}")
                return

        await self.push_frame(frame, direction)
