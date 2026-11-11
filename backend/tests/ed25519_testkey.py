"""Ed25519 signing for tests only (RFC 8032 section 6 reference algorithm) – a fixed TEST key, never a real one.

scripts/update.py only verifies; these helpers make the signatures the tests verify.
"""

from __future__ import annotations

import base64
import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
Point = tuple[int, int, int, int]

# A test key: 32 fixed bytes. It signs nothing outside the tests.
TEST_SECRET = bytes(range(1, 33))


def _add(a: Point, b: Point) -> Point:
    k1 = (a[1] - a[0]) * (b[1] - b[0]) % P
    k2 = (a[1] + a[0]) * (b[1] + b[0]) % P
    k3 = 2 * a[3] * b[3] * D % P
    k4 = 2 * a[2] * b[2] % P
    e, f, g, h = k2 - k1, k4 - k3, k4 + k3, k2 + k1
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(scalar: int, point: Point) -> Point:
    result: Point = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _recover_x(y: int, sign: int) -> int:
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    return P - x if (x & 1) != sign else x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _recover_x(_GY, 0)
BASE: Point = (_GX, _GY, 1, _GX * _GY % P)


def _compress(point: Point) -> bytes:
    zi = pow(point[2], P - 2, P)
    x, y = point[0] * zi % P, point[1] * zi % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _expand(secret: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(secret).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def public_key(secret: bytes = TEST_SECRET) -> bytes:
    return _compress(_mul(_expand(secret)[0], BASE))


def sign(message: bytes, secret: bytes = TEST_SECRET) -> bytes:
    a, prefix = _expand(secret)
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % L
    big_r = _compress(_mul(r, BASE))
    k = int.from_bytes(hashlib.sha512(big_r + public_key(secret) + message).digest(), "little") % L
    return big_r + int.to_bytes((r + k * a) % L, 32, "little")


def signature_file(message: bytes, secret: bytes = TEST_SECRET) -> str:
    """The contents of a ``.sig`` file: the signature in base64."""
    return base64.b64encode(sign(message, secret)).decode("ascii") + "\n"
