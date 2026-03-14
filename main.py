import asyncio
import io
import json
import logging
import os
import re
import tempfile
import time
import wave
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError
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

DEFAULT_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
MAX_SPEED = 0.6
MAX_DURATION_SECONDS = 3.0
MAX_VIDEO_FPS = 1.0
DEFAULT_VIDEO_FPS = 1.0
DEFAULT_VIDEO_JPEG_QUALITY = 85
TURN_RESPONSE_TIMEOUT_SECONDS = 30.0
COMMAND_TOOL_NAMES = {
    "say_hello": "hello",
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


def _quiet_sdk_print(*args: Any, **kwargs: Any) -> None:
    return None


def configure_unitree_sdk_output(debug: bool) -> None:
    if debug:
        return
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


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_tools() -> list[types.Tool]:
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


def build_live_config() -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        tools=build_tools(),
        system_instruction=(
            "You are controlling a Unitree robot through a narrow tool interface. "
            "You may receive a continuous stream of camera images from the robot. "
            "Use that visual context when it helps you answer or decide what to do next. "
            "Only use the provided tools for direct robot actions. "
            "The robot connection is managed automatically. "
            "Keep motion commands conservative. Prefer short moves and call stop when the user asks to stop. "
            "If the user asks for a capability outside the supported commands, explain the limitation plainly."
        ),
    )


def _pcm_sample_rate_from_mime_type(mime_type: str | None) -> int:
    if not mime_type:
        return 24000
    match = re.search(r"rate=(\d+)", mime_type)
    if match:
        return int(match.group(1))
    return 24000


def _sanitize_live_message_for_logging(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[Any, Any] = {}
        for key, value in payload.items():
            if key == "data" and isinstance(value, str):
                sanitized[key] = "<omitted>"
            else:
                sanitized[key] = _sanitize_live_message_for_logging(value)
        return sanitized
    if isinstance(payload, list):
        return [_sanitize_live_message_for_logging(item) for item in payload]
    return payload


async def play_audio_chunk(audio_bytes: bytes, mime_type: str | None) -> None:
    if not audio_bytes:
        return

    sample_rate = _pcm_sample_rate_from_mime_type(mime_type)

    def write_wav_file() -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        with wave.open(tmp_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_bytes)

        return tmp_path

    wav_path = await asyncio.to_thread(write_wav_file)
    try:
        process = await asyncio.create_subprocess_exec(
            "afplay",
            wav_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
    finally:
        Path(wav_path).unlink(missing_ok=True)


async def execute_tool_call(
    controller: RobotController,
    function_call: types.FunctionCall,
) -> types.FunctionResponse:
    args = function_call.args or {}
    name = function_call.name or ""
    _debug_log(
        controller._config.debug,
        f"Tool call: {name} args={json.dumps(args, ensure_ascii=True)}",
    )

    try:
        if name == "get_robot_status":
            result = await controller.status()
        elif name in COMMAND_TOOL_NAMES:
            result = await controller.execute_command(
                command=COMMAND_TOOL_NAMES[name],
                duration_seconds=float(args.get("duration_seconds", 1.5)),
                speed=float(args.get("speed", 0.3)),
            )
        else:
            result = {"ok": False, "error": f"Unknown tool call: {name}"}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}

    return types.FunctionResponse(
        id=function_call.id,
        name=name,
        response=result,
    )


async def handle_model_turn(
    session: Any,
    controller: RobotController,
) -> tuple[str, bool]:
    chunks: list[str] = []
    streamed_output = False

    async for message in session.receive():
        message_payload = _sanitize_live_message_for_logging(
            message.model_dump(mode="json", exclude_none=True)
        )
        _debug_log(
            controller._config.debug,
            "Model message JSON: "
            + json.dumps(message_payload, ensure_ascii=True),
        )
        if message.server_content and message.server_content.model_turn:
            for part in message.server_content.model_turn.parts or []:
                if part.inline_data and part.inline_data.data:
                    if controller._config.play_audio:
                        await play_audio_chunk(
                            audio_bytes=part.inline_data.data,
                            mime_type=part.inline_data.mime_type,
                        )
        if message.text:
            chunks.append(message.text)
        if (
            message.server_content
            and message.server_content.output_transcription
            and message.server_content.output_transcription.text
        ):
            transcript_chunk = message.server_content.output_transcription.text
            chunks.append(transcript_chunk)
            if not streamed_output:
                print("Gemini: ", end="", flush=True)
                streamed_output = True
            print(transcript_chunk, end="", flush=True)

        if message.tool_call and message.tool_call.function_calls:
            responses = [
                await execute_tool_call(controller, function_call)
                for function_call in message.tool_call.function_calls
            ]
            await session.send_tool_response(function_responses=responses)

        if (
            message.server_content
            and (
                message.server_content.turn_complete is True
                or message.server_content.generation_complete is True
            )
        ):
            break

    if streamed_output:
        print()
    return "".join(chunks).strip(), streamed_output


async def stream_video_realtime_to_gemini(session: Any, controller: RobotController) -> None:
    if (
        not controller.connected
        or controller._config.dry_run
        or not controller._config.video_enabled
    ):
        return

    frame_interval_seconds = 1.0 / controller._config.video_fps
    last_forwarded_sequence = 0
    debug_dir = controller._config.video_debug_dir
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)

    while True:
        got_frame = await controller.wait_for_video_frame(timeout=2.0)
        if not got_frame:
            _debug_log(
                controller._config.debug,
                "Robot video stream did not produce a frame for realtime forwarding.",
            )
            await asyncio.sleep(frame_interval_seconds)
            continue

        metadata = controller.latest_video_frame_metadata()
        sequence = int(metadata["sequence"])
        if sequence <= last_forwarded_sequence:
            await asyncio.sleep(frame_interval_seconds)
            continue

        jpeg_bytes = await controller.get_latest_video_frame_jpeg()
        if not jpeg_bytes:
            await asyncio.sleep(frame_interval_seconds)
            continue

        await session.send_realtime_input(
            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
        )
        last_forwarded_sequence = sequence
        if controller._config.debug:
            print(
                "Forwarded realtime robot frame:",
                json.dumps(
                    {
                        "sequence": sequence,
                        "shape": metadata["shape"],
                        "age_ms": round(
                            max(0.0, time.time() - float(metadata["received_at"])) * 1000,
                            1,
                        ),
                        "jpeg_bytes": len(jpeg_bytes),
                    },
                    ensure_ascii=True,
                ),
            )
        if debug_dir is not None:
            debug_path = debug_dir / f"frame_{sequence:06d}.jpg"
            await asyncio.to_thread(_write_bytes, debug_path, jpeg_bytes)

        await asyncio.sleep(frame_interval_seconds)


