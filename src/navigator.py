"""Navigation controller — navigate the Go2 to a detected target object.

Uses visual servoing: detect target with YOLO, estimate bearing/distance
from bounding box, and send velocity commands via unitree_webrtc_connect.

Usage:
    uv run python main.py --ip 192.168.8.181 --target backpack
"""

import argparse
import asyncio
import json
import logging
import math
import random
import sys
import time

import numpy as np

# IMPORTANT: import unitree_webrtc_connect BEFORE aiortc
# The library monkey-patches aioice.Connection in its __init__.py
from unitree_webrtc_connect.constants import DATA_CHANNEL_TYPE, RTC_TOPIC, SPORT_CMD
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)

from src.depth_estimator import estimate_bearing, estimate_distance
from src.detector import ObjectDetector

# --- Logging setup ---
# Suppress the library's per-message INFO logs (it logs every send/recv)
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("navigator")
log.setLevel(logging.INFO)

# --- Control parameters ---
ARRIVAL_DISTANCE = 1.0       # stop distance (m)
KP_FORWARD = 0.15            # forward speed gain (m/s per m error)
KP_ROTATION = 1.2            # rotation speed gain (rad/s per rad error)
MAX_FORWARD_SPEED = 0.5      # m/s
MAX_ROTATION_SPEED = 0.8     # rad/s
MIN_CONFIDENCE = 0.5
LOST_TARGET_FRAMES = 15      # frames without detection before searching
SEARCH_ROTATION_SPEED = 0.4  # rad/s when searching
CONTROL_HZ = 10


