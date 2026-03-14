import asyncio
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.genai import types
from PIL import Image
from unitree_webrtc_connect.constants import (
    RTC_TOPIC,
    SPORT_CMD,
    WebRTCConnectionMethod,
)
import unitree_webrtc_connect.util as unitree_util
import unitree_webrtc_connect.webrtc_datachannel as unitree_webrtc_datachannel
import unitree_webrtc_connect.webrtc_driver as unitree_webrtc_driver
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection

MAX_SPEED = 0.6
MAX_DURATION_SECONDS = 3.0
MAX_VIDEO_FPS = 1.0
DEFAULT_VIDEO_FPS = 1.0
DEFAULT_VIDEO_JPEG_QUALITY = 85
COMMAND_TOOL_NAMES = {
    "say_hello": "hello",
    "make_finger_heart": "finger_heart",
    "stand_up": "stand",
    "sit_down": "sit",
    "move_forward": "move_forward",
    "move_backward": "move_backward",
    "turn_left": "turn_left",
    "turn_right": "turn_right",
    "stop_robot": "stop",
}


@dataclass(slots=True)
class RobotConfig:
    connection_method: WebRTCConnectionMethod
    ip: str | None
    serial_number: str | None
    username: str | None
    password: str | None
    dry_run: bool
    video_enabled: bool
    video_fps: float
    video_jpeg_quality: int
    video_debug_dir: Path | None
    play_audio: bool
    debug: bool

    @classmethod
    def from_env(cls) -> "RobotConfig":
        method_name = (
            os.environ.get("ROBOT_CONNECTION_METHOD", "local_sta").strip().lower()
        )
        method_map = {
            "local_ap": WebRTCConnectionMethod.LocalAP,
            "local_sta": WebRTCConnectionMethod.LocalSTA,
            "remote": WebRTCConnectionMethod.Remote,
        }
        if method_name not in method_map:
            raise ValueError(
                "ROBOT_CONNECTION_METHOD must be one of: local_ap, local_sta, remote."
            )

        return cls(
            connection_method=method_map[method_name],
            ip=os.environ.get("ROBOT_IP"),
            serial_number=os.environ.get("ROBOT_SERIAL_NUMBER"),
            username=os.environ.get("ROBOT_USERNAME"),
            password=os.environ.get("ROBOT_PASSWORD"),
            dry_run=_is_truthy(os.environ.get("ROBOT_DRY_RUN")),
            video_enabled=not _is_truthy(os.environ.get("ROBOT_VIDEO_DISABLED")),
            video_fps=_clamp_float(
                os.environ.get("ROBOT_VIDEO_FPS"),
                default=DEFAULT_VIDEO_FPS,
                minimum=0.1,
                maximum=MAX_VIDEO_FPS,
            ),
            video_jpeg_quality=_clamp_int(
                os.environ.get("ROBOT_VIDEO_JPEG_QUALITY"),
                default=DEFAULT_VIDEO_JPEG_QUALITY,
                minimum=1,
                maximum=95,
            ),
            video_debug_dir=_optional_path(os.environ.get("ROBOT_VIDEO_DEBUG_DIR")),
            play_audio=_is_truthy(os.environ.get("ROBOT_PLAY_AUDIO")),
            debug=_is_truthy(os.environ.get("ROBOT_DEBUG")),
        )


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _clamp_float(
    value: str | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    if value is None:
        return default
    return max(minimum, min(float(value), maximum))


def _clamp_int(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    return max(minimum, min(int(value), maximum))


def _optional_path(value: str | None) -> Path | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return Path(stripped)


def _debug_log(enabled: bool, message: str) -> None:
    if enabled:
        print(message)


def configure_unitree_sdk_output(debug: bool) -> None:
    if debug:
        return
    
    def _quiet_sdk_print(*args: Any, **kwargs: Any) -> None:
        return None
    
    unitree_util.print_status = _quiet_sdk_print
    unitree_webrtc_driver.print_status = _quiet_sdk_print
    unitree_webrtc_datachannel.print_status = _quiet_sdk_print
    unitree_webrtc_datachannel.print = _quiet_sdk_print


class RobotController:
    def __init__(self, config: RobotConfig) -> None:
        self._config = config
        self._conn: UnitreeWebRTCConnection | None = None
        self._latest_video_frame: Any | None = None
        self._video_frame_event = asyncio.Event()
        self._video_frame_sequence = 0
        self._latest_video_frame_shape: tuple[int, ...] | None = None
        self._latest_video_frame_received_at = 0.0

    @property
    def connected(self) -> bool:
        return self._config.dry_run or bool(self._conn and self._conn.isConnected)

    async def ensure_connected(self) -> dict[str, Any]:
        if self.connected:
            return {"ok": True, "message": "Robot is already connected."}
        return await self.connect()

    async def connect(self) -> dict[str, Any]:
        if self._config.dry_run:
            return {
                "ok": True,
                "message": "Dry run enabled. Pretending the robot is connected.",
            }

        if self.connected:
            return {"ok": True, "message": "Robot is already connected."}

        conn = UnitreeWebRTCConnection(
            self._config.connection_method,
            serialNumber=self._config.serial_number,
            ip=self._config.ip,
            username=self._config.username,
            password=self._config.password,
        )
        await conn.connect()
        if self._config.video_enabled:
            conn.video.add_track_callback(self._capture_video_track)
            conn.video.switchVideoChannel(True)
        self._conn = conn
        return {"ok": True, "message": "Robot connected successfully."}

    async def disconnect(self) -> dict[str, Any]:
        if self._config.dry_run:
            return {
                "ok": True,
                "message": "Dry run enabled. Pretending the robot is disconnected.",
            }

        if not self._conn:
            return {"ok": True, "message": "Robot is already disconnected."}

        await self._conn.disconnect()
        self._conn = None
        self._latest_video_frame = None
        self._video_frame_event.clear()
        self._video_frame_sequence = 0
        self._latest_video_frame_shape = None
        self._latest_video_frame_received_at = 0.0
        return {"ok": True, "message": "Robot disconnected successfully."}

    async def status(self) -> dict[str, Any]:
        await self.ensure_connected()
        mode: str | None = None
        if self.connected and not self._config.dry_run:
            mode = await self._get_motion_mode()

        return {
            "ok": True,
            "connected": self.connected,
            "dry_run": self._config.dry_run,
            "connection_method": self._config.connection_method.name,
            "motion_mode": mode,
            "video_enabled": self._config.video_enabled and not self._config.dry_run,
            "video_frame_sequence": self._video_frame_sequence,
            "video_frame_shape": self._latest_video_frame_shape,
        }

    async def execute_command(
        self,
        command: str,
        duration_seconds: float = 1.5,
        speed: float = 0.3,
    ) -> dict[str, Any]:
        command = command.strip().lower()
        duration_seconds = max(0.1, min(duration_seconds, MAX_DURATION_SECONDS))
        speed = max(0.1, min(speed, MAX_SPEED))

        if self._config.dry_run:
            return {
                "ok": True,
                "message": f"Dry run executed {command}.",
                "command": command,
                "duration_seconds": duration_seconds,
                "speed": speed,
            }

        await self.ensure_connected()

        await self._ensure_normal_mode()

        if command == "hello":
            await self._publish_sport({"api_id": SPORT_CMD["Hello"]})
            return {"ok": True, "message": "Robot said hello."}
        if command == "finger_heart":
            await self._publish_sport({"api_id": SPORT_CMD["FingerHeart"]})
            return {"ok": True, "message": "Robot made a finger heart gesture."}
        if command == "stand":
            await self._publish_sport({"api_id": SPORT_CMD["StandUp"]})
            return {"ok": True, "message": "Robot stood up."}
        if command == "sit":
            await self._publish_sport({"api_id": SPORT_CMD["Sit"]})
            return {"ok": True, "message": "Robot sat down."}
        if command == "stop":
            await self._stop_motion()
            return {"ok": True, "message": "Robot stop command sent."}
        if command == "move_forward":
            await self._move_for_duration(
                x=speed, y=0.0, z=0.0, duration_seconds=duration_seconds
            )
            return {"ok": True, "message": "Robot moved forward."}
        if command == "move_backward":
            await self._move_for_duration(
                x=-speed, y=0.0, z=0.0, duration_seconds=duration_seconds
            )
            return {"ok": True, "message": "Robot moved backward."}
        if command == "turn_left":
            await self._move_for_duration(
                x=0.0, y=0.0, z=speed, duration_seconds=duration_seconds
            )
            return {"ok": True, "message": "Robot turned left."}
        if command == "turn_right":
            await self._move_for_duration(
                x=0.0, y=0.0, z=-speed, duration_seconds=duration_seconds
            )
            return {"ok": True, "message": "Robot turned right."}

        raise ValueError(f"Unsupported command: {command}")

    async def _ensure_normal_mode(self) -> None:
        current_mode = await self._get_motion_mode()
        if current_mode != "normal":
            await self._publish_request(
                RTC_TOPIC["MOTION_SWITCHER"],
                {"api_id": 1002, "parameter": {"name": "normal"}},
            )
            await asyncio.sleep(5)

    async def _get_motion_mode(self) -> str | None:
        response = await self._publish_request(
            RTC_TOPIC["MOTION_SWITCHER"],
            {"api_id": 1001},
        )
        status_code = response["data"]["header"]["status"]["code"]
        if status_code != 0:
            return None
        payload = json.loads(response["data"]["data"])
        return payload.get("name")

    async def _move_for_duration(
        self,
        *,
        x: float,
        y: float,
        z: float,
        duration_seconds: float,
    ) -> None:
        await self._publish_sport(
            {
                "api_id": SPORT_CMD["Move"],
                "parameter": {"x": x, "y": y, "z": z},
            }
        )
        await asyncio.sleep(duration_seconds)
        await self._stop_motion()

    async def _stop_motion(self) -> None:
        await self._publish_sport({"api_id": SPORT_CMD["StopMove"]})

    async def _publish_sport(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._publish_request(RTC_TOPIC["SPORT_MOD"], payload)

    async def _publish_request(
        self, topic: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._conn:
            raise RuntimeError("Robot connection is not initialized.")
        return await self._conn.datachannel.pub_sub.publish_request_new(topic, payload)

    async def _capture_video_track(self, track: Any) -> None:
        while True:
            try:
                frame = await track.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _debug_log(self._config.debug, f"Robot video track ended: {exc}")
                return

            self._latest_video_frame = frame.to_ndarray(format="rgb24")
            self._video_frame_sequence += 1
            self._latest_video_frame_shape = tuple(self._latest_video_frame.shape)
            self._latest_video_frame_received_at = time.time()
            self._video_frame_event.set()

    async def wait_for_video_frame(self, timeout: float = 10.0) -> bool:
        if self._config.dry_run or not self._config.video_enabled:
            return False
        if self._latest_video_frame is not None:
            return True
        try:
            await asyncio.wait_for(self._video_frame_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return self._latest_video_frame is not None

    async def get_latest_video_frame_jpeg(self) -> bytes | None:
        if self._config.dry_run or not self._config.video_enabled:
            return None

        frame = self._latest_video_frame
        if frame is None:
            return None

        def encode() -> bytes:
            image = Image.fromarray(frame, mode="RGB")
            with io.BytesIO() as buffer:
                image.save(
                    buffer,
                    format="JPEG",
                    quality=self._config.video_jpeg_quality,
                    optimize=True,
                )
                return buffer.getvalue()

        return await asyncio.to_thread(encode)

    def latest_video_frame_metadata(self) -> dict[str, Any]:
        return {
            "sequence": self._video_frame_sequence,
            "shape": self._latest_video_frame_shape,
            "received_at": self._latest_video_frame_received_at,
        }


def build_robot_tools() -> list[types.Tool]:
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="get_robot_status",
                    description="Get the current robot connection and motion mode status.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.FunctionDeclaration(
                    name="say_hello",
                    description="Make the robot perform its hello gesture.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.FunctionDeclaration(
                    name="make_finger_heart",
                    description="Make the robot perform its finger heart gesture.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.FunctionDeclaration(
                    name="stand_up",
                    description="Make the robot stand up.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.FunctionDeclaration(
                    name="sit_down",
                    description="Make the robot sit down.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.FunctionDeclaration(
                    name="move_forward",
                    description="Move the robot forward for a short duration.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "duration_seconds": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_DURATION_SECONDS,
                            },
                            "speed": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_SPEED,
                            },
                        },
                    },
                ),
                types.FunctionDeclaration(
                    name="move_backward",
                    description="Move the robot backward for a short duration.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "duration_seconds": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_DURATION_SECONDS,
                            },
                            "speed": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_SPEED,
                            },
                        },
                    },
                ),
                types.FunctionDeclaration(
                    name="turn_left",
                    description="Turn the robot left for a short duration.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "duration_seconds": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_DURATION_SECONDS,
                            },
                            "speed": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_SPEED,
                            },
                        },
                    },
                ),
                types.FunctionDeclaration(
                    name="turn_right",
                    description="Turn the robot right for a short duration.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "duration_seconds": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_DURATION_SECONDS,
                            },
                            "speed": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": MAX_SPEED,
                            },
                        },
                    },
                ),
                types.FunctionDeclaration(
                    name="stop_robot",
                    description="Stop the robot's current motion.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
            ]
        )
    ]


