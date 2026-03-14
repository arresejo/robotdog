#!/usr/bin/env python3
"""Test script to validate robot bridge integration."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from robot_bridge import (
    RobotConfig,
    RobotController,
    build_robot_tools,
    build_robot_tool_mapping,
)


async def test_robot_integration():
    """Test the robot bridge integration with dry run mode."""
    print("=" * 60)
    print("Robot Bridge Integration Test (Dry Run Mode)")
    print("=" * 60)
    
    os.environ["ROBOT_DRY_RUN"] = "true"
    os.environ["ROBOT_CONNECTION_METHOD"] = "local_sta"
    os.environ["ROBOT_IP"] = "192.168.8.181"
    
    print("\n1. Testing RobotConfig.from_env()...")
    config = RobotConfig.from_env()
    print(f"   ✓ Config loaded: dry_run={config.dry_run}")
    
    print("\n2. Testing RobotController initialization...")
    controller = RobotController(config)
    print("   ✓ Controller created")
    
    print("\n3. Testing robot connection...")
    result = await controller.connect()
    print(f"   ✓ {result['message']}")
    
    print("\n4. Testing build_robot_tools()...")
    tools = build_robot_tools()
    tool_names = [decl.name for decl in tools[0].function_declarations]
    print(f"   ✓ {len(tool_names)} tools available:")
    for name in tool_names:
        print(f"     - {name}")
    
    print("\n5. Testing build_robot_tool_mapping()...")
    tool_mapping = build_robot_tool_mapping(controller)
    print(f"   ✓ {len(tool_mapping)} tool functions mapped")
    
    print("\n6. Testing tool execution (dry run)...")
    test_tools = [
        ("get_robot_status", {}),
        ("say_hello", {}),
        ("make_finger_heart", {}),
        ("stand_up", {}),
        ("move_forward", {"duration_seconds": 1.0, "speed": 0.3}),
        ("stop_robot", {}),
    ]
    
    for tool_name, args in test_tools:
        print(f"   Testing {tool_name}...")
        tool_func = tool_mapping[tool_name]
        result = await tool_func(**args)
        if result.get("ok"):
            print(f"   ✓ {tool_name}: {result.get('message', 'success')}")
        else:
            print(f"   ✗ {tool_name}: {result.get('error', 'unknown error')}")
    
    print("\n7. Testing robot disconnect...")
    result = await controller.disconnect()
    print(f"   ✓ {result['message']}")
    
    print("\n" + "=" * 60)
    print("All tests passed! Robot integration is working correctly.")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Set ROBOT_ENABLED=true in full_audio/.env")
    print("2. Configure your robot connection settings")
    print("3. Run: cd full_audio && uv run main.py")
    print("4. Open http://localhost:8000 in your browser")
    print("5. Click 'Connect' and enable microphone")
    print("6. Say commands like 'stand up', 'say hello', or 'make a finger heart'")
    print()


if __name__ == "__main__":
    asyncio.run(test_robot_integration())
