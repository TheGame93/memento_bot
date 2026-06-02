#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." &> /dev/null && pwd)"
cd "$PROJECT_DIR"

declare -a TEST_ARTIFACT_FILES=()
declare -a ZIP_FILES=()

if [ -d "./tests/log" ]; then
    mapfile -t TEST_ARTIFACT_FILES < <(
        find ./tests/log -maxdepth 1 -type f \
            \( -name "*.log" -o -name "*.log.*" -o -name "*report*.json" \) \
            -not -name ".gitkeep" \
            | sort -u
    )
fi

if [ -d "./backups/users/1001" ]; then
    mapfile -t ZIP_FILES < <(
        find ./backups/users/1001 -type f -name "*.zip" | sort
    )
fi

for file in "${TEST_ARTIFACT_FILES[@]}"; do
    rm -f "$file"
done

for file in "${ZIP_FILES[@]}"; do
    rm -f "$file"
done

if [ "${#TEST_ARTIFACT_FILES[@]}" -eq 0 ] && [ "${#ZIP_FILES[@]}" -eq 0 ]; then
    echo "No test artifacts or 1001 backups found."
    exit 0
fi

echo "Removed ${#TEST_ARTIFACT_FILES[@]} test artifact file(s)."
echo "Removed ${#ZIP_FILES[@]} backup zip(s) from backups/users/1001."