async def build_user_turn_parts(
    controller: RobotController,
    user_input: str,
) -> list[types.Part]:
    parts: list[types.Part] = []

    if controller.connected and controller._config.video_enabled:
        got_frame = await controller.wait_for_video_frame(timeout=2.0)
        if not got_frame:
            _debug_log(
                controller._config.debug,
                "Robot video stream did not produce a frame before prompt.",
            )
        else:
            jpeg_bytes = await controller.get_latest_video_frame_jpeg()
            if jpeg_bytes:
                metadata = controller.latest_video_frame_metadata()
                parts.append(types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"))
                if controller._config.debug:
                    print(
                        "Included latest robot frame with user turn:",
                        json.dumps(
                            {
                                "sequence": metadata["sequence"],
                                "shape": metadata["shape"],
                                "age_ms": round(
                                    max(0.0, time.time() - float(metadata["received_at"]))
                                    * 1000,
                                    1,
                                ),
                                "jpeg_bytes": len(jpeg_bytes),
                            },
                            ensure_ascii=True,
                        ),
                    )

    parts.append(types.Part(text=user_input))
    return parts


async def repl() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY before running this script.")

    model = os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_MODEL)
    robot_config = RobotConfig.from_env()
    configure_unitree_sdk_output(robot_config.debug)
    if not robot_config.debug:
        logging.getLogger("aiortc").setLevel(logging.ERROR)
        logging.getLogger().setLevel(logging.CRITICAL)
    controller = RobotController(robot_config)
    client = genai.Client(api_key=api_key)

    connection_result = await controller.ensure_connected()
    print(connection_result["message"])

    async with client.aio.live.connect(
        model=model, config=build_live_config()
    ) as session:
        print("Gemini session started.")
        print("Type a request and press Enter.")
        print("Type 'exit' to quit.")
        video_stream_task: asyncio.Task[None] | None = None
        if controller.connected and controller._config.video_enabled:
            video_stream_task = asyncio.create_task(
                stream_video_realtime_to_gemini(session, controller)
            )

        try:
            while True:
                if video_stream_task and video_stream_task.done():
                    task_error = video_stream_task.exception()
                    if task_error is not None:
                        print(f"Realtime video forwarding stopped: {task_error}")
                    break

                user_input = await asyncio.to_thread(input, "\nYou: ")
                if user_input.strip().lower() in {"exit", "quit"}:
                    break
                if not user_input.strip():
                    continue

                turn_parts = await build_user_turn_parts(controller, user_input)
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=turn_parts,
                    ),
                    turn_complete=True,
                )
                try:
                    response_text, streamed_output = await asyncio.wait_for(
                        handle_model_turn(session, controller),
                        timeout=TURN_RESPONSE_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    print("Gemini timed out waiting for a turn response.")
                    break
                except APIError as exc:
                    print(f"Gemini session error: {exc}")
                    break
                if response_text and not streamed_output:
                    print(f"Gemini: {response_text}")
        finally:
            if video_stream_task is not None:
                video_stream_task.cancel()
                with suppress(asyncio.CancelledError):
                    await video_stream_task

    if controller.connected:
        with suppress(Exception):
            await controller.disconnect()


def main() -> None:
    asyncio.run(repl())


if __name__ == "__main__":
    main()
