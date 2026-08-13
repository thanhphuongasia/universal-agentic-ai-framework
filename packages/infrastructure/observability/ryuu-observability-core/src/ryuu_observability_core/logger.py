"""ILogger — generic structured logging protocol.

Decouples application code from the logging backend so callers can switch
between stdlib logging, structlog, CloudWatch, Datadog, etc. without touching
business logic.

Usage:
    # In application code — depend on the protocol, not the implementation
    def my_fn(logger: ILogger) -> None:
        logger.info("something happened: %s", value)

    # Wire-up at entry point (dev_server.py, main.py, etc.)
    from ryuu_observability_core import StdlibLogger
    my_fn(logger=StdlibLogger("my_module"))
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ILogger(Protocol):
    """Minimal structured-logging contract.

    Implementations must accept the same (msg, *args, **kwargs) signature
    as Python's stdlib logging so stdlib-backed implementations need zero
    adaptation.
    """

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


class NullLogger:
    """No-op logger — default for tests and library code that doesn't need logs."""

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: pass
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: pass
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: pass
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: pass
    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: pass


class StdlibLogger:
    """ILogger adapter over Python's stdlib logging.Logger.

    Drop-in replacement for ``logging.getLogger(name)`` that satisfies the
    ILogger protocol and can be swapped for any other backend.

    Args:
        name: Logger name, same as ``logging.getLogger(name)``.
        level: Optional override; if None the root-logger level applies.
    """

    def __init__(self, name: str = "ryuu", level: int | None = None) -> None:
        self._log = logging.getLogger(name)
        if level is not None:
            self._log.setLevel(level)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.exception(msg, *args, **kwargs)
