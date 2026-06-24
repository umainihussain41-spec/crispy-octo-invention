const statusEl = document.querySelector("#status");
const meterEl = document.querySelector("#meter");
const toggleListen = document.querySelector("#toggleListen");
const resetSession = document.querySelector("#resetSession");
const conversation = document.querySelector("#conversation");
const textForm = document.querySelector("#textForm");
const textInput = document.querySelector("#textInput");
const voiceIsolation = document.querySelector("#voiceIsolation");
const autoReply = document.querySelector("#autoReply");
const sensitivity = document.querySelector("#sensitivity");

let sessionId = crypto.randomUUID();
let stream = null;
let audioContext = null;
let analyser = null;
let recorder = null;
let chunks = [];
let listening = false;
let recording = false;
let speaking = false;
let speechStart = 0;
let lastVoiceAt = 0;
let rafId = null;

const setStatus = (label, state = "") => {
  statusEl.textContent = label;
  statusEl.className = `status-pill ${state}`.trim();
};

const appendMessage = (role, text) => {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role === "user" ? "You" : "Assistant";
  const body = document.createElement("p");
  body.textContent = text;
  item.append(label, body);
  conversation.append(item);
  conversation.scrollTop = conversation.scrollHeight;
};

const loadConfig = async () => {
  const res = await fetch("/api/config");
  const config = await res.json();
  document.querySelector("#chatModel").textContent = config.chat_model;
  document.querySelector("#sttModel").textContent = config.stt_model;
  document.querySelector("#ttsModel").textContent = config.tts_model;
};

const startMic = async () => {
  const constraints = {
    audio: {
      echoCancellation: voiceIsolation.checked,
      noiseSuppression: voiceIsolation.checked,
      autoGainControl: voiceIsolation.checked,
      channelCount: 1,
    },
  };
  stream = await navigator.mediaDevices.getUserMedia(constraints);
  audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(stream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
};

const enableListening = async () => {
  if (!stream) await startMic();
  listening = true;
  toggleListen.textContent = "Pause Mic";
  setStatus("Listening", "listening");
  monitor();
};

const disableListening = () => {
  listening = false;
  toggleListen.textContent = "Enable Mic";
  setStatus("Paused");
  meterEl.style.width = "0";
  cancelAnimationFrame(rafId);
  if (recording) stopRecording();
};

const rmsLevel = () => {
  const data = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(data);
  let sum = 0;
  for (const value of data) {
    const centered = (value - 128) / 128;
    sum += centered * centered;
  }
  return Math.sqrt(sum / data.length);
};

const startRecording = () => {
  if (recording || speaking) return;
  chunks = [];
  recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  recorder.ondataavailable = event => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  recorder.onstop = submitAudio;
  recorder.start();
  recording = true;
  speechStart = performance.now();
  setStatus("Listening", "listening");
};

const stopRecording = () => {
  if (!recording || recorder.state === "inactive") return;
  recording = false;
  setStatus("Thinking", "processing");
  recorder.stop();
};

const monitor = () => {
  if (!listening || !analyser) return;
  const level = rmsLevel();
  const threshold = Number(sensitivity.value);
  const now = performance.now();
  meterEl.style.width = `${Math.min(100, Math.round(level * 900))}%`;

  if (!speaking && level > threshold) {
    lastVoiceAt = now;
    if (!recording) startRecording();
  }

  if (recording && now - lastVoiceAt > 900 && now - speechStart > 900) {
    stopRecording();
  }

  rafId = requestAnimationFrame(monitor);
};

const submitAudio = async () => {
  const blob = new Blob(chunks, { type: "audio/webm" });
  if (blob.size < 1200) {
    setStatus("Idle");
    return;
  }

  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("audio", blob, "turn.webm");
  await submitTurn(form);
};

const submitText = async text => {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("text", text);
  await submitTurn(form);
};

const submitTurn = async form => {
  try {
    speaking = true;
    setStatus("Thinking", "processing");
    const res = await fetch("/api/chat", { method: "POST", body: form });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || "Request failed");
    if (payload.transcript) appendMessage("user", payload.transcript);
    appendMessage("assistant", payload.answer);
    if (autoReply.checked && payload.audio_base64) {
      await playAudio(payload.audio_base64);
    }
  } catch (error) {
    appendMessage("assistant", error.message);
  } finally {
    speaking = false;
    setStatus(listening ? "Listening" : "Idle", listening ? "listening" : "");
  }
};

const playAudio = audioBase64 => {
  return new Promise(resolve => {
    const audio = new Audio(`data:audio/wav;base64,${audioBase64}`);
    audio.onended = resolve;
    audio.onerror = resolve;
    audio.play().catch(resolve);
  });
};

toggleListen.addEventListener("click", async () => {
  if (!listening) {
    await enableListening();
    return;
  }

  disableListening();
});

textForm.addEventListener("submit", async event => {
  event.preventDefault();
  const text = textInput.value.trim();
  if (!text) return;
  textInput.value = "";
  await submitText(text);
});

resetSession.addEventListener("click", async () => {
  const res = await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  const payload = await res.json();
  sessionId = payload.session_id;
  conversation.innerHTML = "";
  appendMessage("assistant", "Session reset. Ready for the next support issue.");
});

loadConfig().catch(() => {
  document.querySelector("#chatModel").textContent = "Unavailable";
  document.querySelector("#sttModel").textContent = "Unavailable";
  document.querySelector("#ttsModel").textContent = "Unavailable";
});

const tryAutoStart = async () => {
  if (!navigator.permissions?.query) return;
  try {
    const permission = await navigator.permissions.query({ name: "microphone" });
    if (permission.state === "granted") await enableListening();
  } catch {
    setStatus("Mic needed");
  }
};

tryAutoStart();
