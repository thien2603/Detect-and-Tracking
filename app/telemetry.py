"""Small codec-tolerant clock marker for same-host RTSP latency experiments.

The marker is a replay-source wall-clock timestamp, not a claim about a physical
camera's exposure time. A receiving probe includes both RTSP legs and decoding;
VLC display buffering is not included. Clock synchronization is required across hosts.
"""

import binascii
import logging
import time

import numpy as np

BITS = 72


def clear_time(frame):
    """Do not forge a replay-source clock when an input marker cannot be decoded."""
    cell = min(8, frame.shape[1] // BITS)
    if cell >= 3 and frame.shape[0] >= cell + 2:
        frame[-cell - 2:-2, :BITS * cell] = 0
    return frame


def stamp_time(frame, timestamp_ms=None):
    timestamp_ms = round(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    payload = b"\xa7" + int(timestamp_ms).to_bytes(6, "big")
    payload += binascii.crc_hqx(payload, 0xFFFF).to_bytes(2, "big")
    cell = min(8, frame.shape[1] // BITS)
    if cell < 3 or frame.shape[0] < cell + 2:
        return frame
    y = frame.shape[0] - cell - 2
    bits = np.unpackbits(np.frombuffer(payload, np.uint8))
    for index, bit in enumerate(bits):
        frame[y:y + cell, index * cell:(index + 1) * cell] = 255 if bit else 0
    return frame


def read_time(frame):
    cell = min(8, frame.shape[1] // BITS)
    if cell < 3 or frame.shape[0] < cell + 2:
        return None
    y = frame.shape[0] - cell - 2
    bits = [frame[y + 1:y + cell - 1, i * cell + 1:(i + 1) * cell - 1].mean() > 127
            for i in range(BITS)]
    payload = np.packbits(bits).tobytes()
    if payload[0] != 0xA7:
        return None
    if binascii.crc_hqx(payload[:7], 0xFFFF) != int.from_bytes(payload[7:], "big"):
        return None
    timestamp = int.from_bytes(payload[1:7], "big")
    return timestamp if abs(time.time() * 1000 - timestamp) < 60000 else None


def console_logging(level="INFO"):
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
