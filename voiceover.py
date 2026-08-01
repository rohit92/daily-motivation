#!/usr/bin/env python3
"""Turn one long voice recording into per-line narration for the Shorts.

Why this exists
---------------
edge-tts costs nothing and needs no effort, and that is exactly the problem:
every faceless channel uses it, so the voice carries no signal that a person
made the video. Speak Fluent teaches spoken English — a synthetic voice
teaching pronunciation is also a straight contradiction.

The constraint is the creator's time. He is a student in placement season, so
the workflow is built around ONE sitting a week, not a daily chore:

    python3 voiceover.py --channel education --sheet 7     # -> a read-aloud sheet
    ... record all of it in one file, on a phone, in ~15 minutes ...
    python3 voiceover.py --channel education --ingest take.m4a

Everything after that is automatic.

How the recording is cut up
---------------------------
Two strategies, best first:

1. ALIGN (faster-whisper). Transcribe the take with word timestamps and match
   the transcript against the script lines we know were supposed to be read.
   This survives uneven pauses, throat-clearing and retakes, and it VERIFIES
   that the words spoken are the words scripted — a silence split cannot tell
   the difference between a correct take and a fluent misreading.

2. SPLIT (ffmpeg silencedetect). No model needed. Requires the segment count to
   match the line count exactly, and word timings are approximated from word
   length. Used when the model is unavailable (it is a one-off download and the
   college network is proxied).

Both refuse to write a partial result. A misaligned take that renders anyway
would put the wrong audio under the wrong caption on a live upload, which is
worse than a failed run — so a low-confidence match is a hard error naming the
line it could not find.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))

# Whisper's smallest English model. The transcript is only ever compared against
# text we already have, so a bigger model buys accuracy we do not need.
WHISPER_MODEL = os.environ.get("VOICEOVER_WHISPER_MODEL", "base.en")

# Below this word-overlap ratio a line is treated as not found rather than
# guessed at. 0.62 accepts an ordinary misread word or a dropped "the"; it
# rejects a line that was skipped entirely.
MATCH_MIN = 0.62

# How far ahead of the cursor to search for the next line, in transcript words.
# Generous enough to skip an aside or a false start, short enough that a skipped
# line fails loudly instead of matching something much later in the take.
LOOKAHEAD = 80

SILENCE_DB = "-32dB"          # phone recordings have a noise floor; -50 is too strict
SILENCE_MIN = 0.45            # seconds of quiet that counts as a line break


def paths_for(channel):
    return _paths.paths(channel)


def voice_dir(channel, script_id=None):
    """Where recorded narration lives: <channel>/assets/voice/<script_id>/."""
    P = paths_for(channel)
    base = os.path.join(os.path.dirname(P["content"]), "assets", "voice")
    return os.path.join(base, script_id) if script_id else base


# Pseudo script id for the subscribe line that closes every video. It never
# changes, so it is recorded once and reused for every upload thereafter.
ENDCAP_ID = "_endcap"


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def endcap_line(channel):
    """Must stay word-for-word identical to make_video.ENDCAP_LINE, or the
    alignment will look for a sentence the creator was never asked to read."""
    name = (_paths.channel_meta(channel) or {}).get("name", "this channel")
    return f"Subscribe to {name}. A brand new one drops every single day."


# ----------------------------------------------------------------- the sheet

def unused_items(channel, limit=None):
    """Scripts composed but not yet made into a video, oldest first."""
    P = paths_for(channel)
    content = load(P["content"], {}) or {}
    used = set((load(P["state"], {}) or {}).get("used_ids", []))
    items = [i for i in content.get("items", []) if i["id"] not in used]
    return items[:limit] if limit else items


def write_sheet(channel, count, out_path=None):
    """A read-aloud sheet: every line the take should contain, in order."""
    items = unused_items(channel, count)
    if not items:
        raise SystemExit("No unused scripts to record. Run script_composer.py --ensure first.")

    # The endcap sentence is identical in every video, so it is recorded once
    # and reused forever. Only ask for it while it is still missing.
    if not line_wav(channel, ENDCAP_ID, 0):
        items = items + [{"id": ENDCAP_ID, "lines": [endcap_line(channel)],
                          "theme": "recorded once, reused in every video"}]

    out_path = out_path or os.path.join(voice_dir(channel), "RECORD_THIS.txt")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    total = sum(len(i["lines"]) for i in items)
    L = []
    L.append("=" * 64)
    L.append(f"  RECORDING SHEET — {len(items)} videos, {total} lines")
    L.append("=" * 64)
    L.append("")
    L.append("  Record ALL of it into ONE file. Phone voice memo is fine.")
    L.append("")
    L.append("  1. Quiet room. Phone about a hand's width from your mouth,")
    L.append("     slightly off to the side so your breath doesn't hit it.")
    L.append("  2. Read one line. STOP. Count one-two in your head. Next line.")
    L.append("     That pause is how the lines get cut apart — don't rush it.")
    L.append("  3. Fluffed a line? Just pause and say the whole line again.")
    L.append("     The later take wins. No need to start over.")
    L.append("  4. Speak to one person, not an audience. Slightly slower than")
    L.append("     you think. Your accent is fine — clarity is the only goal.")
    L.append("")
    L.append("  Then: python3 voiceover.py --channel %s --ingest <file>" % channel)
    L.append("")

    for n, it in enumerate(items, 1):
        L.append("-" * 64)
        L.append(f"  VIDEO {n} of {len(items)}   [{it['id']}  ·  {it.get('theme','')}]")
        L.append("-" * 64)
        for line in it["lines"]:
            L.append(f"    {line}")
        L.append("")

    L.append("=" * 64)
    L.append("  End of sheet. Stop recording.")
    L.append("=" * 64)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    # The manifest is what --ingest aligns against: the exact lines, in the
    # exact order, that this take is expected to contain. Without it, ingest
    # would have to re-derive the order and could silently drift if the queue
    # changed between recording and ingesting.
    manifest = {"channel": channel,
                "items": [{"id": i["id"], "lines": i["lines"]} for i in items]}
    with open(os.path.join(voice_dir(channel), "sheet.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return out_path, items, total


# ------------------------------------------------------------- transcription

# Whisper transcribes what it HEARS, and "I'm Rohit" spoken aloud is written
# down as "I am Rohit" about as often as not. On a three-word line that single
# difference drops the word-overlap ratio to 0.57 and the line reads as missing.
# Both sides get expanded to the same canonical form so a contraction can never
# be the reason a correct take is rejected.
_CONTRACTIONS = {
    "i'm": "i am", "i've": "i have", "i'll": "i will", "i'd": "i would",
    "you're": "you are", "you've": "you have", "you'll": "you will",
    "we're": "we are", "we've": "we have", "we'll": "we will",
    "they're": "they are", "they've": "they have", "they'll": "they will",
    "he's": "he is", "she's": "she is", "it's": "it is", "that's": "that is",
    "what's": "what is", "there's": "there is", "here's": "here is",
    "who's": "who is", "let's": "let us", "don't": "do not",
    "doesn't": "does not", "didn't": "did not", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "won't": "will not", "can't": "can not", "cannot": "can not",
    "couldn't": "could not", "wouldn't": "would not", "shouldn't": "should not",
    "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
}


def _norm(text):
    """Words only, lowercased, contractions expanded."""
    out = []
    for w in re.findall(r"[a-z0-9']+", (text or "").lower()):
        # These scripts quote phrases — "Say: 'I'm Rohit.'" — and the quote
        # marks glue themselves onto the word, so "'i'm" never matched the
        # contraction table and the bare closing quote became its own token.
        w = w.strip("'")
        if not w:
            continue
        out.extend(_CONTRACTIONS.get(w, w).split())
    return out


def transcribe(audio):
    """[{word,start,end}] over the whole take, or None if the model is absent."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio, word_timestamps=True, language="en")
        words = []
        for seg in segments:
            for w in (seg.words or []):
                # One spoken word can normalise to several tokens ("I'm" ->
                # "i","am"). Split the word's span across them so timings stay
                # monotonic and the caption highlight doesn't stall.
                tokens = _norm(w.word)
                if not tokens:
                    continue
                step = (w.end - w.start) / len(tokens)
                for k, tok in enumerate(tokens):
                    words.append({"word": tok,
                                  "start": w.start + k * step,
                                  "end": w.start + (k + 1) * step})
        return words or None
    except Exception as e:
        print(f"  ! transcription failed ({str(e)[:80]}), falling back to silence split")
        return None


