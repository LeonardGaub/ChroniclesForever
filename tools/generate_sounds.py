"""Renders the desktop app's built-in sounds into desktop/forever_chronicle/ui/assets/sounds.

All sounds are synthesized here (no recorded or third-party audio), so they can live in the repo:

- click.wav, screenshot.wav, level_up.wav, event.wav, death.wav: short effects (QSoundEffect plays WAV only)
- cinematic_theme.ogg: an original orchestral loop for cinematic mode (strings, harp, flute, horn; hall reverb).
  The reverb tail is folded back onto the start, so the file loops without a seam.

Needs numpy and soundfile (dev only, not used by the app): pip install numpy soundfile
Run: desktop/.venv/Scripts/python tools/generate_sounds.py [names...]   (e.g. `click`; none: all)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
CLICK_PEAK = 0.50           # the click's level: about 2 dB below the first, hollow version (A-weighted)
OUT = Path(__file__).resolve().parents[1] / "desktop" / "forever_chronicle" / "ui" / "assets" / "sounds"
rng = np.random.default_rng(1004)   # fixed seed: the same files on every run


# -- building blocks -----------------------------------------------------------------------

def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def timeline(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


def envelope(n: int, attack: float, hold: float, release: float) -> np.ndarray:
    """Smooth rise over `attack` s, sustain until `hold` s, then an exponential-ish fall over `release` s."""
    t = np.arange(n) / SR
    rise = np.clip(t / max(attack, 1e-4), 0, 1)
    rise = 0.5 - 0.5 * np.cos(np.pi * rise)
    fall = np.clip((t - hold) / max(release, 1e-4), 0, 1)
    return rise * (1 - fall) ** 2


def lowpass(x: np.ndarray, cutoff: float, order: int = 1) -> np.ndarray:
    """Zero-phase low-pass in the frequency domain (works on mono or stereo along axis 0)."""
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1 / SR)
    gain = 1 / np.sqrt(1 + (f / cutoff) ** (2 * order))
    if x.ndim == 2:
        gain = gain[:, None]
    return np.fft.irfft(spec * gain, n=x.shape[0], axis=0)


def highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - lowpass(x, cutoff)


def vibrato_phase(freq: float, n: int, rate: float, depth: float, delay: float) -> np.ndarray:
    t = np.arange(n) / SR
    amount = depth * np.clip((t - delay) / 0.6, 0, 1)
    inst = freq * (1 + amount * np.sin(2 * np.pi * rate * t + rng.uniform(0, 6.28)))
    return 2 * np.pi * np.cumsum(inst) / SR


def pan(mono: np.ndarray, position: float) -> np.ndarray:
    """position -1 (left) .. 1 (right), equal power."""
    angle = (position + 1) * np.pi / 4
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1)


def mix_into(track: np.ndarray, sound: np.ndarray, at: float) -> None:
    start = int(at * SR)
    end = min(track.shape[0], start + sound.shape[0])
    if end > start:
        track[start:end] += sound[:end - start]


def reverb(x: np.ndarray, seconds: float = 3.0, wet: float = 0.3, predelay: float = 0.02,
           tone: float = 5000) -> np.ndarray:
    """Hall reverb by convolution with decaying, darkened stereo noise. Returns the dry/wet mix with the tail."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    decay = np.exp(-6.9 * t / seconds)
    ir = rng.standard_normal((n, 2)) * decay[:, None]
    ir = lowpass(ir, tone)
    ir[:int(predelay * SR)] = 0
    ir /= np.sqrt(np.sum(ir ** 2, axis=0, keepdims=True))
    size = 1 << int(np.ceil(np.log2(x.shape[0] + n)))
    out = np.zeros((x.shape[0] + n, 2))
    for ch in range(2):
        src = x[:, ch] if x.ndim == 2 else x
        out[:, ch] = np.fft.irfft(np.fft.rfft(src, size) * np.fft.rfft(ir[:, ch], size), size)[:out.shape[0]]
    dry = np.zeros_like(out)
    dry[:x.shape[0]] = x if x.ndim == 2 else np.stack([x, x], axis=1)
    return dry * (1 - wet) + out * wet * 2.2


def normalize(x: np.ndarray, peak: float) -> np.ndarray:
    return x * (peak / max(1e-9, np.max(np.abs(x))))


def fade_edges(x: np.ndarray, fade_in: float = 0.002, fade_out: float = 0.05) -> np.ndarray:
    a, b = int(fade_in * SR), int(fade_out * SR)
    if a:
        x[:a] *= np.linspace(0, 1, a)[:, None] if x.ndim == 2 else np.linspace(0, 1, a)
    if b:
        x[-b:] *= np.linspace(1, 0, b)[:, None] if x.ndim == 2 else np.linspace(1, 0, b)
    return x


