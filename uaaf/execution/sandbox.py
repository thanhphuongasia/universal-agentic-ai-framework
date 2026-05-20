"""SandboxManager v0.1 — subprocess-based isolation with resource limits.

v0.1 provides subprocess-level isolation only (not container-grade).
It is suitable for trusted-but-isolated code.  For untrusted code, a
container backend (Phase 3+) should be used.

Linux/macOS: resource limits enforced via ``resource.setrlimit``.
Windows: resource limits skipped with a warning (subprocess still runs).
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from uaaf_workflow.errors import RetryableError

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    memory_exceeded: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.memory_exceeded


# ---------------------------------------------------------------------------
# Protocol (Phase 3+ will add DockerSandbox, FirecrackerSandbox)
# ---------------------------------------------------------------------------


@runtime_checkable
class ISandbox(Protocol):
    def run(
        self,
        command: list[str],
        *,
        timeout: float,
        memory_limit_mb: int,
        cpu_seconds: float,
        env: dict[str, str] | None,
        stdin: str | None,
    ) -> SandboxResult: ...


# ---------------------------------------------------------------------------
# SandboxManager (subprocess backend)
# ---------------------------------------------------------------------------


def _apply_resource_limits(memory_limit_mb: int, cpu_seconds: float) -> None:
    """Called inside the child process (preexec_fn) to apply limits.

    On Linux: RLIMIT_AS (virtual address space) + RLIMIT_CPU.
    On macOS: RLIMIT_DATA (heap) + RLIMIT_CPU.  RLIMIT_AS is unreliable on
    macOS because the interpreter's own address space often exceeds 256MB.
    """
    if sys.platform == "win32":
        return  # resource module not available on Windows

    import resource  # noqa: PLC0415 (local import — only in child process)

    mem_bytes = memory_limit_mb * 1024 * 1024
    cpu_limit = max(1, int(cpu_seconds))

    if sys.platform == "linux":
        # RLIMIT_AS: total virtual address space.
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (OSError, ValueError):
            pass  # limit below current usage — skip
    else:
        # macOS / other POSIX: limit heap data segment only.
        try:
            resource.setrlimit(resource.RLIMIT_DATA, (mem_bytes, mem_bytes))
        except (OSError, ValueError):
            pass

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
    except (OSError, ValueError):
        pass


class SubprocessSandbox:
    """Subprocess-based sandbox — one subprocess per ``run()`` call."""

    def run(
        self,
        command: list[str],
        *,
        timeout: float = 10.0,
        memory_limit_mb: int = 256,
        cpu_seconds: float = 5.0,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> SandboxResult:
        sandbox_env = self._build_env(env)
        preexec = None if sys.platform == "win32" else (
            lambda: _apply_resource_limits(memory_limit_mb, cpu_seconds)
        )

        try:
            proc = subprocess.run(
                command,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=sandbox_env,
                preexec_fn=preexec,
            )
            return SandboxResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                returncode=-1,
                stdout=exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                stderr=exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
                timed_out=True,
            )
        except MemoryError:
            return SandboxResult(returncode=-1, stdout="", stderr="memory exceeded", memory_exceeded=True)
        except Exception as exc:
            raise RetryableError(f"Sandbox subprocess failed: {exc}") from exc

    @staticmethod
    def _build_env(override: dict[str, str] | None) -> dict[str, str]:
        """Scrub env and apply overrides.

        Strips PATH-adjacent vars that could be exploited; keeps minimal safe set.
        """
        base = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "en_US.UTF-8",
        }
        if override:
            base.update(override)
        return base


class SandboxManager:
    """Facade over ISandbox implementations.

    v0.1 uses SubprocessSandbox.  Phase 3+ will allow injecting a container backend.
    """

    def __init__(self, backend: ISandbox | None = None) -> None:
        self._backend: ISandbox = backend or SubprocessSandbox()

    def run(
        self,
        command: list[str],
        *,
        timeout: float = 10.0,
        memory_limit_mb: int = 256,
        cpu_seconds: float = 5.0,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> SandboxResult:
        """Run *command* in the sandbox and return the result.

        This is a synchronous call — wrap in ``anyio.to_thread.run_sync`` if
        you need to call from async code without blocking the event loop.
        """
        if sys.platform == "win32":
            import warnings

            warnings.warn(
                "SandboxManager resource limits are not enforced on Windows.",
                stacklevel=2,
            )
        return self._backend.run(
            command,
            timeout=timeout,
            memory_limit_mb=memory_limit_mb,
            cpu_seconds=cpu_seconds,
            env=env,
            stdin=stdin,
        )
