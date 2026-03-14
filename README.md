# robotdog

Minimal Gemini Live API to Unitree WebRTC bridge for simple robot commands.

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
```

Connection methods:

- `local_ap`
- `local_sta`
- `remote`

## Run

```sh
uv run python 'main.py'
```

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

Example prompts:

- `connect to the robot and say hello`
- `move forward for one second`
- `turn left briefly`
- `sit down`
- `stop`

## Scope

This first try intentionally supports only a narrow command set:

- `hello`
- `stand`
- `sit`
- `move_forward`
- `move_backward`
- `turn_left`
- `turn_right`
- `stop`

Motion speed and duration are capped in code to keep the first integration conservative.