# -- instruments ---------------------------------------------------------------------------

def strings(midi: float, seconds: float, attack: float = 1.4, release: float = 2.0) -> np.ndarray:
    """Ensemble strings: three detuned bowed voices (band-limited saw), slow bow, gentle vibrato."""
    n = int((seconds + release) * SR)
    freq = hz(midi)
    out = np.zeros((n, 2))
    for detune, position in ((-7, -0.6), (0, 0.0), (6, 0.6)):
        phase = vibrato_phase(freq * 2 ** (detune / 1200), n, 4.6 + rng.uniform(-0.4, 0.4), 0.0025, 0.4)
        voice = np.zeros(n)
        for k in range(1, 14):
            if freq * k > 9000:
                break
            voice += np.sin(k * phase + rng.uniform(0, 6.28)) / k * np.exp(-0.16 * k)
        out += pan(voice, position)
    out = lowpass(out, 2600 + freq)
    return out * envelope(n, attack, seconds, release)[:, None] / 3


def harp(midi: float, ring: float = 2.8) -> np.ndarray:
    """Plucked string: harmonics that die faster the higher they are, and a soft finger noise."""
    n = int(ring * SR)
    t = np.arange(n) / SR
    freq = hz(midi)
    tone = np.zeros(n)
    for k in range(1, 10):
        if freq * k > 12000:
            break
        tone += np.sin(2 * np.pi * freq * k * t * (1 + 0.0004 * k * k)) / k ** 1.6 * np.exp(-(1.4 + 1.1 * k) * t)
    pluck = lowpass(rng.standard_normal(n) * np.exp(-t * 90), 3000) * 0.08
    return (tone + pluck) * envelope(n, 0.004, ring, ring * 0.25)


def flute(midi: float, seconds: float) -> np.ndarray:
    n = int((seconds + 0.5) * SR)
    phase = vibrato_phase(hz(midi), n, 5.2, 0.004, 0.35)
    tone = np.sin(phase) + 0.22 * np.sin(2 * phase) + 0.07 * np.sin(3 * phase)
    breath = highpass(lowpass(rng.standard_normal(n), 4000), 800) * 0.035
    return (tone + breath) * envelope(n, 0.12, seconds, 0.45)


def horn(midi: float, seconds: float, attack: float = 0.18) -> np.ndarray:
    """French-horn-like: warm harmonics that open up while the note swells."""
    n = int((seconds + 0.6) * SR)
    t = np.arange(n) / SR
    phase = vibrato_phase(hz(midi), n, 4.8, 0.002, 0.5)
    brightness = 0.35 + 0.65 * np.clip(t / (attack * 3), 0, 1)
    tone = np.zeros(n)
    for k in range(1, 10):
        tone += np.sin(k * phase) / k ** 1.2 * brightness ** (k - 1)
    tone = lowpass(tone, 1400 + hz(midi))
    return tone * envelope(n, attack, seconds, 0.55) * 0.6


def bell(midi: float, ring: float = 2.5, bright: float = 1.0) -> np.ndarray:
    """Glockenspiel/chime: inharmonic partials, fast attack."""
    n = int(ring * SR)
    t = np.arange(n) / SR
    freq = hz(midi)
    tone = np.zeros(n)
    for ratio, amp, decay in ((1, 1.0, 1.3), (2.0, 0.45 * bright, 2.0), (2.76, 0.35 * bright, 2.8),
                              (5.4, 0.2 * bright, 4.5), (8.93, 0.1 * bright, 6.5)):
        if freq * ratio < 16000:
            tone += amp * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-decay * t)
    return tone * envelope(n, 0.002, ring, ring * 0.3)


def noise_burst(seconds: float, decay: float, low: float, high: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    return highpass(lowpass(rng.standard_normal(n), high, 2), low) * np.exp(-decay * t)


# -- short effects -------------------------------------------------------------------------

def click() -> np.ndarray:
    """A short, crisp tick, quiet enough for every button: a bright snap with only a hint of body (a low,
    ringing body sounds hollow)."""
    t = timeline(0.07)                           # the noise keeps this length: later sounds draw the same noise
    snap = (0.5 * np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 260)
            + 0.25 * np.sin(2 * np.pi * 4100 * t) * np.exp(-t * 450)
            + 0.15 * np.sin(2 * np.pi * 1100 * t) * np.exp(-t * 300))
    tick = noise_burst(0.07, 900, 2500, 10000) * 0.7
    out = highpass(snap + tick, 700)[:int(0.035 * SR)]
    return fade_edges(normalize(out, CLICK_PEAK), 0.0003, 0.008)


