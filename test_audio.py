"""Quick test: play a beep on the robot speaker via upload-then-play."""

import asyncio
import base64
import hashlib
import io
import json
import math
import os
import struct
import time
import wave
from pathlib import Path

# Load .env
_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import AUDIO_API

import logging
logging.basicConfig(level=logging.INFO)


def generate_beep_wav_bytes(freq=440, duration=1.5, sample_rate=44100, amplitude=0.5) -> bytes:
    """Generate a sine wave beep as a complete WAV file in memory (44100 Hz, mono, 16-bit)."""
    buf = io.BytesIO()
    n_samples = int(sample_rate * duration)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            t = i / sample_rate
            value = int(amplitude * 32767 * math.sin(2 * math.pi * freq * t))
            frames.extend(struct.pack("<h", value))
        wf.writeframes(frames)
    return buf.getvalue()


async def main():
    ip = os.environ.get("ROBOT_IP", "172.17.224.149")
    print(f"Connecting to robot at {ip}...")
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip)
    await conn.connect()
    print("Connected.")

    pub_sub = conn.datachannel.pub_sub
    topic = "rt/api/audiohub/request"

    # Generate beep WAV
    wav_data = generate_beep_wav_bytes(freq=440, duration=1.5, sample_rate=44100)
    file_name = f"beep_test_{int(time.time() * 1000)}"
    file_md5 = hashlib.md5(wav_data).hexdigest()
    print(f"WAV size: {len(wav_data)} bytes, file_name: {file_name}")

    # Base64 encode the entire WAV file
    b64_data = base64.b64encode(wav_data).decode("utf-8")

    # Split into 4KB chunks
    chunk_size = 4096
    chunks = [b64_data[i:i + chunk_size] for i in range(0, len(b64_data), chunk_size)]
    total_chunks = len(chunks)
    print(f"Uploading {total_chunks} chunks...")

    # Upload all chunks via UPLOAD_AUDIO_FILE
    for i, chunk in enumerate(chunks, 1):
        parameter = {
            "file_name": file_name,
            "file_type": "wav",
            "file_size": len(wav_data),
            "current_block_index": i,
            "total_block_number": total_chunks,
            "block_content": chunk,
            "current_block_size": len(chunk),
            "file_md5": file_md5,
            "create_time": int(time.time() * 1000),
        }
        await pub_sub.publish_request_new(topic, {
            "api_id": AUDIO_API["UPLOAD_AUDIO_FILE"],
            "parameter": json.dumps(parameter, ensure_ascii=True),
        })
        if i % 50 == 0 or i == total_chunks:
            print(f"  Uploaded chunk {i}/{total_chunks}")
        await asyncio.sleep(0.1)

    print("Upload complete. Getting audio list...")

    # Get audio list to find UUID
    response = await pub_sub.publish_request_new(topic, {
        "api_id": AUDIO_API["GET_AUDIO_LIST"],
        "parameter": json.dumps({}),
    })

    audio_uuid = None
    try:
        data_str = response.get("data", {}).get("data", "{}")
        audio_list = json.loads(data_str).get("audio_list", [])
        print(f"Found {len(audio_list)} audio files on robot")
        entry = next((a for a in audio_list if a.get("CUSTOM_NAME") == file_name), None)
        if entry:
            audio_uuid = entry["UNIQUE_ID"]
            print(f"Found our file: UUID={audio_uuid}")
    except Exception as e:
        print(f"Error parsing audio list: {e}")

    if audio_uuid:
        # Set play mode to no_cycle so it doesn't loop
        await pub_sub.publish_request_new(topic, {
            "api_id": AUDIO_API["SET_PLAY_MODE"],
            "parameter": json.dumps({"play_mode": "no_cycle"}),
        })
        print("Play mode set to no_cycle.")

        print(f"Playing audio...")
        await pub_sub.publish_request_new(topic, {
            "api_id": AUDIO_API["SELECT_START_PLAY"],
            "parameter": json.dumps({"unique_id": audio_uuid}),
        })
        print("Play command sent. Waiting for playback...")
        await asyncio.sleep(3)

        # Delete the uploaded file to avoid clutter
        print("Deleting uploaded audio file...")
        await pub_sub.publish_request_new(topic, {
            "api_id": AUDIO_API["SELECT_DELETE"],
            "parameter": json.dumps({"unique_id": audio_uuid}),
        })
    else:
        print("ERROR: Could not find uploaded audio file!")

    print("Done. Disconnecting...")
    await conn.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
