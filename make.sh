#!/bin/zsh
# Convenience launcher so you don't have to think about PATH.
# Usage:
#   ./make.sh            -> make the next 1 video
#   ./make.sh --batch 7  -> make the next 7
#   ./make.sh --list-voices
export PATH="$PATH:/opt/homebrew/bin"   # append: keep our python3 first
cd "$(dirname "$0")"
python3 make_video.py "$@"