def shutter() -> np.ndarray:
    """Camera shutter: the blade (a bright snap) and the mirror coming back (a duller one)."""
    out = np.zeros(int(0.32 * SR))
    for at, high, level, thunk in ((0.0, 9000, 1.0, 0.5), (0.085, 5500, 0.75, 0.35)):
        snap = noise_burst(0.09, 140, 1200, high) * level
        t = timeline(0.09)
        snap = snap + thunk * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 70)
        mix_into(out, snap, at)
    stereo = reverb(out, 0.6, wet=0.12, tone=6000)
    return fade_edges(normalize(stereo, 0.7), 0.0005, 0.05)


def level_up() -> np.ndarray:
    """Golden fanfare: a quick rising chime arpeggio into a shimmering D major chord with horns and strings."""
    out = np.zeros((int(3.6 * SR), 2))
    for i, note in enumerate((74, 78, 81, 86, 90)):
        mix_into(out, pan(bell(note, 2.6, 0.9), -0.4 + i * 0.2) * 0.5, i * 0.075)
    for note in (62, 66, 69, 74):
        mix_into(out, pan(horn(note, 1.7, attack=0.12), 0) * 0.28, 0.3)
    for note in (50, 62, 66, 69, 74, 78):
        mix_into(out, strings(note, 1.4, attack=0.35, release=1.2) * 0.35, 0.3)
    t = timeline(2.6)   # sparkle: a fast high tremolo that fades
    sparkle = sum(np.sin(2 * np.pi * hz(m) * t) for m in (98, 102, 105)) * (0.5 + 0.5 * np.sin(2 * np.pi * 14 * t))
    mix_into(out, pan(sparkle * np.exp(-t * 1.6) * envelope(len(t), 0.25, 2.6, 0.5) * 0.06, 0.2), 0.35)
    wet = reverb(out, 2.4, wet=0.3)
    return fade_edges(normalize(wet[:int(4.4 * SR)], 0.85), 0.001, 0.3)


def event_chime() -> np.ndarray:
    """Achievement-style alert: two bright bells, the second higher, over a soft chord."""
    out = np.zeros((int(1.8 * SR), 2))
    mix_into(out, pan(bell(81, 1.6), -0.2) * 0.6, 0.0)
    mix_into(out, pan(bell(88, 1.6), 0.2) * 0.6, 0.11)
    for note in (69, 73, 76):
        mix_into(out, pan(harp(note, 1.6), 0) * 0.25, 0.11)
    wet = reverb(out, 1.6, wet=0.25)
    return fade_edges(normalize(wet[:int(2.4 * SR)], 0.7), 0.001, 0.2)


def death_toll() -> np.ndarray:
    """A low, sad bell over a dark minor chord."""
    out = np.zeros((int(3.2 * SR), 2))
    mix_into(out, pan(bell(50, 3.0, 0.6), 0) * 0.7, 0.0)
    mix_into(out, pan(bell(53, 3.0, 0.5), 0.1) * 0.35, 0.05)
    for note in (38, 50, 53, 57):
        mix_into(out, strings(note, 1.6, attack=0.4, release=1.4) * 0.3, 0.05)
    wet = reverb(out, 2.6, wet=0.3, tone=3500)
    return fade_edges(normalize(wet[:int(4.0 * SR)], 0.7), 0.001, 0.4)


# -- cinematic theme -----------------------------------------------------------------------

BPM = 70
BEAT = 60 / BPM
BAR = 4 * BEAT
CHORDS = {   # pitch classes, root first
    "D": (2, 6, 9), "Bm": (11, 2, 6), "G": (7, 11, 2), "A": (9, 1, 4), "F#m": (6, 9, 1),
    "Em": (4, 7, 11, 2), "Asus": (9, 2, 4),
}
# One entry per bar; a tuple splits the bar in two halves. The last bar leads back to the first.
PROGRESSION = [
    "D", "Bm", "G", "A", "D", "F#m", "G", ("Asus", "A"),          # intro: strings and harp
    "Bm", "G", "D", "A", "Bm", "G", "Em", "A",                    # flute enters
    "D", "Bm", "G", "A", "D", "F#m", "G", "A",                    # flute, higher
    "G", "A", "F#m", "Bm", "G", "A", "D", ("Asus", "A"),          # horn answers, back home
]
# (bar, beat, midi, beats)
FLUTE = [
    (8, 0, 78, 3), (8, 3, 76, 1), (9, 0, 74, 2), (9, 2, 71, 1), (9, 3, 74, 1), (10, 0, 81, 3), (10, 3, 78, 1),
    (11, 0, 76, 4), (12, 0, 78, 2), (12, 2, 83, 2), (13, 0, 81, 1), (13, 1, 79, 1), (13, 2, 74, 2),
    (14, 0, 76, 1), (14, 1, 79, 1), (14, 2, 83, 2), (15, 0, 81, 2), (15, 2, 79, 1), (15, 3, 76, 1),
    (16, 0, 78, 2), (16, 2, 81, 2), (17, 0, 86, 2), (17, 2, 83, 1), (17, 3, 81, 1), (18, 0, 83, 3), (18, 3, 79, 1),
    (19, 0, 81, 2), (19, 2, 76, 2), (20, 0, 78, 1), (20, 1, 76, 1), (20, 2, 74, 2), (21, 0, 73, 2), (21, 2, 78, 1),
    (21, 3, 81, 1), (22, 0, 79, 2), (22, 2, 83, 1), (22, 3, 86, 1), (23, 0, 85, 3), (23, 3, 81, 1),
]
HORN = [
    (24, 0, 71, 3), (24, 3, 69, 1), (25, 0, 73, 2), (25, 2, 76, 2), (26, 0, 69, 3), (26, 3, 73, 1),
    (27, 0, 74, 2), (27, 2, 71, 2), (28, 0, 67, 1), (28, 1, 71, 1), (28, 2, 74, 2), (29, 0, 76, 2), (29, 2, 73, 2),
    (30, 0, 74, 4),
]


