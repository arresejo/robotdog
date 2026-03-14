"""Entry point — navigate the Go2 to a target object.

Usage:
    uv run python main.py --ip 192.168.8.181 --target chair
"""

import asyncio
import sys

from src.navigator import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
