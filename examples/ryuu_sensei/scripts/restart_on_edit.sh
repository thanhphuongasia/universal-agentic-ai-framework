#!/bin/bash
# Claude Code PostToolUse hook — restart ryuu_sensei bot when relevant files change.
#
# Triggered after Edit/Write/MultiEdit/NotebookEdit on file paths.
# Claude Code passes the edited paths via $CLAUDE_FILE_PATHS (newline- or space-separated).
#
# Restart only if ANY edited path matches:
#   examples/ryuu_sensei/   — handler / main / skills / fixtures
#   packages/*/src/         — framework source (ryuu, ryuu-messaging-*, etc.)
#
# Skip:
#   tests/, *.md, scripts/, fixtures/*.yml — non-code or non-runtime files
#
# Exit 0 always so the hook never blocks Claude Code, even on errors.

set -u

PATHS="${CLAUDE_FILE_PATHS:-}"
if [[ -z "${PATHS}" ]]; then
    exit 0   # nothing to check
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Normalize: split on newlines or spaces
SHOULD_RESTART=0
while IFS= read -r p; do
    [[ -z "${p}" ]] && continue
    # Match patterns — accept both absolute and relative paths
    if [[ "${p}" == *"examples/ryuu_sensei/"*".py" ]] \
       || [[ "${p}" == *"packages/"*"/src/"*".py" ]]; then
        # Exclude test files and scripts/
        if [[ "${p}" != *"/tests/"* ]] \
           && [[ "${p}" != *"/scripts/"* ]] \
           && [[ "${p}" != *"test_"*".py" ]]; then
            SHOULD_RESTART=1
            echo "[restart_on_edit] match: ${p}"
            break
        fi
    fi
done <<< "$(echo "${PATHS}" | tr ' ' '\n')"

if [[ "${SHOULD_RESTART}" -eq 1 ]]; then
    bash "${SCRIPT_DIR}/restart_bot.sh"
fi

exit 0
