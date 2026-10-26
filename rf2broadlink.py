#!/usr/bin/env python3
"""rf2broadlink — turn known 433/315 MHz remote codes into Broadlink RF packets.

Instead of "learning" an RF remote with a Broadlink RM4 Pro (slow frequency sweep,
noisy and very long captures), generate a clean packet from the code itself:

  * a 24-bit Princeton / EV1527 / PT2262-style code (e.g. 0x67AE02), or
  * a Flipper Zero ``.sub`` file (``Protocol: Princeton`` or ``Protocol: RAW``).

The output is a base64 Broadlink packet that Home Assistant can send directly:

    action: remote.send_command
    target: {entity_id: remote.my_rm4_pro}
    data: {command: "b64:<output>"}

No dependencies, Python 3.9+.
"""
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

__version__ = "0.1.0"

# Broadlink pulse unit: 269/8192 ms ≈ 32.84 µs.
TICK_US = 269 / 8192 * 1000

# First byte of a Broadlink RF packet selects the band.
BAND_BYTE = {433: 0xB2, 315: 0xD7}


def _encode_pulse(us: float) -> bytes:
    """Encode one pulse length (µs) in Broadlink units (1 byte, or 0x00 + 2 bytes BE)."""
    ticks = max(1, round(us / TICK_US))
    if ticks < 256:
        return bytes([ticks])
    if ticks > 0xFFFF:
        raise ValueError(f"pulse of {us:.0f} µs is too long for a Broadlink packet")
    return b"\x00" + ticks.to_bytes(2, "big")


def _packet(pulses_us: list[float], band: int, repeat: int = 0) -> bytes:
    """Build a Broadlink RF packet from alternating on/off durations (starting with on)."""
    if band not in BAND_BYTE:
        raise ValueError("Broadlink RF only supports the 433 and 315 MHz bands")
    data = b"".join(_encode_pulse(p) for p in pulses_us)
    return bytes([BAND_BYTE[band], repeat]) + len(data).to_bytes(2, "little") + data


def princeton_pulses(code: int, bits: int = 24, te: int = 350, frames: int = 6,
                     gap_ms: float = 120) -> list[float]:
    """Pulse train for a Princeton/EV1527 code.

    bit 1 = 3·TE on + 1·TE off, bit 0 = 1·TE on + 3·TE off,
    each frame ends with a sync of 1·TE on + 31·TE off.
    The last frame's sync is stretched to ``gap_ms`` so that two packets sent
    back to back are seen by the receiver as two separate button presses.
    """
    if not 0 <= code < 1 << bits:
        raise ValueError(f"code 0x{code:X} does not fit in {bits} bits")
    if frames < 1:
        raise ValueError("frames must be >= 1")
    frame: list[float] = []
    for i in range(bits - 1, -1, -1):
        frame += [3 * te, te] if code >> i & 1 else [te, 3 * te]
    pulses: list[float] = []
    for n in range(frames):
        last = n == frames - 1
        pulses += frame + [te, max(31 * te, gap_ms * 1000) if last else 31 * te]
    return pulses


def raw_pulses(raw: list[int]) -> list[float]:
    """Flipper RAW_Data (signed µs: + on, − off) → alternating on/off list starting with on."""
    out: list[float] = []
    on_expected = True
    for v in raw:
        if v == 0:
            continue
        is_on = v > 0
        if not out and not is_on:
            continue  # leading silence
        if is_on == on_expected:
            out.append(abs(v))
            on_expected = not on_expected
        else:
            out[-1] += abs(v)  # merge consecutive pulses of the same level
    if len(out) % 2:
        out.append(10_000)  # close with an "off" so the pairs stay aligned
    return out


def to_b64(packet: bytes) -> str:
    return base64.b64encode(packet).decode()


