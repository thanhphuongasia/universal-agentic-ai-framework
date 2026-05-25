#!/bin/bash
# Restart ryuu_sensei Telegram bot in background.
#
# - Kills any running `main_ryuu` Python process (SIGTERM, then SIGKILL fallback).
# - Starts a new instance detached with nohup so it survives shell exit.
# - Inherits env vars from the calling shell (OPENAI_API_KEY, RYUU_BOT_TOKEN, etc.).
# - Stdout/stderr → ~/.ryuu/ryuu.log (rotating handler in Python already writes there).
# - Returns within ~2s so Claude Code hooks don't hang.
#
# Usage: bash examples/ryuu_sensei/scripts/restart_bot.sh
# Triggered automatically by .claude/settings.json PostToolUse hook.

set -u

# Locate repo root (script lives at examples/ryuu_sensei/scripts/restart_bot.sh)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LOG_DIR="${HOME}/.ryuu"
LOG_FILE="${LOG_DIR}/ryuu_bot.out"   # raw stdout/stderr — Python logs go to ryuu.log separately
mkdir -p "${LOG_DIR}"

# Find existing bot PID(s)
PIDS=$(pgrep -f "examples\.ryuu_sensei\.main_ryuu" || true)

if [[ -n "${PIDS}" ]]; then
    echo "[restart_bot] stopping existing bot (pids: ${PIDS})"
    # shellcheck disable=SC2086
    kill -TERM ${PIDS} 2>/dev/null || true
    # Wait up to 3s for clean exit
    for _ in 1 2 3 4 5 6; do
        sleep 0.5
        if ! pgrep -f "examples\.ryuu_sensei\.main_ryuu" >/dev/null; then
            break
        fi
    done
    # Force-kill if still alive
    STRAGGLERS=$(pgrep -f "examples\.ryuu_sensei\.main_ryuu" || true)
    if [[ -n "${STRAGGLERS}" ]]; then
        echo "[restart_bot] force-killing stragglers: ${STRAGGLERS}"
        # shellcheck disable=SC2086
        kill -KILL ${STRAGGLERS} 2>/dev/null || true
    fi
fi

# Resolve python executable — prefer one already on PATH
PYTHON_BIN="${PYTHON:-python3}"

# Launch detached with nohup; stdout/stderr append to log file
cd "${REPO_ROOT}" || { echo "[restart_bot] cd ${REPO_ROOT} failed"; exit 1; }
nohup "${PYTHON_BIN}" -m examples.ryuu_sensei.main_ryuu --telegram \
    >>"${LOG_FILE}" 2>&1 </dev/null &

NEW_PID=$!
disown 2>/dev/null || true
echo "[restart_bot] new bot pid=${NEW_PID} → ${LOG_FILE}"