def _best_window(target, words, cursor):
    """Best-scoring run of transcript words for one expected line.

    Returns (score, start, end) over words[start:end]. Windows are tried around
    the target's own length: a line of eight words is not going to be twenty.
    """
    best = (0.0, cursor, cursor)
    lo = max(1, len(target) - 3)
    hi = len(target) + 4
    limit = min(len(words), cursor + LOOKAHEAD)
    for start in range(cursor, limit):
        for wlen in range(lo, hi):
            end = start + wlen
            if end > len(words):
                break
            cand = [w["word"] for w in words[start:end]]
            score = SequenceMatcher(None, target, cand).ratio()
            if score > best[0]:
                best = (score, start, end)
    return best


def align(items, words):
    """Cut points for every line of every script, or raise on a bad take.

    Retakes: after a line matches, the take is checked for the SAME line again
    immediately after. A creator who fluffs a line and repeats it expects the
    second attempt to be the one that ships, so the later match wins.
    """
    cuts, cursor, failures = [], 0, []
    for it in items:
        for idx, line in enumerate(it["lines"]):
            target = _norm(line)
            if not target:
                continue
            score, start, end = _best_window(target, words, cursor)
            if score < MATCH_MIN:
                failures.append((it["id"], idx, line, score))
                continue
            # prefer a retake sitting directly after this one
            while True:
                s2, st2, en2 = _best_window(target, words, end)
                if s2 >= MATCH_MIN and st2 <= end + 3 and s2 >= score - 0.08:
                    score, start, end = s2, st2, en2
                else:
                    break
            cuts.append({"id": it["id"], "index": idx, "line": line,
                         "score": round(score, 3),
                         "start": words[start]["start"], "end": words[end - 1]["end"],
                         "words": words[start:end]})
            cursor = end

    if failures:
        msg = ["Could not find %d line(s) in the recording:" % len(failures)]
        for sid, idx, line, sc in failures[:8]:
            msg.append(f"   {sid} line {idx + 1} (best match {sc:.2f}): {line}")
        msg.append("")
        msg.append("Nothing was written. Re-record those lines, or record the")
        msg.append("whole sheet again — a partial cut would put the wrong audio")
        msg.append("under the wrong caption.")
        raise SystemExit("\n".join(msg))
    return cuts


