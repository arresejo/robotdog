# Gemini Dog Trainers

<img src="https://upload.wikimedia.org/wikipedia/commons/thumb/1/1d/Google_Gemini_icon_2025.svg/960px-Google_Gemini_icon_2025.svg.png" width="100" align="right">

## Project Overview

This project transforms a standard Unitree robot dog into an intelligent, visually-aware companion powered by the Gemini Live API. By connecting the robot to its multimodal Gemini-based brain, it easily understands its environment and allows users to ask visual questions and perform actions.

## Hackathon Submission Details

**Team Name:** Gemini Dog Trainers  
**Team Members:** 3  

### Team Members
- Abdallah Nassur (nassur1607@gmail.com)
- Titouan Verhille (titouan.verhille@gmail.com)
- Jorge Arrese (jorge.arrese@gmail.com)

### Links
- **GitHub Repository:** https://github.com/arresejo/robotdog
- **Demo Video:** https://youtube.com/shorts/cCP1iuVv5ds?feature=share

## Setup

Install dependencies:

```sh
uv sync
```

Set the required environment variables:

```sh
export GEMINI_API_KEY='your-api-key'
export ROBOT_CONNECTION_METHOD='local_sta'
export ROBOT_IP='192.168.8.181'
```

Optional variables:

```sh
export GEMINI_LIVE_MODEL='gemini-live-2.5-flash-preview'
export ROBOT_SERIAL_NUMBER='B42D2000XXXXXXXX'
export ROBOT_USERNAME='your-unitree-login'
export ROBOT_PASSWORD='your-unitree-password'
export ROBOT_DRY_RUN='true'
export ROBOT_VIDEO_FPS='1.0'
export ROBOT_VIDEO_JPEG_QUALITY='85'
export ROBOT_VIDEO_DEBUG_DIR='.debug/robot-video'
export ROBOT_PLAY_AUDIO='true'
export ROBOT_DEBUG='true'
```

To disable sending the robot camera to Gemini:

```sh
export ROBOT_VIDEO_DISABLED='true'
```

Connection methods:
- `local_ap`
- `local_sta`
- `remote`

## Run

```sh
uv run python 'main.py'
```

When video is enabled, `main.py` subscribes to the Unitree camera feed and
forwards JPEG frames to Gemini Live continuously for the whole session with
`send_realtime_input(video=...)`, capped by `ROBOT_VIDEO_FPS` (max `1.0` as
recommended by Gemini Live docs). User prompts are still sent as normal text
turns.

If you set `ROBOT_VIDEO_DEBUG_DIR`, the bridge saves the exact JPEG frames it
forwards to Gemini so you can verify what the model actually received.

By default the CLI stays quiet while you type. Set `ROBOT_DEBUG='true'` to show
tool calls, Live API message payloads, and per-frame forwarding logs.

By default the CLI does not play Gemini audio locally, so text responses stay
responsive. Set `ROBOT_PLAY_AUDIO='true'` if you want local audio playback.

Minimal posture test with one camera frame capture:

```sh
export ROBOT_IMAGE_PATH='robot_camera_capture.ppm'
uv run python 'simple_posture_with_image_test.py'
uv run python 'simple_posture_with_image_test.py' --sit-up
```

This version is intentionally close to the upstream `sportmode.py` example:
it connects with `LocalSTA`, checks `MOTION_SWITCHER`, sends `Sit` or `RiseSit`, saves one camera frame, then disconnects.

Optional image output path:

```sh
export ROBOT_IMAGE_PATH='robot_camera_capture.ppm'
```

## Example Prompts

- `connect to the robot and say hello`
- `make a finger heart`
- `move forward for one second`
- `turn left briefly`
- `sit down`
- `stop`

## Scope

This first try intentionally supports only a narrow command set:

- `hello`
- `finger_heart`
- `stand`
- `sit`
- `move_forward`
- `move_backward`
- `turn_left`
- `turn_right`
- `stop`

Motion speed and duration are capped in code to keep the first integration conservative.
