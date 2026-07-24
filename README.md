# Daily Motivation — Faceless Shorts Generator

Generates ready-to-upload vertical (1080×1920) motivational Shorts, ~15–20s each:
a natural voiceover, on-screen captions that change with each spoken line, and
license-free background images with a slow Ken Burns zoom.

**100% free and copyright-safe** (important for monetization):
- **Voice:** `edge-tts` neural voice (`en-US-AndrewNeural`) — very natural.
  Falls back to **Piper** (fully offline) if there's no internet.
- **Images:** `assets/backgrounds/` — sourced from Picsum/Pexels (free for
  commercial use). **Never** put random Google-image-search results here; most
  are copyrighted and will get the channel demonetized or struck.

## Make videos

```bash
cd ~/youtube
./make.sh              # make the next 1 video
./make.sh --batch 5    # make several at once
./make.sh --reset      # forget history and start the content list over
```

Output lands in `output/` as `NN_<id>.mp4`, numbered in upload order. Each run
remembers which scripts were used (`state.json`), so nothing repeats.

> edge-tts calls the network once per line, so a batch of 10 takes a couple of
> minutes. That's normal.

## Add more backgrounds (optional)

```bash
python3 fetch_backgrounds.py --count 20                     # keyless (Picsum)
python3 fetch_backgrounds.py --pexels-key KEY --query "dark mountains" --count 20
```
Get a free Pexels key at https://www.pexels.com/api/ for themed images.

## Add / edit content

Edit `content.json`. Each item is a list of short spoken `lines` (one caption +
one background per line). Keep 6–8 lines for a ~15–20s video:
```json
{ "id": "m011", "lines": ["First beat.", "Second beat.", "..."] }
```
Change `category_label` (top text) and `cta` (bottom text) to rebrand, or swap in
a whole new niche (stoicism, fitness, facts).

## Daily routine

1. Run `./make.sh` (or pre-make a batch).
2. Watch the `.mp4` once — quick quality check.
3. Upload to YouTube as a **Short**: quote + hashtags in the title
   (`#motivation #shorts #discipline`), post at a consistent time.
4. Repeat every day. Consistency is the whole game.

## Monetization reality

- Shorts pay ~$0.01–$0.06 per 1,000 views. Real income = volume + consistency,
  then affiliate links / your own product later.
- Monetization needs **10M Shorts views in 90 days** (or 1k subs + 4k watch
  hours). Expect **months**, not days.
- Vary quotes, voices, and backgrounds so the channel reads as real, not spam —
  YouTube demonetizes mass-produced identical content.

## Config knobs (top of `make_video.py`)

- `EDGE_VOICE` — try `en-US-GuyNeural`, `en-US-ChristopherNeural`, `en-GB-RyanNeural`.
- `EDGE_RATE` — delivery speed (e.g. `-9%`).
- `GAP_SECONDS` — pause between lines (also controls length).