# ------------------------------------------------------- silence-split fallback

def silence_cuts(audio, items):
    """Split on silence. Requires an exact segment/line count match."""
    r = subprocess.run(
        ["ffmpeg", "-i", audio, "-af",
         f"silencedetect=noise={SILENCE_DB}:d={SILENCE_MIN}", "-f", "null", "-"],
        capture_output=True, text=True)
    marks = []
    for m in re.finditer(r"silence_(start|end):\s*([0-9.]+)", r.stderr):
        marks.append((m.group(1), float(m.group(2))))

    total = media_duration(audio)
    spans, pos = [], 0.0
    for kind, t in marks:
        if kind == "start":
            if t - pos > 0.25:
                spans.append((pos, t))
        else:
            pos = t
    if total - pos > 0.25:
        spans.append((pos, total))

    expected = [(it["id"], i, ln) for it in items for i, ln in enumerate(it["lines"])]
    if len(spans) != len(expected):
        raise SystemExit(
            f"Silence split found {len(spans)} segments but the sheet has "
            f"{len(expected)} lines.\nRecord with a clear one-second pause "
            f"between lines, or install faster-whisper so the take can be\n"
            f"matched by content instead of by counting:\n"
            f"    pip install faster-whisper")

    return [{"id": sid, "index": idx, "line": ln, "score": None,
             "start": s, "end": e, "words": None}
            for (sid, idx, ln), (s, e) in zip(expected, spans)]


def media_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# ------------------------------------------------------------------ cutting