class Navigator:
    """Visual servoing navigator — drives the Go2 toward a detected target."""

    def __init__(self, conn: UnitreeWebRTCConnection, target_class: str = "backpack"):
        self.conn = conn
        self.target_class = target_class
        self.detector = ObjectDetector(confidence=MIN_CONFIDENCE)
        self.latest_frame: np.ndarray | None = None
        self._running = False
        self._lost_counter = 0

    async def start(self):
        """Connect, initialize robot, and run the control loop."""
        log.info("Connecting to Go2...")
        await self.conn.connect()
        log.info("Connected ✓")

        # Enable video stream
        self.conn.video.switchVideoChannel(True)

        # Wait briefly for the library's on_track handler to finish processing
        await asyncio.sleep(1)

        # Get the video track from the peer connection and start reading frames
        video_track = None
        for receiver in self.conn.pc.getReceivers():
            if receiver.track and receiver.track.kind == "video":
                video_track = receiver.track
                break

        if video_track:
            log.info("Video track found — starting frame reader")
            asyncio.create_task(self._read_frames(video_track))
        else:
            log.warning("No video track found!")

        # Wait for video frames to start arriving
        log.info("Waiting for video frames...")
        for _ in range(50):  # up to 5 seconds
            if self.latest_frame is not None:
                break
            await asyncio.sleep(0.1)

        if self.latest_frame is None:
            log.warning("No video frames received yet — continuing anyway")
        else:
            h, w = self.latest_frame.shape[:2]
            log.info("Video streaming: %dx%d ✓", w, h)

        # Switch to sport mode and stand up
        await self._prepare_robot()

        log.info("Starting navigation to '%s'...", self.target_class)
        self._running = True

        try:
            await self._control_loop()
        finally:
            self._send_stop()
            log.info("Navigation ended.")

    async def _read_frames(self, track):
        """Continuously read video frames in the background."""
        count = 0
        while True:
            try:
                frame = await track.recv()
                self.latest_frame = frame.to_ndarray(format="bgr24")
                count += 1
                if count % 300 == 0:
                    log.info("Video frames: %d", count)
            except Exception:
                log.warning("Video track ended after %d frames", count)
                break

    async def _prepare_robot(self):
        """Ensure robot is in normal sport mode and standing."""
        # Check current mode
        log.info("Checking motion mode...")
        response = await self.conn.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["MOTION_SWITCHER"],
            {"api_id": 1001},
        )

        current_mode = "unknown"
        try:
            if response["data"]["header"]["status"]["code"] == 0:
                data = json.loads(response["data"]["data"])
                current_mode = data.get("name", "unknown")
        except (KeyError, TypeError, json.JSONDecodeError):
            pass

        log.info("Current motion mode: %s", current_mode)

        if current_mode != "normal":
            log.info("Switching to normal mode...")
            await self.conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["MOTION_SWITCHER"],
                {"api_id": 1002, "parameter": {"name": "normal"}},
            )
            await asyncio.sleep(3)

        # Recovery stand to ensure robot is upright and ready
        log.info("Sending RecoveryStand...")
        await self.conn.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["RecoveryStand"]},
        )
        await asyncio.sleep(2)
        log.info("Robot ready ✓")

        # Enable obstacle avoidance
        try:
            await self.conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["OBSTACLES_AVOID"],
                {"api_id": 1001, "parameter": {"enable": True}},
            )
            log.info("Obstacle avoidance enabled ✓")
        except Exception as e:
            log.warning("Could not enable obstacle avoidance: %s", e)

    def _send_move(self, forward: float, lateral: float, rotation: float):
        """Send a velocity command (fire-and-forget, non-blocking)."""
        generated_id = int(time.time() * 1000) % 2147483648 + random.randint(0, 1000)
        payload = {
            "header": {
                "identity": {
                    "id": generated_id,
                    "api_id": SPORT_CMD["Move"],
                }
            },
            "parameter": json.dumps({"x": forward, "y": lateral, "z": rotation}),
        }
        self.conn.datachannel.pub_sub.publish_without_callback(
            RTC_TOPIC["SPORT_MOD"], payload, DATA_CHANNEL_TYPE["REQUEST"]
        )

    def _send_stop(self):
        """Send a stop command (fire-and-forget, non-blocking)."""
        generated_id = int(time.time() * 1000) % 2147483648 + random.randint(0, 1000)
        payload = {
            "header": {
                "identity": {
                    "id": generated_id,
                    "api_id": SPORT_CMD["StopMove"],
                }
            },
            "parameter": "",
        }
        self.conn.datachannel.pub_sub.publish_without_callback(
            RTC_TOPIC["SPORT_MOD"], payload, DATA_CHANNEL_TYPE["REQUEST"]
        )

    async def _control_loop(self):
        """Main control loop — detect, estimate, steer."""
        period = 1.0 / CONTROL_HZ

        while self._running:
            frame = self.latest_frame

            if frame is None:
                await asyncio.sleep(period)
                continue

            # Detect target
            detection = self.detector.detect(frame, self.target_class)

            if detection is None:
                self._lost_counter += 1
                if self._lost_counter == LOST_TARGET_FRAMES:
                    log.info("Target lost — searching...")
                if self._lost_counter >= LOST_TARGET_FRAMES:
                    # Rotate in place to search for target
                    self._send_move(0.0, 0.0, SEARCH_ROTATION_SPEED)
                await asyncio.sleep(period)
                continue

            # Target found
            if self._lost_counter >= LOST_TARGET_FRAMES:
                log.info("Target re-acquired!")
            self._lost_counter = 0

            cx, cy = detection["center_px"]
            bbox_h = detection["bbox_height"]
            conf = detection["confidence"]

            # Estimate distance and bearing
            distance = estimate_distance(bbox_h, self.target_class)
            bearing = estimate_bearing(cx)

            log.info(
                "Target: dist=%.2fm bearing=%.1f° conf=%.2f",
                distance,
                math.degrees(bearing),
                conf,
            )

            # Check arrival
            if distance <= ARRIVAL_DISTANCE:
                log.info("✓ Arrived at target! Distance: %.2fm", distance)
                self._send_stop()
                self._running = False
                break

            # Proportional control
            forward_speed = min(KP_FORWARD * (distance - ARRIVAL_DISTANCE), MAX_FORWARD_SPEED)
            rotation_speed = max(
                -MAX_ROTATION_SPEED, min(KP_ROTATION * bearing, MAX_ROTATION_SPEED)
            )

            # Reduce forward speed during large turns
            turn_factor = 1.0 - min(abs(bearing) / (math.pi / 4), 0.8)
            forward_speed *= turn_factor

            log.info("Move: fwd=%.2f rot=%.2f", forward_speed, rotation_speed)
            self._send_move(forward_speed, 0.0, rotation_speed)

            await asyncio.sleep(period)


async def main():
    parser = argparse.ArgumentParser(description="Navigate Go2 to a target object")
    parser.add_argument("--ip", type=str, help="Robot IP (STA mode)")
    parser.add_argument("--serial", type=str, help="Robot serial number")
    parser.add_argument(
        "--target",
        type=str,
        default="backpack",
        help="Target object class (default: backpack)",
    )
    parser.add_argument(
        "--arrival-distance",
        type=float,
        default=ARRIVAL_DISTANCE,
        help="Stop distance from target in meters (default: 1.0)",
    )
    args = parser.parse_args()

    if args.ip:
        conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=args.ip)
    elif args.serial:
        conn = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA, serialNumber=args.serial
        )
    else:
        conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalAP)

    navigator = Navigator(conn, target_class=args.target)
    await navigator.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
