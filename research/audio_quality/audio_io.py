"""Read mono/stereo WAV without hidden normalization or sample rate conversion."""

from array import array
from dataclasses import dataclass
import math
from pathlib import Path
import struct
import sys
from typing import Sequence, Tuple


@dataclass
class Audio:
    rate: int
    channels: Tuple[Sequence[float], ...]

    def __post_init__(self):
        if self.rate <= 0 or len(self.channels) not in (1, 2):
            raise ValueError("audio requires a positive sample rate and one or two channels")
        if not self.frames or any(len(channel) != self.frames for channel in self.channels):
            raise ValueError("audio channels must have the same nonzero frame count")

    @property
    def frames(self):
        return len(self.channels[0])


def read_wav(path):
    raw = Path(path).read_bytes()
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"{path}: expected little-endian RIFF/WAVE")
    end = 8 + struct.unpack_from("<I", raw, 4)[0]
    if end > len(raw):
        raise ValueError(f"{path}: truncated WAV container")
    offset = 12
    fmt = samples = None
    while offset + 8 <= end:
        tag, size = struct.unpack_from("<4sI", raw, offset)
        offset += 8
        if offset + size > end:
            raise ValueError(f"{path}: truncated WAV chunk")
        if tag == b"fmt ":
            fmt = raw[offset:offset + size]
        elif tag == b"data":
            samples = raw[offset:offset + size]
        offset += size + (size % 2)
    if fmt is None or len(fmt) < 16 or not samples:
        raise ValueError(f"{path}: missing WAV format or samples")

    encoding, count, rate, _, block_size, bits = struct.unpack_from("<HHIIHH", fmt)
    if encoding == 0xFFFE and len(fmt) >= 40:
        valid_bits = struct.unpack_from("<H", fmt, 18)[0]
        standard_subtype = fmt[26:40] == bytes.fromhex("000000001000800000aa00389b71")
        if standard_subtype and valid_bits in (0, bits):
            encoding = struct.unpack_from("<H", fmt, 24)[0]
    if count not in (1, 2) or block_size != count * (bits // 8) or not block_size:
        raise ValueError(f"{path}: expected mono or stereo WAV with packed channel samples")
    if len(samples) % block_size:
        raise ValueError(f"{path}: partial WAV frame")

    if (encoding, bits) == (3, 32):
        numbers = array("f", samples)
        if sys.byteorder != "little":
            numbers.byteswap()
        if not all(math.isfinite(value) for value in numbers):
            raise ValueError(f"{path}: non-finite WAV sample")
    elif encoding == 1 and bits in (16, 24, 32):
        scale = 1 << (bits - 1)
        if bits == 24:
            integers = (
                int.from_bytes(samples[i:i + 3], "little", signed=True)
                for i in range(0, len(samples), 3)
            )
        else:
            template = "<h" if bits == 16 else "<i"
            integers = (number for (number,) in struct.iter_unpack(template, samples))
        numbers = array("d", (number / scale for number in integers))
    else:
        raise ValueError(f"{path}: expected PCM16/24/32 or IEEE float32 WAV")
    return Audio(rate, tuple(numbers[i::count] for i in range(count)))


def _chunk(tag, payload):
    return tag + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) % 2 else b"")


def write_wav(path, audio, *, pcm24=False):
    bits = 24 if pcm24 else 32
    encoding = 1 if pcm24 else 3
    count = len(audio.channels)
    block_size = count * (bits // 8)
    fmt = struct.pack("<HHIIHH", encoding, count, audio.rate, audio.rate * block_size, block_size, bits)
    data = zip(*audio.channels)
    if pcm24:
        amplitude = 1 << 23
        payload = bytearray()
        for frame in data:
            for value in frame:
                sample = round(value * amplitude)
                if sample < -amplitude or sample >= amplitude:
                    raise ValueError("PCM24 export would clip")
                payload.extend(sample.to_bytes(3, "little", signed=True))
        fact = b""
    else:
        values = array("f", (value for frame in data for value in frame))
        if sys.byteorder != "little":
            values.byteswap()
        payload = values.tobytes()
        fact = _chunk(b"fact", struct.pack("<I", audio.frames))
    riff = b"WAVE" + _chunk(b"fmt ", fmt) + fact + _chunk(b"data", bytes(payload))
    Path(path).write_bytes(b"RIFF" + struct.pack("<I", len(riff)) + riff)
