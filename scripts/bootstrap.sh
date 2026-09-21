#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install FFmpeg: https://brew.sh"
  exit 1
fi

brew bundle --file "$project_dir/Brewfile"

python_bin="$(brew --prefix python@3.14)/bin/python3.14"
"$python_bin" -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install --upgrade pip
"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"

echo
echo "Setup complete. Start the app with:"
echo "  .venv/bin/python music_convert.py"
