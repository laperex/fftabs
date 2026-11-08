#!/bin/sh
# Stub rofi script for testing fftabs
set -e

STUB_DIR="${ROFI_STUB_DIR:-/tmp/rofi_stub}"
mkdir -p "$STUB_DIR"

# Record argv
printf "%s\n" "$@" > "$STUB_DIR/argv"

# Record stdin
cat > "$STUB_DIR/stdin"

# Output selection to stdout
echo "${ROFI_STUB_SELECTION:-0}"

# Exit code
exit "${ROFI_STUB_EXIT:-0}"