def from_princeton(code: int, *, bits: int = 24, te: int = 350, frames: int = 6,
                   gap_ms: float = 120, band: int = 433) -> str:
    return to_b64(_packet(princeton_pulses(code, bits, te, frames, gap_ms), band))


def parse_sub(text: str) -> dict:
    """Parse a Flipper Zero .sub file into a dict (RAW_Data lines are concatenated)."""
    info: dict = {"raw": []}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        if key == "RAW_Data":
            info["raw"] += [int(x) for x in value.split()]
        else:
            info[key] = value
    return info


def _band_from_hz(freq: str | None) -> int:
    if not freq:
        return 433
    mhz = int(freq) / 1e6
    for band in BAND_BYTE:
        if abs(mhz - band) < 2:
            return band
    raise ValueError(f"{mhz:.2f} MHz: Broadlink RF only transmits on 433 or 315 MHz")


def from_sub(text: str, *, frames: int = 6, gap_ms: float = 120, te: int | None = None) -> str:
    info = parse_sub(text)
    band = _band_from_hz(info.get("Frequency"))
    proto = info.get("Protocol", "")
    if proto == "RAW":
        if not info["raw"]:
            raise ValueError("RAW file without RAW_Data")
        return to_b64(_packet(raw_pulses(info["raw"]), band))
    if proto in ("Princeton", "EV1527"):
        bits = int(info.get("Bit", 24))
        code = int(info["Key"].replace(" ", ""), 16)
        return from_princeton(code, bits=bits, te=te or int(info.get("TE", 350)),
                              frames=frames, gap_ms=gap_ms, band=band)
    raise ValueError(f"unsupported protocol {proto!r} (supported: Princeton, EV1527, RAW)")


def decode(b64: str) -> dict:
    """Inspect a Broadlink packet: band byte, repeat byte, pulse count and length."""
    raw = base64.b64decode(b64.removeprefix("b64:"))
    n = int.from_bytes(raw[2:4], "little")
    data, pulses, i = raw[4:4 + n], [], 0
    while i < len(data):
        if data[i] == 0:
            pulses.append(int.from_bytes(data[i + 1:i + 3], "big") * TICK_US)
            i += 3
        else:
            pulses.append(data[i] * TICK_US)
            i += 1
    band = {v: k for k, v in BAND_BYTE.items()}.get(raw[0], f"0x{raw[0]:02X}")
    return {"band": band, "repeat": raw[1], "pulses": len(pulses),
            "duration_ms": round(sum(pulses) / 1000, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rf2broadlink", description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="24-bit code in hex (e.g. 67AE02), a Flipper .sub file, "
                                   "or a b64 packet with --decode")
    ap.add_argument("--te", type=int, help="pulse unit in µs (default: from .sub, else 350)")
    ap.add_argument("--bits", type=int, default=24, help="code length in bits (default 24)")
    ap.add_argument("--frames", type=int, default=6, help="frame repetitions per press (default 6)")
    ap.add_argument("--gap-ms", type=float, default=120, help="silence after the last frame (default 120)")
    ap.add_argument("--band", type=int, choices=sorted(BAND_BYTE), default=433)
    ap.add_argument("--ha", action="store_true", help="print with the b64: prefix used by Home Assistant")
    ap.add_argument("--decode", action="store_true", help="inspect an existing Broadlink b64 packet")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)

    try:
        if a.decode:
            print(decode(a.source))
            return 0
        path = Path(a.source)
        if path.suffix == ".sub" and path.exists():
            out = from_sub(path.read_text(), frames=a.frames, gap_ms=a.gap_ms, te=a.te)
        elif re.fullmatch(r"(0x)?[0-9a-fA-F]+", a.source):
            out = from_princeton(int(a.source, 16), bits=a.bits, te=a.te or 350,
                                 frames=a.frames, gap_ms=a.gap_ms, band=a.band)
        else:
            ap.error(f"{a.source!r} is neither a hex code nor an existing .sub file")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"b64:{out}" if a.ha else out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
