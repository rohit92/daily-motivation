# ⚙️ Mindset Refuel — The Automation System & Workflow

A defined, repeatable pipeline. Claude's tools do the making and the analysis;
you do only what a human must: **upload, publish, engage.**

```
                        ┌───────────────────────────────────────────┐
                        │            THE CONTROL ROOM                │
                        │        ./dashboard.sh → localhost:5050     │
                        └───────────────────────────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        ▼                                 ▼                                 ▼
  ┌───────────┐                    ┌───────────┐                     ┌───────────┐
  │  ANALYZE  │  ── informs ──▶    │  CREATE   │   ── produces ──▶   │  PUBLISH  │
  │ (auto)    │                    │ (auto)    │                     │  (you)    │
  └───────────┘                    └───────────┘                     └───────────┘
  trend_scan.py                    ai_brain.py / script_composer.py   upload to YouTube
  channel_stats.py  ◀── your        make_video.py  (voice+bg+music)   + Instagram Reels
  ai_brain --analyze    account      metadata.py   (titles/desc/IG)   mark uploaded
```

## The loop, step by step

**1. ANALYZE — the system studies the niche and your own channel (automatic)**
- `trend_scan.py` → what's trending in motivation this week (via YouTube API).
- `channel_stats.py` → pulls *your* real view counts from your channel into the
  library (dashboard: **Sync my stats**). This is the self-analysis from your account.
- `ai_brain.py --analyze` → Claude reads both and tells you what to make next
  (dashboard: **AI Coach**). Free offline summary if no Anthropic key.

**2. CREATE — the system builds finished, on-trend videos (automatic)**
Press **Generate** once. Behind it:
- `ai_brain.py --ensure N` → writes fresh scripts (AI, trend- + performance-aware)
  or falls back to the 500-combo offline bank. Never runs dry.
- `make_video.py` → natural voice + changing backgrounds + captions + soft music.
- `metadata.py` → title, description, hashtags, and IG caption for each, tracked
  in `library.json`.

**3. PUBLISH — the part only you can do (manual, ~10 min/day)**
- Open the library, copy the title/description/IG caption, upload the `.mp4` to
  YouTube (Short) + Instagram Reels, click **mark uploaded**.
- Reply to comments. That's it.

## What is automated vs. yours

| Automated by the system | Only you can do |
|---|---|
| Trend scanning | Uploading / publishing |
| Reading your channel's real stats | Replying to comments |
| Writing scripts (AI or offline) | Approving spend / accounts |
| Making the videos + music | Sharing in communities |
| Writing titles/descriptions/captions | Final creative calls |
| Ranking your winners, coaching | — |

## Cadence (defined)

- **Daily** (~10 min): upload today's video (dashboard shows which), engage.
- **Weekly** (~15 min): **Sync my stats** → **AI Coach** → **Generate** next 7.
- **Monthly** (~5 min): `python3 doctor.py` health check.

## Turning on the AI brain (optional, ~cents/week)

1. Get a key at https://console.anthropic.com
2. `export ANTHROPIC_API_KEY=sk-ant-...`  (or save to `assets/anthropic_api_key.txt`)
3. In `config.json` set `"ai_scripts": true` to have Generate write with AI.
   The dashboard header shows **AI brain: ON** when it's active.

Everything works without it — the AI brain only makes scripts more original and
adds the coaching. Model is set in `config.json` (`ai_model`).
