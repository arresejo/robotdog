"""Make the Go2 stand up.

Usage:
    uv run python -m src.stand --ip 192.168.8.181
"""

import argparse
import asyncio
import json
import logging
import sys

from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Make Go2 stand up")
    parser.add_argument("--ip", type=str, help="Robot IP (STA mode)")
    parser.add_argument("--serial", type=str, help="Robot serial number")
    args = parser.parse_args()

    if args.ip:
        conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=args.ip)
    elif args.serial:
        conn = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA, serialNumber=args.serial
        )
    else:
        conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalAP)

    log.info("Connecting to Go2...")
    await conn.connect()
    log.info("Connected.")

    # Check current motion mode
    response = await conn.datachannel.pub_sub.publish_request_new(
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

    # Switch to normal mode if needed
    if current_mode != "normal":
        log.info("Switching to normal mode...")
        await conn.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["MOTION_SWITCHER"],
            {"api_id": 1002, "parameter": {"name": "normal"}},
        )
        await asyncio.sleep(3)

    # Stand up
    log.info("Standing up...")
    await conn.datachannel.pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["RecoveryStand"]},
    )

    await asyncio.sleep(2)
    log.info("Done. Robot should be standing.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
