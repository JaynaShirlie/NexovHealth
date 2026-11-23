"""Try stock ElevenLabs voices and report which ones your plan can use via the API.
Run from backend/:  python scripts/check_voices.py   (reads ELEVENLABS_API_KEY from .env; the key is never printed)"""
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()
key = os.environ["ELEVENLABS_API_KEY"]
CANDIDATES = {
    "George": "JBFqnCBsd6RMkjVDRZzb", "Sarah": "EXAVITQu4vr4OOiZY7Mv", "Roger": "CwhRBWXzGAHq8TQ4Fs17",
    "Charlie": "IKne3meq5aSn9XLyUdCD", "Brian": "nPczCjzI2devNBz1zQrb", "Alice": "Xb7hH8MSUJpSbSDYk0k2",
    "Matilda": "XrExE9yKIg1WjnnlVkGX", "Lily": "pFZP5JQG7iQjIQuC4Bku", "Jessica": "cgSgspJ2msm6clMCkdW9",
    "Bill": "pqHfZKP75CvOlQylNhV4", "Laura": "FGY2WhTYpPnrIDTdsKH5", "Eric": "cjVigY5qzO86Huf0OWal",
}
for name, vid in CANDIDATES.items():
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_22050_32",
        data=json.dumps({"text": "Hi.", "model_id": "eleven_flash_v2_5"}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"OK    {name:8} {vid}  ({len(r.read())} bytes)")
    except urllib.error.HTTPError as e:
        print(f"FAIL  {name:8} {vid}  {e.code} {json.loads(e.read()).get('detail', {}).get('code')}")
