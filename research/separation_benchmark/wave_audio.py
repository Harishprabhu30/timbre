"""Read uncompressed little-endian RIFF/WAVE samples into binary64."""

from array import array
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import struct
import sys


@dataclass(frozen=True)
class Audio:
    sample_rate: int
    channels: int
    samples: array

    @property
    def frames(self):
        return len(self.samples) // self.channels


def read_wave(path: Path) -> Audio:
    with path.open("rb") as source:
        header = source.read(12)
        if len(header) != 12:
            raise ValueError("truncated WAVE header")
        container, size, kind = struct.unpack("<4sI4s", header)
        if (container, kind) != (b"RIFF", b"WAVE"):
            raise ValueError("expected a little-endian RIFF/WAVE file")
        limit = size + 8
        if limit > source.seek(0, 2):
            raise ValueError("truncated RIFF container")

        source.seek(12)
        fmt = None
        fmt_size = 0
        data = None
        while source.tell() < limit:
            header = source.read(8)
            if len(header) != 8:
                raise ValueError("truncated RIFF chunk header")
            kind, size = struct.unpack("<4sI", header)
            start = source.tell()
            end = start + size + (size % 2)
            if end > limit:
                raise ValueError("RIFF chunk extends past the container")
            if kind == b"fmt ":
                if fmt is not None:
                    raise ValueError("multiple format chunks")
                fmt = source.read(min(size, 40))
                fmt_size = size
            elif kind == b"data":
                if data is not None:
                    raise ValueError("multiple data chunks")
                data = (start, size)
            source.seek(end)

        if fmt is None or len(fmt) < 16 or data is None:
            raise ValueError("missing WAVE format or sample data")
        tag, channels, rate, byte_rate, frame_bytes, bits = struct.unpack_from("<HHIIHH", fmt)
        if tag == 0xFFFE:
            tag = extensible_tag(fmt, fmt_size, channels, bits)
        sample_format = {(1, 16): "h", (1, 24): None, (1, 32): "i", (3, 32): "f", (3, 64): "d"}
        if (tag, bits) not in sample_format:
            raise ValueError("expected PCM16/24/32 or IEEE float32/64 WAV")
        if channels != 2:
            raise ValueError(f"expected two stereo channels, got {channels}")
        if rate == 0 or frame_bytes != channels * (bits // 8) or byte_rate != rate * frame_bytes:
            raise ValueError("invalid WAVE format sizes or sample rate")
        offset, length = data
        if length == 0 or length % frame_bytes:
            raise ValueError("empty data chunk or incomplete sample frame")
        source.seek(offset)
        raw = source.read(length)
        if len(raw) != length:
            raise ValueError("truncated WAVE data")

    samples = decode_samples(raw, sample_format[tag, bits], bits, tag)
    if not all(map(isfinite, samples)):
        raise ValueError("WAVE audio contains non-finite samples")
    return Audio(rate, channels, samples)


def extensible_tag(fmt, fmt_size, channels, bits):
    if len(fmt) < 40:
        raise ValueError("incomplete extensible WAVE format")
    extra_bytes, valid_bits, channel_mask, tag, tail = struct.unpack_from("<HHII12s", fmt, 16)
    if (
        extra_bytes < 22
        or extra_bytes + 18 > fmt_size
        or not 0 < valid_bits <= bits
        or (tag == 3 and valid_bits != bits)
        or tail != bytes.fromhex("00001000800000aa00389b71")
    ):
        raise ValueError("unsupported extensible WAVE format")
    if channels == 2 and channel_mask not in (0, 3):
        raise ValueError("expected stereo front-left/front-right channel mapping")
    return tag


def decode_samples(raw, typecode, bits, tag):
    if typecode is None:
        scale = 2 ** (bits - 1)
        view = memoryview(raw)
        return array("d", (
            int.from_bytes(view[i:i + 3], "little", signed=True) / scale
            for i in range(0, len(raw), 3)
        ))

    decoded = array(typecode)
    decoded.frombytes(raw)
    if sys.byteorder == "big":
        decoded.byteswap()
    if tag == 1:
        return array("d", (value / 2 ** (bits - 1) for value in decoded))
    return decoded if typecode == "d" else array("d", decoded)