def build_robot_tool_mapping(controller: RobotController) -> dict[str, Any]:
    async def get_robot_status() -> dict[str, Any]:
        return await controller.status()

    async def say_hello() -> dict[str, Any]:
        return await controller.execute_command("hello")

    async def make_finger_heart() -> dict[str, Any]:
        return await controller.execute_command("finger_heart")

    async def stand_up() -> dict[str, Any]:
        return await controller.execute_command("stand")

    async def sit_down() -> dict[str, Any]:
        return await controller.execute_command("sit")

    async def move_forward(
        duration_seconds: float = 1.5, speed: float = 0.3
    ) -> dict[str, Any]:
        return await controller.execute_command(
            "move_forward", duration_seconds=duration_seconds, speed=speed
        )

    async def move_backward(
        duration_seconds: float = 1.5, speed: float = 0.3
    ) -> dict[str, Any]:
        return await controller.execute_command(
            "move_backward", duration_seconds=duration_seconds, speed=speed
        )

    async def turn_left(
        duration_seconds: float = 1.5, speed: float = 0.3
    ) -> dict[str, Any]:
        return await controller.execute_command(
            "turn_left", duration_seconds=duration_seconds, speed=speed
        )

    async def turn_right(
        duration_seconds: float = 1.5, speed: float = 0.3
    ) -> dict[str, Any]:
        return await controller.execute_command(
            "turn_right", duration_seconds=duration_seconds, speed=speed
        )

    async def stop_robot() -> dict[str, Any]:
        return await controller.execute_command("stop")

    return {
        "get_robot_status": get_robot_status,
        "say_hello": say_hello,
        "make_finger_heart": make_finger_heart,
        "stand_up": stand_up,
        "sit_down": sit_down,
        "move_forward": move_forward,
        "move_backward": move_backward,
        "turn_left": turn_left,
        "turn_right": turn_right,
        "stop_robot": stop_robot,
    }
