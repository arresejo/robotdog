import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD, WebRTCConnectionMethod
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection


DEFAULT_MODEL = "gemini-live-2.5-flash-preview"
MAX_SPEED = 0.6
MAX_DURATION_SECONDS = 3.0


@dataclass(slots=True)
class RobotConfig:
    connection_method: WebRTCConnectionMethod
    ip: str | None
    serial_number: str | None
    username: str | None
    password: str | None
    dry_run: bool

    @classmethod
    def from_env(cls) -> "RobotConfig":
        method_name = os.environ.get("ROBOT_CONNECTION_METHOD", "local_sta").strip().lower()
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
        )


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


class RobotController:
    def __init__(self, config: RobotConfig) -> None:
        self._config = config
        self._conn: UnitreeWebRTCConnection | None = None

    @property
    def connected(self) -> bool:
        return self._config.dry_run or bool(self._conn and self._conn.isConnected)

    async def connect(self) -> dict[str, Any]:
        if self._config.dry_run:
            return {"ok": True, "message": "Dry run enabled. Pretending the robot is connected."}

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
        self._conn = conn
        return {"ok": True, "message": "Robot connected successfully."}

    async def disconnect(self) -> dict[str, Any]:
        if self._config.dry_run:
            return {"ok": True, "message": "Dry run enabled. Pretending the robot is disconnected."}

        if not self._conn:
            return {"ok": True, "message": "Robot is already disconnected."}

        await self._conn.disconnect()
        self._conn = None
        return {"ok": True, "message": "Robot disconnected successfully."}

    async def status(self) -> dict[str, Any]:
        mode: str | None = None
        if self.connected and not self._config.dry_run:
            mode = await self._get_motion_mode()

        return {
            "ok": True,
            "connected": self.connected,
            "dry_run": self._config.dry_run,
            "connection_method": self._config.connection_method.name,
            "motion_mode": mode,
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

        if not self.connected:
            raise RuntimeError("Robot is not connected. Call connect_robot first.")

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
            await self._move_for_duration(x=speed, y=0.0, z=0.0, duration_seconds=duration_seconds)
            return {"ok": True, "message": "Robot moved forward."}
        if command == "move_backward":
            await self._move_for_duration(x=-speed, y=0.0, z=0.0, duration_seconds=duration_seconds)
            return {"ok": True, "message": "Robot moved backward."}
        if command == "turn_left":
            await self._move_for_duration(x=0.0, y=0.0, z=speed, duration_seconds=duration_seconds)
            return {"ok": True, "message": "Robot turned left."}
        if command == "turn_right":
            await self._move_for_duration(x=0.0, y=0.0, z=-speed, duration_seconds=duration_seconds)
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

    async def _publish_request(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._conn:
            raise RuntimeError("Robot connection is not initialized.")
        return await self._conn.datachannel.pub_sub.publish_request_new(topic, payload)


def build_tools() -> list[types.Tool]:
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="connect_robot",
                    description="Connect to the Unitree robot before issuing motion commands.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.FunctionDeclaration(
                    name="get_robot_status",
                    description="Get the current robot connection and motion mode status.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.FunctionDeclaration(
                    name="robot_command",
                    description="Run one simple motion command on the robot.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "enum": [
                                    "hello",
                                    "stand",
                                    "sit",
                                    "move_forward",
                                    "move_backward",
                                    "turn_left",
                                    "turn_right",
                                    "stop",
                                ],
                            },
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
                        "required": ["command"],
                    },
                ),
                types.FunctionDeclaration(
                    name="disconnect_robot",
                    description="Disconnect from the Unitree robot when the session is finished.",
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
        response_modalities=["TEXT"],
        tools=build_tools(),
        system_instruction=(
            "You are controlling a Unitree robot through a narrow tool interface. "
            "Only use the provided tools for direct robot actions. "
            "Before the first movement command, connect the robot if needed. "
            "Keep motion commands conservative. Prefer short moves and call stop when the user asks to stop. "
            "If the user asks for a capability outside the supported commands, explain the limitation plainly."
        ),
    )


async def execute_tool_call(
    controller: RobotController,
    function_call: types.FunctionCall,
) -> types.FunctionResponse:
    args = function_call.args or {}
    name = function_call.name or ""

    try:
        if name == "connect_robot":
            result = await controller.connect()
        elif name == "get_robot_status":
            result = await controller.status()
        elif name == "robot_command":
            result = await controller.execute_command(
                command=str(args.get("command", "")),
                duration_seconds=float(args.get("duration_seconds", 1.5)),
                speed=float(args.get("speed", 0.3)),
            )
        elif name == "disconnect_robot":
            result = await controller.disconnect()
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
) -> str:
    chunks: list[str] = []

    async for message in session.receive():
        if message.text:
            chunks.append(message.text)

        if message.tool_call and message.tool_call.function_calls:
            responses = [
                await execute_tool_call(controller, function_call)
                for function_call in message.tool_call.function_calls
            ]
            await session.send_tool_response(function_responses=responses)

    return "".join(chunks).strip()


async def repl() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY before running this script.")

    model = os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_MODEL)
    robot_config = RobotConfig.from_env()
    controller = RobotController(robot_config)
    client = genai.Client(api_key=api_key)

    async with client.aio.live.connect(model=model, config=build_live_config()) as session:
        print(f"Gemini Live session started with model: {model}")
        print(
            "Type a plain request such as 'connect to the robot and say hello' "
            "or 'move forward for a second', then press Enter."
        )
        print("Type 'exit' to quit.")

        while True:
            user_input = await asyncio.to_thread(input, "\nYou: ")
            if user_input.strip().lower() in {"exit", "quit"}:
                break
            if not user_input.strip():
                continue

            await session.send_realtime_input(text=user_input)
            response_text = await handle_model_turn(session, controller)
            if response_text:
                print(f"Gemini: {response_text}")

    if controller.connected:
        await controller.disconnect()


def main() -> None:
    asyncio.run(repl())


if __name__ == "__main__":
    main()
