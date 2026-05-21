#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 user@host [remote_path] [ssh_port]" >&2
  echo "Example: $0 root@203.0.113.10 /var/www/soniccity.app 22" >&2
  exit 1
fi

REMOTE_HOST="$1"
REMOTE_PATH="${2:-/var/www/soniccity.app}"
SSH_PORT="${3:-22}"
LOCAL_AUDIO_DIR="${LOCAL_AUDIO_DIR:-static/audio/}"
REMOTE_AUDIO_DIR="${REMOTE_PATH%/}/static/audio/"

if [ ! -d "$LOCAL_AUDIO_DIR" ]; then
  echo "Local audio directory not found: $LOCAL_AUDIO_DIR" >&2
  exit 1
fi

echo "Syncing $LOCAL_AUDIO_DIR to $REMOTE_HOST:$REMOTE_AUDIO_DIR"
echo "SSH port: $SSH_PORT"

ssh -p "$SSH_PORT" "$REMOTE_HOST" "mkdir -p '$REMOTE_AUDIO_DIR'"

rsync -azP --delete \
  -e "ssh -p $SSH_PORT" \
  "$LOCAL_AUDIO_DIR" \
  "$REMOTE_HOST:$REMOTE_AUDIO_DIR"

echo "Audio sync complete."
