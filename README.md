# robotdog

Navigate a Unitree Go2 to a target object (e.g. a chair) using camera-based detection and visual servoing.

## How it works

1. **Camera stream** — receives video from the Go2 via WebRTC
2. **YOLOv8 detection** — detects the target object in each frame
3. **Depth estimation** — estimates distance from bounding box size
4. **Visual servoing** — proportional controller steers the robot toward the target
5. **Obstacle avoidance** — the Go2's built-in avoidance stays active during navigation

## Setup

```bash
uv sync
```

## Usage

### Navigate to a target
```bash
uv run python main.py --ip 192.168.8.181 --target chair
```

### Sniff SLAM/navigation protocol (for future SLAM navigation)
```bash
uv run python -m src.sniffer --ip 192.168.8.181
```

## Project structure

```
src/
  navigator.py       # Main navigation controller (visual servoing loop)
  detector.py        # YOLOv8 object detection
  depth_estimator.py # Pixel → world coordinate projection
  state_tracker.py   # Robot pose & state subscription
  sniffer.py         # Protocol sniffer for reverse-engineering SLAM nav
```

## Configuration

Edit constants in `src/navigator.py`:
- `ARRIVAL_DISTANCE` — how close to stop (default: 1.0m)
- `MAX_FORWARD_SPEED` — top speed (default: 0.5 m/s)
- `KP_FORWARD` / `KP_ROTATION` — proportional gains

Edit camera params in `src/depth_estimator.py`:
- `CAMERA_FX`, `CAMERA_FY` — focal lengths
- `OBJECT_HEIGHTS` — real-world sizes of target objects
