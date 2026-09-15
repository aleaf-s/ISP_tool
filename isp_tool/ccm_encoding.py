"""13-bit two's-complement CCM encoding, with ten fractional bits."""
import math

FIXED_MIN = -4.0
FIXED_MAX = 4095 / 1024


def decode_ccm(code):
    if isinstance(code, bool) or not math.isfinite(float(code)) or int(code) != code or not 0 <= code <= 8191:
        raise ValueError("Fixed code must be an integer in 0…8191")
    return (int(code) if code < 4096 else int(code) - 8192) / 1024


def encode_ccm(coefficient):
    value = float(coefficient)
    if not math.isfinite(value) or not FIXED_MIN <= value <= FIXED_MAX:
        raise ValueError("Fixed range: −4 … 3.9990234375 (+4 is not representable)")
    # Exactly halfway values round to the even integer (Python round).
    signed = round(value * 1024)
    return signed if signed >= 0 else signed + 8192
