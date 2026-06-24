from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

try:
    import winsound
except ImportError:
    winsound = None


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, general-purpose AI voice assistant. "
    "Be conversational, concise, and useful. Ask clarifying questions when needed."
)


@dataclass
class BotConfig:
    ollama_model: str
    ollama_url: str
    sarvam_api_key: str
    sarvam_tts_model: str
    sarvam_stt_model: str
    sarvam_language: str
    sarvam_speaker: str
    record_seconds: int
    sample_rate: int
    speak: bool


class VoiceBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.sarvam = None
        if config.sarvam_api_key:
            try:
                from sarvamai import SarvamAI
            except ImportError as exc:
                raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc
            self.sarvam = SarvamAI(api_subscription_key=config.sarvam_api_key)

        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}
        ]

    def ask_ollama(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        response = requests.post(
            f"{self.config.ollama_url.rstrip('/')}/api/chat",
            json={
                "model": self.config.ollama_model,
                "messages": self.messages,
                "stream": False,
                "options": {"temperature": 0.7},
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        answer = payload.get("message", {}).get("content", "").strip()
        if not answer:
            answer = "I could not get a useful response from Ollama."
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def record_turn(self) -> Path:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "Voice mode needs microphone dependencies. Run: pip install -r requirements.txt"
            ) from exc

        print(f"Recording for {self.config.record_seconds} seconds...")
        audio = sd.rec(
            int(self.config.record_seconds * self.config.sample_rate),
            samplerate=self.config.sample_rate,
            channels=1,
            dtype="int16",
        )
        sd.wait()

        fd, path = tempfile.mkstemp(prefix="voicebot_input_", suffix=".wav")
        os.close(fd)
        wav_path = Path(path)
        with wave.open(str(wav_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(np.dtype("int16").itemsize)
            wav_file.setframerate(self.config.sample_rate)
            wav_file.writeframes(audio.tobytes())
        return wav_path

    def transcribe(self, audio_path: Path) -> str:
        if self.sarvam is None:
            raise RuntimeError("Voice mode needs SARVAM_API_KEY for speech-to-text.")

        with audio_path.open("rb") as audio_file:
            response = self.sarvam.speech_to_text.transcribe(
                file=audio_file,
                model=self.config.sarvam_stt_model,
                mode="transcribe",
            )
        return extract_text(response)

    def speak(self, text: str) -> None:
        if not self.config.speak:
            return
        if self.sarvam is None:
            raise RuntimeError("Speaking responses needs SARVAM_API_KEY for text-to-speech.")
        if winsound is None:
            raise RuntimeError("CLI audio playback is only implemented for Windows. Use the web GUI on servers.")

        response = self.sarvam.text_to_speech.convert(
            target_language_code=self.config.sarvam_language,
            text=text[:2400],
            model=self.config.sarvam_tts_model,
            speaker=self.config.sarvam_speaker,
        )
        if isinstance(response, dict):
            audio_chunks = response.get("audios", [])
        else:
            audio_chunks = getattr(response, "audios", [])
        if not audio_chunks:
            print("Sarvam TTS returned no audio.")
            return

        audio_bytes = base64.b64decode("".join(audio_chunks))
        fd, path = tempfile.mkstemp(prefix="voicebot_reply_", suffix=".wav")
        os.close(fd)
        wav_path = Path(path)
        wav_path.write_bytes(audio_bytes)
        winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)

    def run_text_loop(self) -> None:
        print("Text mode. Type exit, quit, or bye to stop.")
        while True:
            user_text = input("\nYou: ").strip()
            if should_exit(user_text):
                break
            if not user_text:
                continue
            self.respond(user_text)

    def run_voice_loop(self) -> None:
        print("Voice mode. Press Enter to record a turn, or type exit to stop.")
        while True:
            command = input("\nPress Enter to talk: ").strip()
            if should_exit(command):
                break
            audio_path = self.record_turn()
            try:
                user_text = self.transcribe(audio_path)
            finally:
                audio_path.unlink(missing_ok=True)

            if not user_text:
                print("I did not catch that.")
                continue
            print(f"You: {user_text}")
            if should_exit(user_text):
                break
            self.respond(user_text)

    def respond(self, user_text: str) -> None:
        answer = self.ask_ollama(user_text)
        print(f"\nAssistant: {answer}")
        self.speak(answer)


def extract_text(response: Any) -> str:
    if hasattr(response, "model_dump"):
        return extract_text(response.model_dump())

    if isinstance(response, dict):
        candidates = [
            response.get("transcript"),
            response.get("text"),
            response.get("transcription"),
        ]
    else:
        candidates = [
            getattr(response, "transcript", None),
            getattr(response, "text", None),
            getattr(response, "transcription", None),
        ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    try:
        payload = json.loads(str(response))
        return extract_text(payload)
    except Exception:
        return ""


def should_exit(text: str) -> bool:
    return text.lower() in {"exit", "quit", "bye", "stop"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="General-purpose Ollama voicebot with Sarvam TTS.")
    parser.add_argument("--mode", choices=["voice", "text"], default="voice")
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "llama3:latest"))
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://localhost:11434"))
    parser.add_argument("--language", default=os.getenv("SARVAM_LANGUAGE", "en-IN"))
    parser.add_argument("--speaker", default=os.getenv("SARVAM_SPEAKER", "shubh"))
    parser.add_argument("--seconds", type=int, default=int(os.getenv("VOICEBOT_RECORD_SECONDS", "6")))
    parser.add_argument("--sample-rate", type=int, default=int(os.getenv("VOICEBOT_SAMPLE_RATE", "16000")))
    parser.add_argument("--no-speak", action="store_true")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    api_key = os.getenv("SARVAM_API_KEY", "").strip()
    if not api_key and (args.mode == "voice" or not args.no_speak):
        raise SystemExit("Missing SARVAM_API_KEY. Copy .env.example to .env and add your key.")

    config = BotConfig(
        ollama_model=args.model,
        ollama_url=args.ollama_url,
        sarvam_api_key=api_key,
        sarvam_tts_model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        sarvam_stt_model=os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
        sarvam_language=args.language,
        sarvam_speaker=args.speaker,
        record_seconds=args.seconds,
        sample_rate=args.sample_rate,
        speak=not args.no_speak,
    )

    bot = VoiceBot(config)
    if args.mode == "text":
        bot.run_text_loop()
    else:
        bot.run_voice_loop()


if __name__ == "__main__":
    main()
