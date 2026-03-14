# Quick Start Guide - Voice-Controlled Robot Dog

## Prerequisites
- Python 3.13+
- `uv` package manager
- Gemini API key
- Unitree robot dog (or use dry run mode)

## Setup (5 minutes)

### 1. Install Dependencies
```bash
cd full_audio
pip install -r requirements.txt
```

### 2. Configure Environment
Create `full_audio/.env`:
```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Robot Configuration
ROBOT_ENABLED=true
ROBOT_CONNECTION_METHOD=local_sta
ROBOT_IP=192.168.8.181

# For testing without robot
ROBOT_DRY_RUN=true
```

### 3. Start the Server
```bash
cd full_audio
uv run main.py
```

### 4. Open Browser
Navigate to: **http://localhost:8000**

## Usage

1. **Click "Connect"** - Establishes WebSocket connection
2. **Click "Start Mic"** - Enables microphone
3. **Speak Commands**:
   - "Stand up"
   - "Say hello"
   - "Move forward"
   - "Turn left"
   - "Sit down"
   - "Stop"

## Testing Without Robot

Set in your `.env`:
```env
ROBOT_DRY_RUN=true
```

This simulates robot commands without physical hardware.

## Verification

Run the integration test:
```bash
cd /Users/titouv/Developer/hackathon_2026/robotdog
uv run python test_robot_integration.py
```

Expected output: All tests should pass ✓

## Troubleshooting

### Robot won't connect
- Check `ROBOT_IP` matches your robot's IP
- Verify robot is on and network accessible
- Try `ROBOT_CONNECTION_METHOD=local_ap` if on robot's WiFi

### No audio
- Check browser permissions for microphone
- Verify HTTPS or localhost (required for mic access)
- Check browser console for errors

### Commands not executing
- Check server logs for tool call execution
- Verify `ROBOT_ENABLED=true` in `.env`
- Try simpler commands: "stand" or "sit"

## Architecture

```
Voice → Browser → WebSocket → FastAPI Backend
                                    ↓
                              Gemini Live API
                                    ↓
                            Robot Controller
                                    ↓
                          Unitree WebRTC
                                    ↓
                              Robot Dog
```

## Safety Notes

⚠️ **Important Safety Features**:
- Commands are capped at 0.6 m/s max speed
- Motion duration limited to 3 seconds
- Always have emergency stop ready
- Test with `ROBOT_DRY_RUN=true` first

## Support

Check the following files for detailed documentation:
- `full_audio/README.md` - Complete feature documentation
- `INTEGRATION_COMPLETE.md` - Technical implementation details
- `robot_bridge.py` - Robot controller API reference