def cut_segments(audio, cuts, channel, pad=0.12):
    """Write one wav per line, cleaned and loudness-matched.

    highpass strips handling rumble and plosives that a phone picks up; loudnorm
    puts every line at the same perceived level so a batch recorded across two
    sittings doesn't jump in volume mid-video.
    """
    by_script = {}
    for c in cuts:
        by_script.setdefault(c["id"], []).append(c)

    written = 0
    for sid, segs in by_script.items():
        d = voice_dir(channel, sid)
        os.makedirs(d, exist_ok=True)
        timings = {}
        for c in sorted(segs, key=lambda x: x["index"]):
            start = max(0.0, c["start"] - pad)
            dur = (c["end"] + pad) - start
            out = os.path.join(d, f"line_{c['index']:02d}.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                 "-i", audio, "-ac", "2",
                 "-af", "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100",
                 out], check=True, capture_output=True)
            written += 1

            if c["words"]:
                timings[str(c["index"])] = [
                    {"text": w["word"], "start": max(0.0, w["start"] - start),
                     "end": max(0.0, w["end"] - start)} for w in c["words"]]

        meta = {"script_id": sid, "source": os.path.basename(audio),
                "lines": {str(c["index"]): c["line"] for c in segs},
                "scores": {str(c["index"]): c["score"] for c in segs},
                "timings": timings}
        with open(os.path.join(d, "voice.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    return written


# -------------------------------------------------------------- public lookup

def line_wav(channel, script_id, index):
    """Path to recorded narration for one line, or None. Used by make_video."""
    if not script_id:
        return None
    p = os.path.join(voice_dir(channel, script_id), f"line_{index:02d}.wav")
    return p if os.path.exists(p) and os.path.getsize(p) > 0 else None


def line_timings(channel, script_id, index):
    """Word timings for a recorded line in its own timeline, or None."""
    meta = load(os.path.join(voice_dir(channel, script_id), "voice.json"), {}) or {}
    return (meta.get("timings") or {}).get(str(index))


def status(channel):
    items = unused_items(channel)
    rows = []
    for it in items:
        have = sum(1 for i in range(len(it["lines"]))
                   if line_wav(channel, it["id"], i))
        rows.append((it["id"], it.get("theme", ""), have, len(it["lines"])))
    return rows


# ---------------------------------------------------------------------- cli

def do_ingest(channel, audio):
    if not os.path.exists(audio):
        raise SystemExit(f"No such recording: {audio}")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required and was not found on PATH.")

    sheet = load(os.path.join(voice_dir(channel), "sheet.json"), None)
    if not sheet:
        raise SystemExit("No sheet.json — run --sheet first so ingest knows "
                         "which lines this recording is supposed to contain.")
    items = sheet["items"]
    expected = sum(len(i["lines"]) for i in items)
    print(f"  recording : {os.path.basename(audio)} ({media_duration(audio):.0f}s)")
    print(f"  sheet     : {len(items)} scripts, {expected} lines")

    words = transcribe(audio)
    if words:
        print(f"  method    : whisper alignment ({len(words)} words heard)")
        cuts = align(items, words)
        worst = min(c["score"] for c in cuts)
        print(f"  match     : all {len(cuts)} lines found (worst {worst:.2f})")
    else:
        print("  method    : silence split (no whisper model available)")
        cuts = silence_cuts(audio, items)

    n = cut_segments(audio, cuts, channel)
    print(f"  ✓ wrote {n} line(s) of narration for {len({c['id'] for c in cuts})} video(s)")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--channel", default="education")
    ap.add_argument("--sheet", type=int, metavar="N",
                    help="write a read-aloud sheet for the next N scripts")
    ap.add_argument("--out", help="where to write the sheet")
    ap.add_argument("--ingest", metavar="AUDIO",
                    help="cut a recording into per-line narration")
    ap.add_argument("--status", action="store_true",
                    help="show which queued scripts have narration")
    args = ap.parse_args()

    if args.sheet:
        path, items, total = write_sheet(args.channel, args.sheet, args.out)
        print(f"  ✓ {len(items)} scripts, {total} lines → {path}")
        print(f"    Read it top to bottom into one file, then:")
        print(f"    python3 voiceover.py --channel {args.channel} --ingest <file>")
    elif args.ingest:
        do_ingest(args.channel, args.ingest)
    elif args.status:
        rows = status(args.channel)
        if not rows:
            print("  no unused scripts queued")
        for sid, theme, have, need in rows:
            mark = "✓" if have == need else ("·" if have == 0 else "!")
            print(f"  {mark} {sid:6}{theme:18}{have}/{need} lines")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
