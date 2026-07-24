#!/usr/bin/env python3
"""
make_music.py — generate soft, copyright-safe ambient background beds.

These are synthesized from scratch (pure sine chords), so there is zero
copyright/Content-ID risk. They're meant to sit quietly UNDER the voice.
Output: assets/music/bed_*.wav  (make_video.py mixes one in automatically).

You can also drop your own tracks from the YouTube Audio Library into
assets/music/ — any .mp3/.wav there gets used too.

  python3 make_music.py
"""

import os
import wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MUSIC_DIR = os.path.join(HERE, "assets", "music")
SR = 44100
DUR = 40.0  # longer than any Short, so it never loops mid-video

# gentle chords (root, third, fifth [+ soft octave]) in Hz
BEDS = {
    "calm":   [110.0, 164.81, 220.0, 329.63],   # A minor-ish, warm
    "uplift": [130.81, 164.81, 196.0, 392.0],    # C major, hopeful
    "deep":   [98.0, 146.83, 220.0, 293.66],     # G/D, cinematic low
}


def bed(freqs):
    t = np.linspace(0, DUR, int(SR * DUR), endpoint=False)
    sig = np.zeros_like(t)
    for k, f in enumerate(freqs):
        # higher partials quieter; tiny detune for a warm chorus feel
        amp = 1.0 / (k + 1.4)
        sig += amp * np.sin(2 * np.pi * f * t)
        sig += 0.5 * amp * np.sin(2 * np.pi * (f * 1.003) * t)
    # slow volume swell (breathing pad)
    lfo = 0.65 + 0.35 * np.sin(2 * np.pi * 0.05 * t)
    sig *= lfo
    # 2s fade in / out
    fade = int(SR * 2)
    env = np.ones_like(sig)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    sig *= env
    # normalize
    sig = sig / (np.max(np.abs(sig)) + 1e-9) * 0.85
    return (sig * 32767).astype("<i2")


def save(path, samples):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(samples.tobytes())


if __name__ == "__main__":
    os.makedirs(MUSIC_DIR, exist_ok=True)
    for name, freqs in BEDS.items():
        p = os.path.join(MUSIC_DIR, f"bed_{name}.wav")
        save(p, bed(freqs))
        print("wrote", os.path.relpath(p, HERE))
    print("Done. make_video.py will now mix these in quietly.")
