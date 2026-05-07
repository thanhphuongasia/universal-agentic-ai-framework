"""Tests for uaaf.execution.sandbox (SandboxManager) — T11."""

from __future__ import annotations

import sys

import pytest

from uaaf.execution.sandbox import SandboxManager, SandboxResult

# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


def test_run_simple_command() -> None:
    sandbox = SandboxManager()
    result = sandbox.run([sys.executable, "-c", "print('hello')"])
    assert result.success
    assert "hello" in result.stdout
    assert result.returncode == 0


def test_run_captures_stderr() -> None:
    sandbox = SandboxManager()
    result = sandbox.run([sys.executable, "-c", "import sys; sys.stderr.write('err\n')"])
    assert "err" in result.stderr


def test_run_captures_return_code() -> None:
    sandbox = SandboxManager()
    result = sandbox.run([sys.executable, "-c", "raise SystemExit(42)"])
    assert result.returncode == 42
    assert not result.success


def test_run_stdin() -> None:
    sandbox = SandboxManager()
    result = sandbox.run(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"],
        stdin="hello from stdin",
    )
    assert "hello from stdin" in result.stdout


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_run_timeout_is_enforced() -> None:
    sandbox = SandboxManager()
    result = sandbox.run(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        timeout=0.5,
    )
    assert result.timed_out is True
    assert not result.success


def test_run_finishes_within_timeout() -> None:
    sandbox = SandboxManager()
    result = sandbox.run(
        [sys.executable, "-c", "pass"],
        timeout=5.0,
    )
    assert result.timed_out is False
    assert result.success


# ---------------------------------------------------------------------------
# Resource limits (Linux/macOS only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS memory enforcement only reliable on Linux")
def test_memory_limit_blocks_large_allocation() -> None:
    sandbox = SandboxManager()
    # Try to allocate more than the limit — process should be killed by OOM
    result = sandbox.run(
        [sys.executable, "-c", "x = bytearray(512 * 1024 * 1024)"],  # 512MB
        memory_limit_mb=64,
        timeout=5.0,
    )
    # On Linux, the process should be killed; returncode != 0
    assert not result.success


@pytest.mark.skipif(sys.platform == "win32", reason="resource limits not available on Windows")
def test_cpu_limit_blocks_infinite_loop() -> None:
    sandbox = SandboxManager()
    result = sandbox.run(
        [sys.executable, "-c", "while True: pass"],
        cpu_seconds=1.0,
        timeout=5.0,
    )
    # Process should be terminated by SIGXCPU or killed by timeout
    assert not result.success


# ---------------------------------------------------------------------------
# Output capture
# ---------------------------------------------------------------------------


def test_output_capture_both_streams() -> None:
    sandbox = SandboxManager()
    # Use separate commands to avoid newline-in-string issues with -c argument.
    r_out = sandbox.run([sys.executable, "-c", "print('out')"])
    r_err = sandbox.run([sys.executable, "-c", "import sys; sys.stderr.write('err')"])
    assert "out" in r_out.stdout
    assert "err" in r_err.stderr


# ---------------------------------------------------------------------------
# SandboxResult
# ---------------------------------------------------------------------------


def test_sandbox_result_success_property() -> None:
    r = SandboxResult(returncode=0, stdout="ok", stderr="")
    assert r.success is True


def test_sandbox_result_failure_on_nonzero() -> None:
    r = SandboxResult(returncode=1, stdout="", stderr="error")
    assert r.success is False


def test_sandbox_result_failure_on_timeout() -> None:
    r = SandboxResult(returncode=0, stdout="", stderr="", timed_out=True)
    assert r.success is False
