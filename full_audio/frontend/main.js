// --- Main Application Logic ---

const statusDiv = document.getElementById("status");
const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");
const sessionEndSection = document.getElementById("session-end-section");
const restartBtn = document.getElementById("restartBtn");
const micBtn = document.getElementById("micBtn");
const robotCameraBtn = document.getElementById("robotCameraBtn");
const cameraBtn = document.getElementById("cameraBtn");
const screenBtn = document.getElementById("screenBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");
const videoPreview = document.getElementById("video-preview");
const videoPlaceholder = document.getElementById("video-placeholder");
const robotVideoCanvas = document.getElementById("robot-video-canvas");
const connectBtn = document.getElementById("connectBtn");
const chatLog = document.getElementById("chat-log");

let currentGeminiMessageDiv = null;
let currentUserMessageDiv = null;
let showingRobotCamera = false;

const mediaHandler = new MediaHandler();
const geminiClient = new GeminiClient({
  onOpen: () => {
    statusDiv.textContent = "Connected";
    statusDiv.className = "status connected";
    authSection.classList.add("hidden");
    appSection.classList.remove("hidden");

    // Send hidden instruction
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
      // Binary data (audio response from Gemini)
      mediaHandler.playAudio(event.data);
    }
  },
  onClose: (e) => {
    console.log("WS Closed:", e);
    statusDiv.textContent = "Disconnected";
    statusDiv.className = "status disconnected";
    showSessionEnd();
  },
  onError: (e) => {
    console.error("WS Error:", e);
    statusDiv.textContent = "Connection Error";
    statusDiv.className = "status error";
  },
});

function handleJsonMessage(msg) {
  if (msg.type === "robot_video_frame") {
    // Handle robot video frame
    if (showingRobotCamera) {
      displayRobotVideoFrame(msg.data);
    }
  } else if (msg.type === "interrupted") {
    mediaHandler.stopAudioPlayback();
    currentGeminiMessageDiv = null;
    currentUserMessageDiv = null;
  } else if (msg.type === "turn_complete") {
    currentGeminiMessageDiv = null;
    currentUserMessageDiv = null;
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
    // Display tool execution
    appendMessage("system", `🤖 Executing: ${msg.name}`);
  }
}

function displayRobotVideoFrame(base64Data) {
  const img = new Image();
  img.onload = () => {
    const ctx = robotVideoCanvas.getContext("2d");
    robotVideoCanvas.width = img.width;
    robotVideoCanvas.height = img.height;
    ctx.drawImage(img, 0, 0);
    
    // Copy to video preview canvas for display
    const videoCtx = videoPreview.getContext ? null : document.getElementById("video-canvas").getContext("2d");
    if (videoCtx) {
      const canvas = document.getElementById("video-canvas");
      canvas.width = img.width;
      canvas.height = img.height;
      videoCtx.drawImage(img, 0, 0);
    }
    
    // Update video preview by drawing on it
    videoPreview.style.display = "none";
    robotVideoCanvas.style.display = "block";
    robotVideoCanvas.style.width = "100%";
    robotVideoCanvas.style.height = "auto";
  };
  img.src = "data:image/jpeg;base64," + base64Data;
}

