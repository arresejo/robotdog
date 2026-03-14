# Robot Dog Voice Control - Gemini Live API + Unitree WebRTC

A real-time voice-controlled robot dog application using the [Google Gen AI Python SDK](https://github.com/googleapis/python-genai) for the backend and vanilla JavaScript for the frontend. Control a Unitree robot dog through natural voice commands via browser microphone.

## Quick Start

### 1. Backend Setup

Install dependencies and start the FastAPI server using `uv`:

```bash
# From the full_audio directory
cd full_audio

# Install dependencies
uv pip install -r requirements.txt

# Start the server
uv run main.py
```

### 2. Environment Configuration

Create a `.env` file in the `full_audio` directory with the following:

```env
# Required: Gemini API Key
GEMINI_API_KEY=your_api_key_here

# Optional: Model selection
MODEL=gemini-2.5-flash-native-audio-preview-12-2025

# Optional: Server port
PORT=8000

# Robot Configuration (required for robot control)
ROBOT_ENABLED=true
ROBOT_CONNECTION_METHOD=local_sta
ROBOT_IP=192.168.8.181

# Optional Robot Settings
ROBOT_SERIAL_NUMBER=B42D2000XXXXXXXX
ROBOT_USERNAME=your-unitree-login
ROBOT_PASSWORD=your-unitree-password
ROBOT_DRY_RUN=false
ROBOT_VIDEO_DISABLED=true
ROBOT_DEBUG=false
```

**Connection Methods:**
- `local_ap` - Direct WiFi hotspot
- `local_sta` - Local network (default)
- `remote` - Remote connection

### 3. Frontend

Open your browser and navigate to:

[http://localhost:8000](http://localhost:8000)

## Features

- **Voice Control**: Use your microphone to issue natural language commands to the robot
- **Real-time Audio Streaming**: Low-latency bi-directional audio via Gemini Live API
- **Robot Camera Feed**: Robot's camera view is streamed to Gemini for visual context
- **Robot Control Tools**: Backend Gemini tools execute actual robot commands
- **Optional Browser Video**: Can also share browser camera or screen for additional context
- **Text Input**: Alternative to voice commands

## Supported Robot Commands

Say any of these commands naturally:
- **"Hello" / "Wave"** - Robot performs hello gesture
- **"Stand up"** - Robot stands from sitting position
- **"Sit down"** - Robot sits down
- **"Move forward"** - Robot walks forward briefly
- **"Move backward"** - Robot walks backward briefly
- **"Turn left" / "Turn right"** - Robot rotates in place
- **"Stop"** - Emergency stop for all motion

## Project Structure

```
/full_audio
├── main.py             # FastAPI server & WebSocket endpoint with robot integration
├── gemini_live.py      # Gemini Live API wrapper with tool support
├── requirements.txt    # Python dependencies (includes unitree-webrtc-connect)
└── frontend/
    ├── index.html      # Robot control UI
    ├── main.js         # Application logic
    ├── gemini-client.js # WebSocket client for backend communication
    ├── media-handler.js # Audio/Video capture and playback
    └── pcm-processor.js # AudioWorklet for PCM processing
```

## How It Works

1. **Audio Input**: Browser captures microphone audio at 16kHz PCM and streams it via WebSocket
2. **Robot Video**: Robot's camera feed (if enabled) is continuously captured and sent to Gemini
3. **Gemini Processing**: Backend forwards audio and video to Gemini Live API for speech recognition, visual understanding, and intent analysis
4. **Tool Execution**: When Gemini detects a robot command, it calls the corresponding tool function
5. **Robot Control**: Backend executes the command via Unitree WebRTC connection
6. **Audio Response**: Gemini's voice response streams back to the browser for playback

### Video Inputs
The system supports two video sources:
- **Robot Camera** (server-side): Streams from robot's onboard camera to Gemini (~1 FPS)
- **Browser Camera/Screen** (client-side): Optional additional visual context from user's device

## Safety Features

- Motion commands are capped at safe speeds (max 0.6 m/s)
- Duration limits prevent extended unsafe motion (max 3 seconds)
- Robot automatically switches to "normal" motion mode before movement
- Dry run mode available for testing without actual robot connection
- Video streaming can be disabled if not needed (`ROBOT_VIDEO_DISABLED=true`)

## Development

### Testing Without a Robot

Set `ROBOT_DRY_RUN=true` in your `.env` file to simulate robot commands without a physical connection.

### Debugging

Enable detailed logging:
```env
ROBOT_DEBUG=true
```

This will show:
- Robot connection status
- Tool call invocations
- Command execution results
- WebRTC communication logs
- Robot video frame forwarding (sequence number, size, etc.)