def voiced(pcs, low: int, count: int) -> list[int]:
    """The chord's notes from `low` upwards (closest voicing, which leads smoothly from chord to chord)."""
    notes = [m for m in range(low, low + 36) if m % 12 in pcs]
    return notes[:count]


def chord_spans():
    """(start seconds, length seconds, pitch classes) for every chord."""
    for bar, entry in enumerate(PROGRESSION):
        names = entry if isinstance(entry, tuple) else (entry,)
        length = BAR / len(names)
        for i, name in enumerate(names):
            yield bar * BAR + i * length, length, CHORDS[name]


def cinematic_theme() -> np.ndarray:
    song = len(PROGRESSION) * BAR
    tail = 4.0
    out = np.zeros((int((song + tail) * SR), 2))
    for start, length, pcs in chord_spans():
        bar = int(start // BAR)
        swell = 0.75 if bar < 8 else 1.0
        mix_into(out, strings(voiced(pcs[:1], 38, 1)[0], length + 0.15) * 0.34 * swell, start)       # basses
        for note in voiced(pcs[:3], 55, 3):                                                          # violas/violins
            mix_into(out, strings(note, length + 0.15) * 0.2 * swell, start)
        if bar >= 16:
            mix_into(out, strings(voiced(pcs[:3], 67, 2)[1], length + 0.15) * 0.1, start)          # high violins
        arp = voiced(pcs[:3], 50, 5)
        steps = int(round(length / (BEAT / 2)))
        for i in range(steps):
            note = arp[(0, 1, 2, 3, 4, 3, 2, 1)[i % 8]]
            accent = 1.0 if i % 4 == 0 else 0.75
            mix_into(out, pan(harp(note), -0.35) * 0.16 * accent * swell, start + i * BEAT / 2)
    for bar, beat, note, beats in FLUTE:
        mix_into(out, pan(flute(note, beats * BEAT * 0.97), 0.15) * 0.17, bar * BAR + beat * BEAT)
    for bar, beat, note, beats in HORN:
        mix_into(out, pan(horn(note, beats * BEAT * 0.97), -0.1) * 0.3, bar * BAR + beat * BEAT)
    wet = reverb(out, 3.4, wet=0.34, tone=4200)
    loop = wet[:int(song * SR)].copy()
    rest = wet[int(song * SR):]
    loop[:rest.shape[0]] += rest                        # the tail rings on into the start: a seamless loop
    loop = np.tanh(normalize(loop, 0.9) * 1.1) / np.tanh(1.1) * 0.85
    return loop


def main(only: list[str]) -> None:
    """Renders everything, or only the named sounds (e.g. `click`), leaving the other files as they are."""
    OUT.mkdir(parents=True, exist_ok=True)
    makers = {"click": click, "screenshot": shutter, "level_up": level_up, "event": event_chime,
              "death": death_toll}
    for name, make in makers.items():
        data = make()                            # always made, in order: every sound draws the same noise
        if only and name not in only:
            continue
        sf.write(OUT / f"{name}.wav", data, SR, subtype="PCM_16")
        print(f"{name}.wav  {data.shape[0] / SR:.2f} s")
    if only and "cinematic_theme" not in only:
        return
    theme = cinematic_theme()
    # Written in blocks: libsndfile's Vorbis encoder overflows the stack on one large write.
    with sf.SoundFile(OUT / "cinematic_theme.ogg", "w", SR, 2, format="OGG", subtype="VORBIS") as f:
        for i in range(0, theme.shape[0], SR):
            f.write(theme[i:i + SR])
    print(f"cinematic_theme.ogg  {theme.shape[0] / SR:.1f} s")


if __name__ == "__main__":
    main(sys.argv[1:])
