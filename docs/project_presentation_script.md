# 🤖 RobotDog: The Ultimate MLLM Companion
**Pitch & Presentation Script**

---

## 🎤 Introduction (The Hook)
"Imagine a world where your robotic companion doesn't just execute hardcoded buttons on a remote control, but actually sees what you see, hears what you say, and responds intelligently in real-time. Welcome to our project: A fully autonomous, voice-controlled Unitree Robot Dog powered by the Gemini Live API."

"We've bridged the gap between cutting-edge Multimodal Large Language Models (MLLMs) and physical robotics, turning an off-the-shelf Unitree robot into a conversational, spatially-aware assistant that you can talk to naturally."

---

## 💡 What Can We Achieve? (The Magic)
By giving Gemini direct tool access to the robot's physical movement and tying its visual cortex to the robot's front-facing camera, we unlock incredible use cases:

*   **Natural Voice Control:** You don’t need to know how to code. Just say, *"Stand up and say hello,"* or *"Move forward a bit."*
*   **"What do you see?" (Visual Context):** The robot streams its camera feed directly to Gemini and your browser UI simultaneously. You can ask the robot to describe its surroundings, or verify if an object is in front of it.
*   **The Object Hunt:** *"Hey robot, I can't find my red coffee mug."* The robot can look around, physically turn itself to scan a room, and stand up triumphantly when its visual feed spots your mug.

---

## 🛠️ The Technology Stack
We adhered to a strict, modern, and zero-global philosophy using best-in-class tools.

**1. The Brains: Google Gemini Live API (`google-genai`)**
We use the cutting-edge `gemini-2.5-flash-native-audio-preview` model via a WebSockets Live Session. It handles intent recognition, processes continuous audio streams (Audio-in/Audio-out), and ingests frames at ~1 FPS for real-time visual reasoning.

**2. The Muscle: Unitree WebRTC Connect**
Instead of clunky ROS setups, we use `unitree-webrtc-connect` for direct, low-latency WebRTC communication with the robot over a local network. This abstracts complex hardware protocols into Python asynchronous commands.

**3. The Backbone: FastAPI & WebSockets (Python 3.13)**
A robust FastAPI server acts as the bridge. It exposes a WebSocket endpoint that connects the user's browser (microphone + UI) to the Gemini backend, while spawning background tasks to constantly poll the robot's camera.

**4. The Environment: `uv`**
Everything is strictly isolated and managed using Astral's `uv`. No global system dependencies required, ensuring the setup is reproducible in seconds.

**5. The Interface: Vanilla JS & HTML**
We built a lightweight frontend that requires zero bundlers. It captures 16kHz PCM audio from your microphone, streams it to the backend, and renders the robot's point-of-view via a dynamic `<canvas>` display.

---

## 🔄 How It Actually Works (The Architecture)

_"So, how fast is it really?"_

It operates in a continuous, asynchronous loop:
1.  **Audio Stream:** You speak into your browser. The frontend captures raw audio and pipes it over WebSockets to the Python server, which forwards it to Gemini.
2.  **Vision Stream:** Simultaneously, a background task on the server grabs JPEG frames from the robot's native camera every second and pushes them into Gemini's context window AND your browser UI.
3.  **Tool Execution:** When Gemini realizes you gave a physical command, it triggers a registered "Tool" (e.g., `robot_command("turn_left")`). 
4.  **Hardware Handshake:** Our `RobotController` safely catches this API request, enforces hardcoded safety limits (max 0.6 m/s speed, max 3 seconds duration), and publishes the WebRTC payload to the robot's motors.
5.  **Audio Feedback:** Gemini audibly replies to you _while_ the robot moves, creating a seamless, sci-fi-like experience.

---

## 🛡️ Safety & Reliability First
We didn't just wire an AI to motors; we built guardrails.
*   **Sandboxed Environment:** Everything runs inside a `dry_run` mode for testing logic before putting a $2000 machine at risk.
*   **Time & Speed Boxing:** The AI cannot command a continuous sprint. We force short bursts of motion.
*   **Mode Enforcement:** The controller automatically forces the robot into "normal" walking mode before accepting commands, avoiding terrifying physical glitches.

## 🚀 The Future
What we have today is a proof of concept. But tomorrow, this architecture allows us to attach thermal plugins, LiDAR mapping, or specialized manipulation arms. The foundation—a real-time, vision-enabled conversational agent tied to physical hardware—is fully online.
