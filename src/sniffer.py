"""Protocol sniffer — capture SLAM/navigation messages from the Go2.

Run this while using the Unitree app to perform navigation actions.
It logs all messages from SLAM and navigation topics so you can
reverse-engineer the exact payloads for SLAM_QT_COMMAND.

Usage:
    uv run python -m src.sniffer --ip 192.168.8.181
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from unitree_webrtc_connect.constants import RTC_TOPIC
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# Topics we want to sniff — all SLAM and navigation related
SNIFF_TOPICS = [
    "SLAM_QT_COMMAND",
    "SLAM_QT_NOTICE",
    "SLAM_ADD_NODE",
    "SLAM_ADD_EDGE",
    "LIDAR_MAPPING_CMD",
    "LIDAR_MAPPING_ODOM",
    "LIDAR_MAPPING_SERVER_LOG",
    "LIDAR_LOCALIZATION_ODOM",
    "LIDAR_NAVIGATION_GLOBAL_PATH",
    "SPORT_MOD",
    "SPORT_MOD_STATE",
    "LF_SPORT_MOD_STATE",
    "MOTION_SWITCHER",
    "OBSTACLES_AVOID",
]


def make_callback(topic_name: str, log_file):
    """Create a callback that logs messages for a given topic."""

    def callback(message):
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "topic": topic_name,
            "data": message,
        }
        line = json.dumps(entry, default=str)
        log.info("[%s] %s", topic_name, line)
        log_file.write(line + "\n")
        log_file.flush()

    return callback


async def main():
    parser = argparse.ArgumentParser(description="Sniff Go2 SLAM/Nav messages")
    parser.add_argument("--ip", type=str, help="Robot IP (STA mode)")
    parser.add_argument("--serial", type=str, help="Robot serial number")
    parser.add_argument(
        "--output",
        type=str,
        default="sniff_log.jsonl",
        help="Output log file (default: sniff_log.jsonl)",
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

    log.info("Connecting to Go2...")
    await conn.connect()
    log.info("Connected. Subscribing to topics...")

    with open(args.output, "a") as log_file:
        for topic_name in SNIFF_TOPICS:
            topic_key = RTC_TOPIC.get(topic_name)
            if topic_key is None:
                log.warning("Topic %s not found in RTC_TOPIC constants", topic_name)
                continue
            conn.datachannel.pub_sub.subscribe(
                topic_key, make_callback(topic_name, log_file)
            )
            log.info("  Subscribed to %s → %s", topic_name, topic_key)

        log.info("Sniffing... Use the Unitree app to navigate. Press Ctrl+C to stop.")
        log.info("Logs written to %s", args.output)

        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
