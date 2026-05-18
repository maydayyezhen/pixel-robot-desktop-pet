from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SFX_DIR = ROOT / "assets" / "sfx"
SAMPLE_RATE = 44100


def envelope(sample_index: int, total_samples: int) -> float:
    attack = max(1, int(total_samples * 0.08))
    release = max(1, int(total_samples * 0.24))
    if sample_index < attack:
        return sample_index / attack
    if sample_index > total_samples - release:
        return max(0.0, (total_samples - sample_index) / release)
    return 1.0


def square_sample(freq: float, t: float) -> float:
    return 1.0 if math.sin(math.tau * freq * t) >= 0 else -1.0


def tone(freq: float, duration: float, volume: float = 0.22) -> list[int]:
    count = int(SAMPLE_RATE * duration)
    samples: list[int] = []
    for i in range(count):
        t = i / SAMPLE_RATE
        value = square_sample(freq, t) * envelope(i, count) * volume
        samples.append(int(value * 32767))
    return samples


def slide(start: float, end: float, duration: float, volume: float = 0.22) -> list[int]:
    count = int(SAMPLE_RATE * duration)
    samples: list[int] = []
    phase = 0.0
    for i in range(count):
        progress = i / max(1, count - 1)
        freq = start + (end - start) * progress
        phase += math.tau * freq / SAMPLE_RATE
        value = (1.0 if math.sin(phase) >= 0 else -1.0) * envelope(i, count) * volume
        samples.append(int(value * 32767))
    return samples


def silence(duration: float) -> list[int]:
    return [0] * int(SAMPLE_RATE * duration)


def write_wav(path: Path, samples: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


def make_all() -> None:
    sounds = {
        "click.wav": tone(880, 0.035) + tone(1320, 0.055, 0.18),
        "drop.wav": slide(360, 120, 0.12, 0.24) + silence(0.025) + tone(160, 0.045, 0.16),
        "sleep.wav": tone(520, 0.06, 0.17) + silence(0.02) + tone(390, 0.07, 0.15) + silence(0.02) + tone(260, 0.09, 0.13),
        "wake.wav": tone(420, 0.045, 0.15) + tone(760, 0.045, 0.18) + tone(1180, 0.065, 0.20),
        "resize.wav": slide(620, 980, 0.08, 0.16),
        "toggle.wav": tone(700, 0.04, 0.13) + silence(0.015) + tone(700, 0.04, 0.13),
        "alarm.wav": tone(1040, 0.08, 0.18) + silence(0.04) + tone(1320, 0.08, 0.18) + silence(0.08) + tone(1040, 0.07, 0.16),
    }
    for filename, samples in sounds.items():
        write_wav(SFX_DIR / filename, samples)
        print(SFX_DIR / filename)


if __name__ == "__main__":
    make_all()
