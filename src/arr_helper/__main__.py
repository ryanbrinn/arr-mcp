"""Entry point for arr-agent."""

from __future__ import annotations

import asyncio
import logging
import sys

from arr_helper.server import serve


def main() -> None:
    """Configure logging and start the Unix socket server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        stream=sys.stdout,
    )
    asyncio.run(serve())


if __name__ == "__main__":
    main()
