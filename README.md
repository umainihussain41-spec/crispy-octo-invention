# General Purpose Ollama + Sarvam Voicebot

This is a small voicebot that can run as either a local CLI bot or a browser GUI:

- uses Sarvam `sarvam-30b` by default for real-time tech-support conversations
- can still use a local Ollama model if `AI_PROVIDER=ollama`
- uses Sarvam Saaras v3 for speech-to-text in voice mode
- uses Sarvam Bulbul v3 for text-to-speech
- supports typed chat mode as a fallback
- includes browser-side voice activity detection so it starts responding after you stop speaking
- requests browser microphone noise suppression, echo cancellation, and auto gain control for better voice isolation

Detected Ollama models on this machine:

- `llama3:latest`
- `mistral:latest`
- `phi3:mini`
- `deepseek-r1:latest`
- `qwen2.5-coder:7b-instruct`
- `deepseek-coder:6.7b-instruct`
- `deepseek-coder:6.7b`
- `llama3:8b`
- `gpt-3.5-turbo:latest`
- `nomic-embed-text:latest`

The browser GUI defaults to Sarvam `sarvam-30b`, which Sarvam positions for real-time voice-agent and conversational workloads. Use `sarvam-105b` when you want higher-quality reasoning and can accept more latency/cost.

The CLI defaults to `llama3:latest` when using Ollama, because it is the best general chat default from the installed local options.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set:

```text
SARVAM_API_KEY=your_sarvam_api_key_here
```

Make sure Ollama is running:

```powershell
ollama serve
```

In another terminal, start the bot:

```powershell
python voicebot.py
```

## Browser GUI

Run the Railway-ready web app locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn web_app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Click `Enable Mic` once if the browser asks for microphone permission. After that, the browser listens continuously, starts recording when your voice crosses the sensitivity threshold, stops after a short silence, sends the turn to Sarvam STT, gets a tech-support answer from Sarvam chat, and plays the reply using Sarvam TTS.

If microphone permission was already granted for the site, the GUI starts listening automatically on page load.

The `Voice isolation` toggle uses browser microphone constraints:

- `noiseSuppression`
- `echoCancellation`
- `autoGainControl`
- single-channel capture

This improves isolation in normal laptop/headset conditions, but it is not biometric speaker separation. For best results, use a headset mic or stay close to the microphone.

## Usage

Voice mode records a fixed-size turn, transcribes it with Sarvam, sends it to Ollama, then speaks the answer with Sarvam TTS:

```powershell
python voicebot.py --mode voice
```

Typed mode skips microphone recording but still speaks responses:

```powershell
python voicebot.py --mode text
```

Useful options:

```powershell
python voicebot.py --model mistral:latest
python voicebot.py --seconds 8
python voicebot.py --language hi-IN --speaker shubh
python voicebot.py --no-speak
```

Say or type `exit`, `quit`, or `bye` to stop.

## Railway

This repo includes:

- `Procfile`
- `runtime.txt`
- `web_app.py`

Set these Railway environment variables:

```text
SARVAM_API_KEY=your_sarvam_api_key_here
AI_PROVIDER=sarvam
SARVAM_CHAT_MODEL=sarvam-30b
SARVAM_STT_MODEL=saaras:v3
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_LANGUAGE=en-IN
SARVAM_SPEAKER=shubh
```

Railway will run:

```text
uvicorn web_app:app --host 0.0.0.0 --port $PORT
```
