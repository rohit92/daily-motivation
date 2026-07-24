#!/bin/zsh
# weekly.sh — the automated weekly routine:
#   1. scan what's trending in the niche this week
#   2. generate 7 fresh videos from the script queue
# Runs automatically via the launchd job (see com.dailymotivation.weekly.plist),
# or run it by hand any time:  ./weekly.sh
export PATH="$PATH:/opt/homebrew/bin"   # append: keep our python3 first
cd "$(dirname "$0")"

echo "=================================================="
echo " WEEKLY RUN — $(date)"
echo "=================================================="

echo "\n[1/2] Scanning this week's trends..."
python3 trend_scan.py --region US

echo "\n[2/2] Generating 7 videos..."
python3 make_video.py --batch 7

echo "\nDone. New videos are in ./output/  (upload one per day)."
echo "If it says 'All items used', add more scripts to content.json first."
