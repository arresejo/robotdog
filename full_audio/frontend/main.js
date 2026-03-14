// --- Main Application Logic ---

const statusDiv       = document.getElementById("status");
const statusText      = statusDiv.querySelector(".status-text");
const authSection     = document.getElementById("auth-section");
const appSection      = document.getElementById("app-section");
const sessionEndSection = document.getElementById("session-end-section");
const restartBtn      = document.getElementById("restartBtn");
const micBtn          = document.getElementById("micBtn");
const micLabel        = micBtn.querySelector(".ctrl-btn-label");
const robotCameraBtn  = document.getElementById("robotCameraBtn");
const robotCamLabel   = robotCameraBtn.querySelector(".ctrl-btn-label");
const cameraBtn       = document.getElementById("cameraBtn");
const cameraLabel     = cameraBtn.querySelector(".ctrl-btn-label");
const screenBtn       = document.getElementById("screenBtn");
const screenLabel     = screenBtn.querySelector(".ctrl-btn-label");
const disconnectBtn   = document.getElementById("disconnectBtn");
const textInput       = document.getElementById("textInput");
const sendBtn         = document.getElementById("sendBtn");
const videoPreview    = document.getElementById("video-preview");
const videoPlaceholder = document.getElementById("video-placeholder");
const robotVideoCanvas = document.getElementById("robot-video-canvas");
const connectBtn      = document.getElementById("connectBtn");
const chatLog         = document.getElementById("chat-log");
const liveBadge       = document.getElementById("live-badge");

let currentGeminiMessageDiv = null;
let currentUserMessageDiv   = null;
let showingRobotCamera      = false;

function setStatus(text, cls) {
  statusText.textContent = text;
  statusDiv.className = `status ${cls}`;
}

const mediaHandler = new MediaHandler();
const geminiClient = new GeminiClient({
  onOpen: () => {
    setStatus("Connected", "connected");
    authSection.classList.add("hidden");
    appSection.classList.remove("hidden");
    liveBadge.classList.add("active");

    geminiClient.sendText(
      `System: You are now connected to control a Unitree robot dog. 
       The user can give you voice commands to control the robot.
       Introduce yourself briefly as the robot control assistant and mention 
       that you're ready to help control the robot dog with commands like 
       'stand up', 'sit down', 'move forward', or 'say hello'. Keep it short and friendly.`
    );
  },
  onMessage: (event) => {
    if (typeof event.data === "string") {
      try {
        const msg = JSON.parse(event.data);
        handleJsonMessage(msg);
      } catch (e) {
        console.error("Parse error:", e);
      }
    } else {
      mediaHandler.playAudio(event.data);
    }
  },
  onClose: (e) => {
    console.log("WS Closed:", e);
    setStatus("Disconnected", "disconnected");
    liveBadge.classList.remove("active");
    showSessionEnd();
  },
  onError: (e) => {
    console.error("WS Error:", e);
    setStatus("Connection Error", "error");
  },
});

function handleJsonMessage(msg) {
  if (msg.type === "robot_video_frame") {
    if (showingRobotCamera) displayRobotVideoFrame(msg.data);
  } else if (msg.type === "interrupted") {
    mediaHandler.stopAudioPlayback();
    currentGeminiMessageDiv = null;
    currentUserMessageDiv   = null;
  } else if (msg.type === "turn_complete") {
    currentGeminiMessageDiv = null;
    currentUserMessageDiv   = null;
  } else if (msg.type === "user") {
    if (currentUserMessageDiv) {
      currentUserMessageDiv.textContent += msg.text;
      chatLog.scrollTop = chatLog.scrollHeight;
    } else {
      currentUserMessageDiv = appendMessage("user", msg.text);
    }
  } else if (msg.type === "gemini") {
    if (currentGeminiMessageDiv) {
      currentGeminiMessageDiv.textContent += msg.text;
      chatLog.scrollTop = chatLog.scrollHeight;
    } else {
      currentGeminiMessageDiv = appendMessage("gemini", msg.text);
    }
  } else if (msg.type === "tool_call") {
    appendMessage("system", `🤖 ${msg.name}`);
  }
}

