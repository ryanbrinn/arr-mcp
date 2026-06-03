"""Safe subprocess execution for arr-agent."""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

_TIMEOUT = 120  # seconds


async def run_command(*args: str) -> tuple[int, str]:
    """Run a command and return (exit_code, combined_output).

    Uses create_subprocess_exec (never shell=True) to prevent injection.
    """
    log.info("Running command: %s", " ".join(args))
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return 1, f"Command timed out after {_TIMEOUT}s"
    output = stdout.decode("utf-8", errors="replace")
    exit_code = proc.returncode if proc.returncode is not None else 1
    log.info("Command exit_code=%d output_len=%d", exit_code, len(output))
    return exit_code, output
