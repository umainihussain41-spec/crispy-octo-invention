from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

TECH_SUPPORT_PROMPT = (
    "You are a calm, practical technical support voice agent. "
    "Help users troubleshoot software, devices, accounts, deployments, and developer issues. "
    "Ask one focused question at a time when information is missing. "
    "Prefer short spoken answers, clear steps, and safe checks before risky changes. "
    "If the issue may involve credentials, payments, data loss, security, or production systems, "
    "pause and explain the risk before proceeding."
)

sessions: dict[str, list[dict[str, str]]] = {}


def get_sarvam_client() -> Any:
    api_key = os.getenv("SARVAM_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="SARVAM_API_KEY is not configured.")
    try:
        from sarvamai import SarvamAI
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Sarvam SDK is not installed.") from exc
    return SarvamAI(api_subscription_key=api_key)


def get_session_messages(session_id: str) -> list[dict[str, str]]:
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": TECH_SUPPORT_PROMPT}]
    return sessions[session_id]


def extract_transcript(response: Any) -> str:
    if hasattr(response, "model_dump"):
        return extract_transcript(response.model_dump())

    if isinstance(response, dict):
        for key in ("transcript", "text", "transcription"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    for key in ("transcript", "text", "transcription"):
        value = getattr(response, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_chat_text(response: Any) -> str:
    if hasattr(response, "model_dump"):
        return extract_chat_text(response.model_dump())

    if isinstance(response, dict):
        choices = response.get("choices") or []
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
        return ""

    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content.strip()
    return ""


def transcribe_audio(audio_path: Path) -> str:
    client = get_sarvam_client()
    with audio_path.open("rb") as audio_file:
        response = client.speech_to_text.transcribe(
            file=audio_file,
            model=os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
            mode="transcribe",
        )
    return extract_transcript(response)


def ask_sarvam(messages: list[dict[str, str]]) -> str:
    client = get_sarvam_client()
    response = client.chat.completions(
        model=os.getenv("SARVAM_CHAT_MODEL", "sarvam-30b"),
        messages=messages,
        temperature=float(os.getenv("AI_TEMPERATURE", "0.35")),
        top_p=1,
        reasoning_effort=None,
        max_tokens=int(os.getenv("AI_MAX_TOKENS", "700")),
    )
    answer = extract_chat_text(response)
    if not answer:
        raise HTTPException(status_code=502, detail="Sarvam chat returned an empty response.")
    return answer


def ask_ollama(messages: list[dict[str, str]]) -> str:
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    response = requests.post(
        f"{ollama_url}/api/chat",
        json={
            "model": os.getenv("OLLAMA_MODEL", "llama3:latest"),
            "messages": messages,
            "stream": False,
            "options": {"temperature": float(os.getenv("AI_TEMPERATURE", "0.35"))},
        },
        timeout=180,
    )
    response.raise_for_status()
    answer = response.json().get("message", {}).get("content", "").strip()
    if not answer:
        raise HTTPException(status_code=502, detail="Ollama returned an empty response.")
    return answer


def ask_ai(messages: list[dict[str, str]]) -> str:
    provider = os.getenv("AI_PROVIDER", "sarvam").lower()
    if provider == "ollama":
        return ask_ollama(messages)
    return ask_sarvam(messages)


def text_to_speech(text: str) -> str:
    client = get_sarvam_client()
    response = client.text_to_speech.convert(
        target_language_code=os.getenv("SARVAM_LANGUAGE", "en-IN"),
        text=text[:2400],
        model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        speaker=os.getenv("SARVAM_SPEAKER", "shubh"),
    )
    if hasattr(response, "model_dump"):
        response = response.model_dump()
    audios = response.get("audios", []) if isinstance(response, dict) else getattr(response, "audios", [])
    if not audios:
        raise HTTPException(status_code=502, detail="Sarvam TTS returned no audio.")
    return "".join(audios)


app = FastAPI(title="Sarvam Tech Support Voicebot")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def config() -> dict[str, str]:
    return {
        "provider": os.getenv("AI_PROVIDER", "sarvam"),
        "chat_model": os.getenv("SARVAM_CHAT_MODEL", "sarvam-30b"),
        "stt_model": os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
        "tts_model": os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        "language": os.getenv("SARVAM_LANGUAGE", "en-IN"),
        "speaker": os.getenv("SARVAM_SPEAKER", "shubh"),
    }


@app.post("/api/reset")
async def reset(request: Request) -> dict[str, str]:
    body = await request.json()
    session_id = body.get("session_id") or str(uuid4())
    sessions[session_id] = [{"role": "system", "content": TECH_SUPPORT_PROMPT}]
    return {"session_id": session_id}


@app.post("/api/chat")
async def chat(
    session_id: str = Form(...),
    audio: UploadFile | None = File(default=None),
    text: str = Form(default=""),
) -> dict[str, str]:
    user_text = text.strip()
    tmp_path: Path | None = None

    if audio is not None and audio.filename:
        suffix = Path(audio.filename).suffix or ".webm"
        fd, raw_path = tempfile.mkstemp(prefix="voicebot_upload_", suffix=suffix)
        os.close(fd)
        tmp_path = Path(raw_path)
        tmp_path.write_bytes(await audio.read())
        try:
            user_text = transcribe_audio(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    if not user_text:
        return {
            "session_id": session_id,
            "transcript": "",
            "answer": "I could not hear a clear request. Please try again a little closer to the microphone.",
            "audio_base64": "",
        }

    messages = get_session_messages(session_id)
    messages.append({"role": "user", "content": user_text})
    answer = ask_ai(messages)
    messages.append({"role": "assistant", "content": answer})
    return {
        "session_id": session_id,
        "transcript": user_text,
        "answer": answer,
        "audio_base64": text_to_speech(answer),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "web_app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