function displayRobotVideoFrame(base64Data) {
  const img = new Image();
  img.onload = () => {
    const ctx = robotVideoCanvas.getContext("2d");
    robotVideoCanvas.width  = img.width;
    robotVideoCanvas.height = img.height;
    ctx.drawImage(img, 0, 0);

    videoPreview.style.display      = "none";
    robotVideoCanvas.style.display  = "block";
    robotVideoCanvas.style.width    = "100%";
    robotVideoCanvas.style.height   = "auto";
  };
  img.src = "data:image/jpeg;base64," + base64Data;
}

function appendMessage(type, text) {
  // Remove empty-state placeholder on first message
  const emptyState = chatLog.querySelector(".chat-empty-state");
  if (emptyState) emptyState.remove();

  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${type}`;
  msgDiv.textContent = text;
  chatLog.appendChild(msgDiv);
  chatLog.scrollTop = chatLog.scrollHeight;
  return msgDiv;
}

// ─── Connect ───────────────────────────────────────────
connectBtn.onclick = async () => {
  setStatus("Connecting…", "disconnected");
  connectBtn.disabled = true;

  try {
    await mediaHandler.initializeAudio();
    geminiClient.connect();
  } catch (error) {
    console.error("Connection error:", error);
    setStatus("Connection Failed", "error");
    connectBtn.disabled = false;
  }
};

// ─── Disconnect ────────────────────────────────────────
disconnectBtn.onclick = () => geminiClient.disconnect();

// ─── Microphone ────────────────────────────────────────
micBtn.onclick = async () => {
  if (mediaHandler.isRecording) {
    mediaHandler.stopAudio();
    micLabel.textContent = "Mic";
    micBtn.classList.remove("recording");
  } else {
    try {
      await mediaHandler.startAudio((data) => {
        if (geminiClient.isConnected()) geminiClient.send(data);
      });
      micLabel.textContent = "Stop Mic";
      micBtn.classList.add("recording");
    } catch (e) {
      alert("Could not start audio capture");
    }
  }
};

// ─── Robot Camera ──────────────────────────────────────
robotCameraBtn.onclick = () => {
  if (showingRobotCamera) {
    showingRobotCamera = false;
    robotCamLabel.textContent = "Robot Cam";
    robotCameraBtn.classList.remove("active");
    robotVideoCanvas.style.display = "none";
    videoPreview.style.display     = "block";
    videoPlaceholder.classList.remove("hidden");
    liveBadge.classList.remove("active");
  } else {
    showingRobotCamera = true;
    robotCamLabel.textContent = "Hide Cam";
    robotCameraBtn.classList.add("active");
    videoPlaceholder.classList.add("hidden");
    liveBadge.classList.add("active");

    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      cameraLabel.textContent = "Camera";
      screenLabel.textContent = "Screen";
      cameraBtn.classList.remove("active");
      screenBtn.classList.remove("active");
    }

    robotVideoCanvas.style.display = "block";
    videoPreview.style.display     = "none";
  }
};

// ─── Browser Camera ────────────────────────────────────
cameraBtn.onclick = async () => {
  if (cameraBtn.classList.contains("active")) {
    mediaHandler.stopVideo(videoPreview);
    cameraLabel.textContent = "Camera";
    cameraBtn.classList.remove("active");
    screenBtn.classList.remove("active");
    if (!showingRobotCamera) videoPlaceholder.classList.remove("hidden");
  } else {
    if (showingRobotCamera) {
      showingRobotCamera = false;
      robotCamLabel.textContent = "Robot Cam";
      robotCameraBtn.classList.remove("active");
      robotVideoCanvas.style.display = "none";
    }

    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      screenLabel.textContent = "Screen";
      screenBtn.classList.remove("active");
    }

    try {
      await mediaHandler.startVideo(videoPreview, (base64Data) => {
        if (geminiClient.isConnected()) geminiClient.sendImage(base64Data);
      });
      cameraLabel.textContent = "Stop Camera";
      cameraBtn.classList.add("active");
      videoPreview.style.display = "block";
      videoPlaceholder.classList.add("hidden");
      liveBadge.classList.add("active");
    } catch (e) {
      alert("Could not access camera");
    }
  }
};

// ─── Screen Share ──────────────────────────────────────
screenBtn.onclick = async () => {
  if (screenBtn.classList.contains("active")) {
    mediaHandler.stopVideo(videoPreview);
    screenLabel.textContent = "Screen";
    screenBtn.classList.remove("active");
    if (!showingRobotCamera) videoPlaceholder.classList.remove("hidden");
  } else {
    if (showingRobotCamera) {
      showingRobotCamera = false;
      robotCamLabel.textContent = "Robot Cam";
      robotCameraBtn.classList.remove("active");
      robotVideoCanvas.style.display = "none";
    }

    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      cameraLabel.textContent = "Camera";
      cameraBtn.classList.remove("active");
    }

    try {
      await mediaHandler.startScreen(
        videoPreview,
        (base64Data) => {
          if (geminiClient.isConnected()) geminiClient.sendImage(base64Data);
        },
        () => {
          screenLabel.textContent = "Screen";
          screenBtn.classList.remove("active");
          if (!showingRobotCamera) videoPlaceholder.classList.remove("hidden");
        }
      );
      screenLabel.textContent = "Stop Screen";
      screenBtn.classList.add("active");
      videoPreview.style.display = "block";
      videoPlaceholder.classList.add("hidden");
      liveBadge.classList.add("active");
    } catch (e) {
      alert("Could not share screen");
    }
  }
};

// ─── Text Input ────────────────────────────────────────
sendBtn.onclick = sendText;
textInput.onkeypress = (e) => { if (e.key === "Enter") sendText(); };

function sendText() {
  const text = textInput.value.trim();
  if (text && geminiClient.isConnected()) {
    geminiClient.sendText(text);
    appendMessage("user", text);
    textInput.value = "";
  }
}

// ─── Reset ────────────────────────────────────────────
function resetUI() {
  authSection.classList.remove("hidden");
  appSection.classList.add("hidden");
  sessionEndSection.classList.add("hidden");

  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
  videoPlaceholder.classList.remove("hidden");

  showingRobotCamera = false;
  robotVideoCanvas.style.display = "none";
  videoPreview.style.display     = "block";

  micLabel.textContent      = "Mic";
  robotCamLabel.textContent = "Robot Cam";
  cameraLabel.textContent   = "Camera";
  screenLabel.textContent   = "Screen";
  micBtn.classList.remove("recording");
  robotCameraBtn.classList.remove("active");
  cameraBtn.classList.remove("active");
  screenBtn.classList.remove("active");
  liveBadge.classList.remove("active");

  // Restore empty state in chat
  chatLog.innerHTML = `
    <div class="chat-empty-state">
      <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
        <path d="M16 0C16 8.837 8.837 16 0 16C8.837 16 16 23.163 16 32C16 23.163 23.163 16 32 16C23.163 16 16 8.837 16 0Z" fill="url(#empty-grad2)" opacity="0.5"/>
        <defs>
          <linearGradient id="empty-grad2" x1="0" y1="0" x2="32" y2="32">
            <stop offset="0%" stop-color="#4285F4"/>
            <stop offset="100%" stop-color="#9B72F8"/>
          </linearGradient>
        </defs>
      </svg>
      <span>Conversation will appear here</span>
    </div>`;

  connectBtn.disabled = false;
}

function showSessionEnd() {
  appSection.classList.add("hidden");
  sessionEndSection.classList.remove("hidden");
  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
}

restartBtn.onclick = () => resetUI();
