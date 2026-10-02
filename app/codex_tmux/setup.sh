#!/usr/bin/env bash
set -euo pipefail
task_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cao_source="$(cd -- "$task_dir/../../cli-agent-orchestrator" && pwd)"
task_root="$HOME/.local/share/aiflow-codex"
if [ "$EUID" -eq 0 ]; then
  echo 'Run as your normal Ubuntu user; sudo is requested only for apt.' >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-dev build-essential tmux
command -v codex >/dev/null || { echo 'Install Node.js and Codex CLI in Ubuntu, then rerun setup.' >&2; exit 1; }
mkdir -p "$task_root"
chmod 700 "$task_root"
python3 -m venv "$task_root/venv"
"$task_root/venv/bin/python" -m pip install "$cao_source"
python3 "$task_dir/bridge.py" install
echo 'Next: codex login (ChatGPT), then run python3 bridge.py serve from this folder.'
