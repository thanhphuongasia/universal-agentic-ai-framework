"""SandboxManager v0.1 — subprocess-based isolation with resource limits."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ryuu_core.errors import RetryableError


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


def _apply_resource_limits(memory_limit_mb: int, cpu_seconds: float) -> None:
    if sys.platform == "win32":
        return

    import resource  # noqa: PLC0415

    mem_bytes = memory_limit_mb * 1024 * 1024
    cpu_limit = max(1, int(cpu_seconds))

    if sys.platform == "linux":
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (OSError, ValueError):
            pass
    else:
        try:
            resource.setrlimit(resource.RLIMIT_DATA, (mem_bytes, mem_bytes))
        except (OSError, ValueError):
            pass

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
    except (OSError, ValueError):
        pass


class SubprocessSandbox:
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
        base = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "en_US.UTF-8",
        }
        if override:
            base.update(override)
        return base


class SandboxManager:
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
