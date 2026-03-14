import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gemini_live import GeminiLive

# Add parent directory to path to import robot_bridge
sys.path.insert(0, str(Path(__file__).parent.parent))
from robot_bridge import (
    RobotConfig,
    RobotController,
    configure_unitree_sdk_output,
    build_robot_tools,
    build_robot_tool_mapping,
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
ROBOT_ENABLED = os.getenv("ROBOT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

# Initialize FastAPI
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Gemini Live with robot control."""
    await websocket.accept()

    logger.info("WebSocket connection accepted")

    robot_controller = None
    robot_tools = []
    robot_tool_mapping = {}

    if ROBOT_ENABLED:
        try:
            robot_config = RobotConfig.from_env()
            configure_unitree_sdk_output(robot_config.debug)
            if not robot_config.debug:
                logging.getLogger("aiortc").setLevel(logging.ERROR)
            
            robot_controller = RobotController(robot_config)
            connection_result = await robot_controller.ensure_connected()
            logger.info(f"Robot: {connection_result['message']}")
            
            robot_tools = build_robot_tools()
            robot_tool_mapping = build_robot_tool_mapping(robot_controller)
        except Exception as e:
            logger.error(f"Failed to initialize robot controller: {e}")
            robot_controller = None

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()

    async def stream_robot_video_to_gemini():
        """Stream robot camera feed to Gemini Live API and frontend."""
        if not robot_controller or not robot_controller.connected:
            return
        if robot_controller._config.dry_run or not robot_controller._config.video_enabled:
            return
        
        frame_interval_seconds = 1.0 / robot_controller._config.video_fps
        last_forwarded_sequence = 0
        
        logger.info("Starting robot video stream to Gemini and frontend")
        
        try:
            while True:
                got_frame = await robot_controller.wait_for_video_frame(timeout=2.0)
                if not got_frame:
                    await asyncio.sleep(frame_interval_seconds)
                    continue
                
                metadata = robot_controller.latest_video_frame_metadata()
                sequence = int(metadata["sequence"])
                if sequence <= last_forwarded_sequence:
                    await asyncio.sleep(frame_interval_seconds)
                    continue
                
                jpeg_bytes = await robot_controller.get_latest_video_frame_jpeg()
                if not jpeg_bytes:
                    await asyncio.sleep(frame_interval_seconds)
                    continue
                
                # Send to Gemini
                await video_input_queue.put(jpeg_bytes)
                
                # Also send to frontend for display
                try:
                    await websocket.send_json({
                        "type": "robot_video_frame",
                        "data": base64.b64encode(jpeg_bytes).decode('utf-8'),
                        "sequence": sequence
                    })
                except Exception as e:
                    logger.debug(f"Could not send video frame to frontend: {e}")
                
                last_forwarded_sequence = sequence
                
                if robot_controller._config.debug:
                    logger.info(f"Forwarded robot frame {sequence}: {len(jpeg_bytes)} bytes")
                
                await asyncio.sleep(frame_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Robot video stream task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in robot video stream: {e}")

    async def audio_output_callback(data):
        await websocket.send_bytes(data)

    async def audio_interrupt_callback():
        pass

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY,
        model=MODEL,
        input_sample_rate=16000,
        tools=robot_tools,
        tool_mapping=robot_tool_mapping,
    )

    async def receive_from_client():
        try:
            while True:
                message = await websocket.receive()

                if message.get("bytes"):
                    await audio_input_queue.put(message["bytes"])
                elif message.get("text"):
                    text = message["text"]
                    try:
                        payload = json.loads(text)
                        if isinstance(payload, dict) and payload.get("type") == "image":
                            logger.info(f"Received image chunk from client: {len(payload['data'])} base64 chars")
                            image_data = base64.b64decode(payload["data"])
                            await video_input_queue.put(image_data)
                            continue
                    except json.JSONDecodeError:
                        pass

                    await text_input_queue.put(text)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error receiving from client: {e}")

    receive_task = asyncio.create_task(receive_from_client())
    robot_video_task = None
    
    if robot_controller and robot_controller._config.video_enabled:
        robot_video_task = asyncio.create_task(stream_robot_video_to_gemini())

    async def run_session():
        async for event in gemini_client.start_session(
            audio_input_queue=audio_input_queue,
            video_input_queue=video_input_queue,
            text_input_queue=text_input_queue,
            audio_output_callback=audio_output_callback,
            audio_interrupt_callback=audio_interrupt_callback,
        ):
            if event:
                await websocket.send_json(event)

    try:
        await run_session()
    except Exception as e:
        logger.error(f"Error in Gemini session: {e}")
    finally:
        receive_task.cancel()
        
        if robot_video_task is not None:
            robot_video_task.cancel()
            try:
                await robot_video_task
            except asyncio.CancelledError:
                pass
        
        if robot_controller and robot_controller.connected:
            try:
                await robot_controller.disconnect()
                logger.info("Robot disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting robot: {e}")
        
        try:
            await websocket.close()
        except:
            pass


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="localhost", port=port)