function appendMessage(type, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${type}`;
  msgDiv.textContent = text;
  chatLog.appendChild(msgDiv);
  chatLog.scrollTop = chatLog.scrollHeight;
  return msgDiv;
}

// Connect Button Handler
connectBtn.onclick = async () => {
  statusDiv.textContent = "Connecting...";
  connectBtn.disabled = true;

  try {
    // Initialize audio context on user gesture
    await mediaHandler.initializeAudio();

    geminiClient.connect();
  } catch (error) {
    console.error("Connection error:", error);
    statusDiv.textContent = "Connection Failed: " + error.message;
    statusDiv.className = "status error";
    connectBtn.disabled = false;
  }
};

// UI Controls
disconnectBtn.onclick = () => {
  geminiClient.disconnect();
};

micBtn.onclick = async () => {
  if (mediaHandler.isRecording) {
    mediaHandler.stopAudio();
    micBtn.textContent = "Start Mic";
  } else {
    try {
      await mediaHandler.startAudio((data) => {
        if (geminiClient.isConnected()) {
          geminiClient.send(data);
        }
      });
      micBtn.textContent = "Stop Mic";
    } catch (e) {
      alert("Could not start audio capture");
    }
  }
};

robotCameraBtn.onclick = () => {
  if (showingRobotCamera) {
    // Stop showing robot camera
    showingRobotCamera = false;
    robotCameraBtn.textContent = "Show Robot Camera";
    robotVideoCanvas.style.display = "none";
    videoPreview.style.display = "block";
    videoPlaceholder.classList.remove("hidden");
  } else {
    // Show robot camera
    showingRobotCamera = true;
    robotCameraBtn.textContent = "Hide Robot Camera";
    videoPlaceholder.classList.add("hidden");
    
    // Stop any browser video streams
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      cameraBtn.textContent = "Browser Camera";
      screenBtn.textContent = "Share Screen";
    }
    
    // Robot frames will now be displayed via handleJsonMessage
    robotVideoCanvas.style.display = "block";
    videoPreview.style.display = "none";
  }
};

cameraBtn.onclick = async () => {
  if (cameraBtn.textContent === "Stop Browser Camera") {
    mediaHandler.stopVideo(videoPreview);
    cameraBtn.textContent = "Browser Camera";
    screenBtn.textContent = "Share Screen";
    if (!showingRobotCamera) {
      videoPlaceholder.classList.remove("hidden");
    }
  } else {
    // Stop robot camera if showing
    if (showingRobotCamera) {
      showingRobotCamera = false;
      robotCameraBtn.textContent = "Show Robot Camera";
      robotVideoCanvas.style.display = "none";
    }
    
    // If screen share is active, stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      screenBtn.textContent = "Share Screen";
    }

    try {
      await mediaHandler.startVideo(videoPreview, (base64Data) => {
        if (geminiClient.isConnected()) {
          geminiClient.sendImage(base64Data);
        }
      });
      cameraBtn.textContent = "Stop Browser Camera";
      screenBtn.textContent = "Share Screen";
      videoPreview.style.display = "block";
      videoPlaceholder.classList.add("hidden");
    } catch (e) {
      alert("Could not access camera");
    }
  }
};

screenBtn.onclick = async () => {
  if (screenBtn.textContent === "Stop Sharing") {
    mediaHandler.stopVideo(videoPreview);
    screenBtn.textContent = "Share Screen";
    cameraBtn.textContent = "Browser Camera";
    if (!showingRobotCamera) {
      videoPlaceholder.classList.remove("hidden");
    }
  } else {
    // Stop robot camera if showing
    if (showingRobotCamera) {
      showingRobotCamera = false;
      robotCameraBtn.textContent = "Show Robot Camera";
      robotVideoCanvas.style.display = "none";
    }
    
    // If camera is active, stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      cameraBtn.textContent = "Browser Camera";
    }

    try {
      await mediaHandler.startScreen(
        videoPreview,
        (base64Data) => {
          if (geminiClient.isConnected()) {
            geminiClient.sendImage(base64Data);
          }
        },
        () => {
          // onEnded callback (e.g. user stopped sharing from browser)
          screenBtn.textContent = "Share Screen";
          if (!showingRobotCamera) {
            videoPlaceholder.classList.remove("hidden");
          }
        }
      );
      screenBtn.textContent = "Stop Sharing";
      cameraBtn.textContent = "Browser Camera";
      videoPreview.style.display = "block";
      videoPlaceholder.classList.add("hidden");
    } catch (e) {
      alert("Could not share screen");
    }
  }
};

sendBtn.onclick = sendText;
textInput.onkeypress = (e) => {
  if (e.key === "Enter") sendText();
};

function sendText() {
  const text = textInput.value;
  if (text && geminiClient.isConnected()) {
    geminiClient.sendText(text);
    appendMessage("user", text);
    textInput.value = "";
  }
}

function resetUI() {
  authSection.classList.remove("hidden");
  appSection.classList.add("hidden");
  sessionEndSection.classList.add("hidden");

  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
  videoPlaceholder.classList.remove("hidden");
  
  showingRobotCamera = false;
  robotVideoCanvas.style.display = "none";
  videoPreview.style.display = "block";

  micBtn.textContent = "Start Mic";
  robotCameraBtn.textContent = "Show Robot Camera";
  cameraBtn.textContent = "Browser Camera";
  screenBtn.textContent = "Share Screen";
  chatLog.innerHTML = "";
  connectBtn.disabled = false;
}

function showSessionEnd() {
  appSection.classList.add("hidden");
  sessionEndSection.classList.remove("hidden");
  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
}

restartBtn.onclick = () => {
  resetUI();
};
