"""Run the external tools doctor shells out to under resource limits.

Every parser here (ghostscript, tesseract, ffmpeg, ...) is fed files
from callers. A crafted file can hang one or ask it for far more memory
than the pod has, and either takes down every request sharing the pod.
Each call gets a wall-clock timeout, a CPU-seconds limit and an
address-space limit, so a bad file kills its own child process and
nothing else. Limits of 0 disable the matching check.
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


def limit_prefix(timeout: float | None = None) -> list[str]:
    """The ``prlimit`` invocation that applies the CPU and memory limits.

    Prepend it to a command. prlimit (util-linux) sets the limits and
    execs the program, which avoids a ``preexec_fn`` in a process that
    runs threads.

    :param timeout: Wall-clock seconds the call is allowed; the CPU limit
        sits a little above it, as a backstop if the timeout fails.
    """
    prefix = ["prlimit"]
    max_memory = settings.DOCTOR_SUBPROCESS_MAX_MEMORY_MB * 1024 * 1024
    if max_memory:
        prefix.append(f"--as={max_memory}")
    if timeout:
        prefix.append(f"--cpu={int(timeout) + 5}")
    return [*prefix, "--"] if len(prefix) > 1 else []


async def run_limited(
    *command: str | bytes,
    input: bytes | None = None,
    stdout: int = PIPE,
    stderr: int = PIPE,
    timeout: float | None = None,
    **kwargs: Any,
) -> tuple[Any, Any, int]:
    """Run a command and wait for it, within the configured limits.

    :param command: The program and its arguments; never a shell string.
    :param input: Bytes to send on stdin, if any.
    :param stdout: PIPE or DEVNULL.
    :param stderr: PIPE or DEVNULL.
    :param timeout: Wall-clock seconds; defaults to
        DOCTOR_SUBPROCESS_TIMEOUT_SECONDS.
    :return: (stdout, stderr, returncode); each output is bytes if piped
        and None if not (hence Any, not bytes | None, which would make
        every caller of a piped stream narrow it). A
        child killed for running too long reports TIMED_OUT, so callers
        handle it like any other failure.
    """
    if timeout is None:
        timeout = settings.DOCTOR_SUBPROCESS_TIMEOUT_SECONDS
    process = await asyncio.create_subprocess_exec(
        *limit_prefix(timeout),
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
