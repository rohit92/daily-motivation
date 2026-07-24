#!/bin/zsh
# One command to open your control room:  ./dashboard.sh
export PATH="$PATH:/opt/homebrew/bin"   # append: keep our python3 first
cd "$(dirname "$0")"

# Start the free local AI (Ollama) so the coach is intelligent, if it's installed
# and not already running. Falls back gracefully if Ollama isn't there.
if command -v ollama >/dev/null 2>&1; then
  if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Starting the local AI (Ollama)…"
    (OLLAMA_FLASH_ATTENTION=1 ollama serve >/tmp/ollama.log 2>&1 &)
    sleep 2
  fi
fi

python3 dashboard.py
