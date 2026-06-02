#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." &> /dev/null && pwd)"
cd "$PROJECT_DIR"

mapfile -t LOG_FILES < <(
    find . -type f \
        \( -name "*.log" -o -name "*.log.*" \) \
        -not -path "./venv/*" \
        -not -path "./.git/*" \
        | sort
)

for file in "${LOG_FILES[@]}"; do
    rm -f "$file"
done

if [ "${#LOG_FILES[@]}" -eq 0 ]; then
    echo "No log files found."
    exit 0
fi

echo "Removed ${#LOG_FILES[@]} log file(s)."
