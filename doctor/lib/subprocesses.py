"""Run the external tools doctor shells out to under a time limit.

Every parser here (ghostscript, tesseract, ffmpeg, ...) is fed files from
callers. A crafted file can hang one, and a hang holds the single worker
for gunicorn's 90 minutes. A child that overruns its timeout is killed,
along with anything it spawned, and reported as failed. Memory is left to
the pod's own limit.
"""

import asyncio
import logging
import os
import signal
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

PIPE = asyncio.subprocess.PIPE
DEVNULL = asyncio.subprocess.DEVNULL

# Returncode reported for a child killed for exceeding its timeout.
TIMED_OUT = -signal.SIGKILL


async def run_limited(
    *command: str | bytes,
    input: bytes | None = None,
    stdout: int = PIPE,
    stderr: int = PIPE,
    timeout: float | None = None,
    **kwargs: Any,
) -> tuple[Any, Any, int]:
    """Run a command and wait for it, within the time limit.

    :param command: The program and its arguments; never a shell string.
    :param input: Bytes to send on stdin, if any.
    :param stdout: PIPE or DEVNULL.
    :param stderr: PIPE or DEVNULL.
    :param timeout: Wall-clock seconds; defaults to
        DOCTOR_SUBPROCESS_TIMEOUT_SECONDS.
    :return: (stdout, stderr, returncode); each output is bytes if piped
        and None if not. A child killed for running too long reports
        TIMED_OUT, so callers handle it like any other failure.
    """
    if timeout is None:
        timeout = settings.DOCTOR_SUBPROCESS_TIMEOUT_SECONDS
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=PIPE if input is not None else DEVNULL,
        stdout=stdout,
        stderr=stderr,
        close_fds=True,
        # Own process group, so a timeout takes out anything it spawned.
        start_new_session=True,
        **kwargs,
    )
    try:
        out, err = await asyncio.wait_for(
            process.communicate(input), timeout=timeout or None
        )
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        logger.error(
            "%s killed after exceeding its %ss timeout", command[0], timeout
        )
        return (
            b"" if stdout == PIPE else None,
            b"killed: exceeded the time limit",
            TIMED_OUT,
        )
    return out, err, process.returncode or 0
