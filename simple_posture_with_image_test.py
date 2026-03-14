import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal Unitree posture test with one camera frame capture."
    )
    parser.add_argument(
        "--sit-up",
        action="store_true",
        help="Send RiseSit instead of Sit.",
    )
    return parser.parse_args()


def save_ppm(rgb_pixels, output_path: Path) -> None:
    height, width, _ = rgb_pixels.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    output_path.write_bytes(header + rgb_pixels.tobytes())


async def main() -> None:
    args = parse_args()
    robot_ip = os.environ.get("ROBOT_IP")
    if not robot_ip:
        raise ValueError("Set ROBOT_IP before running this script.")

    image_path = Path(os.environ.get("ROBOT_IMAGE_PATH", "robot_camera_capture.ppm"))
    action_name = "sit up" if args.sit_up else "sit down"
    action_api_id = SPORT_CMD["RiseSit"] if args.sit_up else SPORT_CMD["Sit"]

    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=robot_ip)
    frame_saved = asyncio.get_running_loop().create_future()

    async def capture_one_frame(track) -> None:
        if frame_saved.done():
            return

        frame = await track.recv()
        rgb_pixels = frame.to_ndarray(format="rgb24")
        save_ppm(rgb_pixels, image_path)
        frame_saved.set_result(str(image_path))

    print("Connecting to robot...")
    await conn.connect()

    conn.video.add_track_callback(capture_one_frame)
    conn.video.switchVideoChannel(True)

    print("Checking current motion mode...")
    response = await conn.datachannel.pub_sub.publish_request_new(
        RTC_TOPIC["MOTION_SWITCHER"],
        {"api_id": 1001},
    )

    current_mode = None
    if response["data"]["header"]["status"]["code"] == 0:
        payload = json.loads(response["data"]["data"])
        current_mode = payload.get("name")
        print(f"Current motion mode: {current_mode}")

    if current_mode != "normal":
        print("Switching motion mode to normal...")
        await conn.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["MOTION_SWITCHER"],
            {
                "api_id": 1002,
                "parameter": {"name": "normal"},
            },
        )
        await asyncio.sleep(5)

    print(f"Sending {action_name} command...")
    await conn.datachannel.pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": action_api_id},
    )

    try:
        saved_path = await asyncio.wait_for(frame_saved, timeout=10)
        print(f"Saved camera frame to: {saved_path}")
    except asyncio.TimeoutError:
        print("Timed out waiting for a camera frame.")

    await asyncio.sleep(2)
    print(f"{action_name.capitalize()} command sent.")

    print("Disconnecting...")
    await conn.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        sys.exit(0)
