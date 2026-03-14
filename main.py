import asyncio
import json
import logging
import os
import re
import tempfile
import time
import wave
from contextlib import suppress
from pathlib import Path
from typing import Any

# Load .env file if present
_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from google import genai
from google.genai import types
from google.genai.errors import APIError

from robot_bridge import (
    RobotConfig,
    RobotController,
    configure_unitree_sdk_output,
    build_robot_tools,
    COMMAND_TOOL_NAMES,
)

DEFAULT_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
TURN_RESPONSE_TIMEOUT_SECONDS = 30.0


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_tools() -> list[types.Tool]:
    return build_robot_tools()


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


async def play_audio_chunk(
    audio_bytes: bytes,
    mime_type: str | None,
    controller: RobotController | None = None,
) -> None:
    if not audio_bytes:
        return

    sample_rate = _pcm_sample_rate_from_mime_type(mime_type)

    # Route to robot speaker when connected and play_audio enabled
    if controller and controller.connected and controller._config.play_audio:
        await controller.play_audio_on_robot(audio_bytes, sample_rate)
        return

    # Fallback: play locally via afplay
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
                            controller=controller,
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
