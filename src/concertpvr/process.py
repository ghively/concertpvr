"""Subprocess wrapper with a Protocol seam for tests."""

from __future__ import annotations

import asyncio
import signal
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ManagedProcess(Protocol):
    pid: int

    def stdout_lines(self) -> AsyncIterator[str]: ...
    def stderr_lines(self) -> AsyncIterator[str]: ...
    async def wait(self) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


@runtime_checkable
class ProcessRunner(Protocol):
    async def spawn(
        self,
        argv: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> ManagedProcess: ...


# ── Real implementation ───────────────────────────────────────────────────


class _RealManagedProcess:
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc
        self.pid = proc.pid

    async def stdout_lines(self) -> AsyncIterator[str]:
        if self._proc.stdout is None:
            raise RuntimeError("stdout pipe not available")
        async for raw in self._proc.stdout:
            yield raw.decode(errors="replace").rstrip("\r\n")

    async def stderr_lines(self) -> AsyncIterator[str]:
        if self._proc.stderr is None:
            raise RuntimeError("stderr pipe not available")
        async for raw in self._proc.stderr:
            yield raw.decode(errors="replace").rstrip("\r\n")

    async def wait(self) -> int:
        return await self._proc.wait()

    def terminate(self) -> None:
        if self._proc.returncode is None:
            self._proc.terminate()

    def kill(self) -> None:
        if self._proc.returncode is None:
            self._proc.kill()


class AsyncSubprocessRunner:
    async def spawn(
        self,
        argv: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> ManagedProcess:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return _RealManagedProcess(proc)


# ── Fake for tests ────────────────────────────────────────────────────────


class _FakeManagedProcess:
    def __init__(
        self,
        stdout: list[str],
        stderr: list[str],
        exit_code: int,
        *,
        blocking: bool = False,
    ) -> None:
        self.pid = 0
        self._stdout = deque(stdout)
        self._stderr = deque(stderr)
        self._exit_code = exit_code
        self._terminated = False
        self._killed = False
        # _done is pre-set (ready to return) unless blocking=True is requested.
        # blocking=True makes wait() suspend until terminate() or kill() is called,
        # which is required for tests that need the fake process to keep "running".
        self._done: asyncio.Event = asyncio.Event()
        if not blocking:
            self._done.set()

    async def stdout_lines(self) -> AsyncIterator[str]:
        while self._stdout:
            yield self._stdout.popleft().rstrip("\r\n")
            await asyncio.sleep(0)

    async def stderr_lines(self) -> AsyncIterator[str]:
        while self._stderr:
            yield self._stderr.popleft().rstrip("\r\n")
            await asyncio.sleep(0)

    async def wait(self) -> int:
        await self._done.wait()
        if self._killed:
            sigkill_val = signal.SIGKILL.value if hasattr(signal, "SIGKILL") else 9
            return -sigkill_val
        if self._terminated:
            return -signal.SIGTERM.value
        return self._exit_code

    def terminate(self) -> None:
        self._terminated = True
        self._done.set()

    def kill(self) -> None:
        self._killed = True
        self._done.set()


class FakeProcessRunner:
    """Test double. Pre-load expected outputs with .queue() before .spawn()."""

    def __init__(self) -> None:
        self._queued: deque[tuple[list[str], list[str], int, bool]] = deque()
        self.spawned: list[list[str]] = []

    def queue(
        self,
        _name: str,
        stdout: list[str],
        stderr: list[str] | None = None,
        exit_code: int = 0,
        *,
        blocking: bool = False,
    ) -> None:
        self._queued.append((list(stdout), list(stderr or []), exit_code, blocking))

    async def spawn(
        self,
        argv: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> ManagedProcess:
        self.spawned.append(list(argv))
        if not self._queued:
            return _FakeManagedProcess([], [], 0)
        stdout, stderr, exit_code, blocking = self._queued.popleft()
        return _FakeManagedProcess(stdout, stderr, exit_code, blocking=blocking)
