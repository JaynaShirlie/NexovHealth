"""Print the LLM models your keys can call (Groq and/or Gemini).
Run from backend/:  python scripts/list_models.py   (reads keys from .env; nothing is printed but model names)"""
import json
import os
import urllib.request

from dotenv import load_dotenv

load_dotenv()

if os.getenv("GROQ_API_KEY"):
    req = urllib.request.Request("https://api.groq.com/openai/v1/models",
                                 headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
    models = json.loads(urllib.request.urlopen(req, timeout=20).read())["data"]
    print("Groq (set GROQ_MODEL):")
    for m in sorted(models, key=lambda m: m["id"]):
        print("  ", m["id"])

if os.getenv("GOOGLE_API_KEY"):
    from google import genai

    print("Gemini (set GEMINI_MODEL / GEMINI_FALLBACK_MODELS):")
    for m in genai.Client(api_key=os.environ["GOOGLE_API_KEY"]).models.list():
        if "generateContent" in (m.supported_actions or []):
            print("  ", m.name.removeprefix("models/"))
