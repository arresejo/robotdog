import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD, WebRTCConnectionMethod
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection


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


async def publish_request(
    conn: UnitreeWebRTCConnection,
    topic: str,
    payload: dict,
) -> dict:
    return await conn.datachannel.pub_sub.publish_request_new(topic, payload)


async def get_motion_mode(conn: UnitreeWebRTCConnection) -> str | None:
    response = await publish_request(
        conn,
        RTC_TOPIC["MOTION_SWITCHER"],
        {"api_id": 1001},
    )
    status_code = response["data"]["header"]["status"]["code"]
    if status_code != 0:
        return None

    payload = json.loads(response["data"]["data"])
    return payload.get("name")


async def ensure_normal_mode(conn: UnitreeWebRTCConnection) -> None:
    current_mode = await get_motion_mode(conn)
    print(f"Current motion mode: {current_mode}")

    if current_mode != "normal":
        print("Switching robot to normal mode...")
        await publish_request(
            conn,
            RTC_TOPIC["MOTION_SWITCHER"],
            {"api_id": 1002, "parameter": {"name": "normal"}},
        )
        await asyncio.sleep(5)


def save_ppm(rgb_pixels, output_path: Path) -> None:
    height, width, _ = rgb_pixels.shape
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    output_path.write_bytes(header + rgb_pixels.tobytes())


async def main() -> None:
    config = RobotConfig.from_env()
    image_path = Path(os.environ.get("ROBOT_IMAGE_PATH", "robot_camera_capture.ppm"))

    if config.dry_run:
        print(f"Dry run enabled. Would connect, capture a frame to {image_path}, and send Sit.")
        return

    conn = UnitreeWebRTCConnection(
        config.connection_method,
        serialNumber=config.serial_number,
        ip=config.ip,
        username=config.username,
        password=config.password,
    )

    try:
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

        await ensure_normal_mode(conn)

        print("Sending Sit command...")
        await publish_request(
            conn,
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["Sit"]},
        )

        try:
            saved_path = await asyncio.wait_for(frame_saved, timeout=10)
            print(f"Saved camera frame to: {saved_path}")
        except asyncio.TimeoutError:
            print("Timed out waiting for a camera frame.")

        await asyncio.sleep(2)
        print("Sit command sent.")
    finally:
        print("Disconnecting...")
        await conn.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
