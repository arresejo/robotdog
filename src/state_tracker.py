"""Robot state tracker — subscribes to localization and sport mode state."""

import asyncio
import logging
import math
from dataclasses import dataclass, field

from unitree_webrtc_connect.constants import RTC_TOPIC

log = logging.getLogger(__name__)


@dataclass
class RobotPose:
    """Robot position and orientation in the map frame."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0  # radians
    pitch: float = 0.0
    roll: float = 0.0
    timestamp: float = 0.0


@dataclass
class RobotState:
    """Full robot state from sport mode."""

    pose: RobotPose = field(default_factory=RobotPose)
    velocity: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    mode: int = 0
    gait_type: int = 0
    body_height: float = 0.0
    yaw_speed: float = 0.0


class RobotStateTracker:
    """Subscribe to robot state topics and maintain current state."""

    def __init__(self):
        self.state = RobotState()
        self._localization_ready = asyncio.Event()
        self._sport_state_ready = asyncio.Event()

    def subscribe(self, conn):
        """Subscribe to state topics on the WebRTC connection."""
        # Sport mode state (position, velocity, IMU)
        conn.datachannel.pub_sub.subscribe(
            RTC_TOPIC["LF_SPORT_MOD_STATE"], self._on_sport_state
        )
        log.info("Subscribed to LF_SPORT_MOD_STATE")

        # LiDAR localization odometry (more precise position on map)
        conn.datachannel.pub_sub.subscribe(
            RTC_TOPIC["LIDAR_LOCALIZATION_ODOM"], self._on_localization
        )
        log.info("Subscribed to LIDAR_LOCALIZATION_ODOM")

    def _on_sport_state(self, message):
        """Handle sport mode state updates."""
        data = message.get("data", message)

        self.state.mode = data.get("mode", 0)
        self.state.gait_type = data.get("gait_type", 0)
        self.state.body_height = data.get("body_height", 0.0)
        self.state.yaw_speed = data.get("yaw_speed", 0.0)

        vel = data.get("velocity", [0, 0, 0])
        if isinstance(vel, list) and len(vel) >= 3:
            self.state.velocity = {"x": vel[0], "y": vel[1], "z": vel[2]}

        pos = data.get("position", [0, 0, 0])
        if isinstance(pos, list) and len(pos) >= 3:
            self.state.pose.x = pos[0]
            self.state.pose.y = pos[1]
            self.state.pose.z = pos[2]

        imu = data.get("imu_state", {})
        rpy = imu.get("rpy", [0, 0, 0])
        if isinstance(rpy, list) and len(rpy) >= 3:
            self.state.pose.roll = rpy[0]
            self.state.pose.pitch = rpy[1]
            self.state.pose.yaw = rpy[2]

        self._sport_state_ready.set()

    def _on_localization(self, message):
        """Handle LiDAR localization updates (overrides sport mode position)."""
        data = message.get("data", message)

        # Localization odometry typically provides pose in map frame
        pose = data.get("pose", {})
        position = pose.get("position", {})
        orientation = pose.get("orientation", {})

        if position:
            self.state.pose.x = position.get("x", self.state.pose.x)
            self.state.pose.y = position.get("y", self.state.pose.y)
            self.state.pose.z = position.get("z", self.state.pose.z)

        if orientation:
            # Convert quaternion to yaw if provided
            qx = orientation.get("x", 0)
            qy = orientation.get("y", 0)
            qz = orientation.get("z", 0)
            qw = orientation.get("w", 1)
            self.state.pose.yaw = math.atan2(
                2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz)
            )

        self._localization_ready.set()

    async def wait_ready(self, timeout: float = 10.0):
        """Wait until at least sport state is available."""
        try:
            await asyncio.wait_for(self._sport_state_ready.wait(), timeout)
            log.info(
                "Robot state ready: pos=(%.2f, %.2f) yaw=%.1f°",
                self.state.pose.x,
                self.state.pose.y,
                math.degrees(self.state.pose.yaw),
            )
        except asyncio.TimeoutError:
            log.warning("Timed out waiting for robot state")
