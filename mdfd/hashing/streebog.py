"""Хеш «Стрибог» (ГОСТ 34.11-2018 / ГОСТ Р 34.11-2012).

Основная реализация — модуль на C (`_streebog`), собирается вместе с программой.
Если модуль не собран, используется реализация на чистом Python: результат
тот же, но она примерно в сто раз медленнее.
"""
from __future__ import annotations

from ._streebog_tables import C as _C
from ._streebog_tables import T as _T

try:
    from . import _streebog as _native
except ImportError:  # pragma: no cover - зависит от сборки
    _native = None

BACKEND = "C" if _native is not None else "Python"

_BLOCK = 64
_MASK = (1 << 64) - 1
_MASK512 = (1 << 512) - 1
_T0, _T1, _T2, _T3, _T4, _T5, _T6, _T7 = _T


def _lps(x):
    x0, x1, x2, x3, x4, x5, x6, x7 = x
    out = []
    for s in (0, 8, 16, 24, 32, 40, 48, 56):
        out.append(
            _T0[(x0 >> s) & 0xFF] ^ _T1[(x1 >> s) & 0xFF] ^ _T2[(x2 >> s) & 0xFF]
            ^ _T3[(x3 >> s) & 0xFF] ^ _T4[(x4 >> s) & 0xFF] ^ _T5[(x5 >> s) & 0xFF]
            ^ _T6[(x6 >> s) & 0xFF] ^ _T7[(x7 >> s) & 0xFF]
        )
    return out


def _xor(a, b):
    return [p ^ q for p, q in zip(a, b)]


def _compress(h, n, m):
    k = _lps(_xor(h, n))
    state = _xor(k, m)
    for c in _C:
        state = _lps(state)
        k = _lps(_xor(k, c))
        state = _xor(state, k)
    return [a ^ b ^ c for a, b, c in zip(h, state, m)]


def _words(block: bytes):
    return [int.from_bytes(block[i:i + 8], "little") for i in range(0, 64, 8)]


def _to_int(words) -> int:
    return int.from_bytes(b"".join(w.to_bytes(8, "little") for w in words), "little")


def _from_int(value: int):
    return _words((value & _MASK512).to_bytes(64, "little"))


class _PyStreebog:
    block_size = _BLOCK

    def __init__(self, bits: int = 256):
        if bits not in (256, 512):
            raise ValueError("bits должен быть 256 или 512")
        self._bits = bits
        self._h = [0x0101010101010101] * 8 if bits == 256 else [0] * 8
        self._n = 0
        self._sigma = 0
        self._buf = b""

    @property
    def digest_size(self) -> int:
        return self._bits // 8

    @property
    def name(self) -> str:
        return f"streebog{self._bits}"

    def update(self, data) -> None:
        data = self._buf + bytes(data)
        full = len(data) - len(data) % _BLOCK
        for i in range(0, full, _BLOCK):
            m = _words(data[i:i + _BLOCK])
            self._h = _compress(self._h, _from_int(self._n), m)
            self._n = (self._n + 512) & _MASK512
            self._sigma = (self._sigma + _to_int(m)) & _MASK512
        self._buf = data[full:]

    def copy(self) -> "_PyStreebog":
        other = _PyStreebog(self._bits)
        other._h, other._n, other._sigma, other._buf = list(self._h), self._n, self._sigma, self._buf
        return other

    def digest(self) -> bytes:
        block = self._buf + b"\x01" + b"\x00" * (_BLOCK - len(self._buf) - 1)
        m = _words(block)
        zero = [0] * 8
        h = _compress(self._h, _from_int(self._n), m)
        n = (self._n + len(self._buf) * 8) & _MASK512
        sigma = (self._sigma + _to_int(m)) & _MASK512
        h = _compress(h, zero, _from_int(n))
        h = _compress(h, zero, _from_int(sigma))
        full = b"".join(w.to_bytes(8, "little") for w in h)
        return full[32:] if self._bits == 256 else full

    def hexdigest(self) -> str:
        return self.digest().hex()


def new(bits: int = 256, data: bytes | None = None, *, pure_python: bool = False):
    """Создаёт объект хеша «Стрибог» (как hashlib.new)."""
    if _native is not None and not pure_python:
        return _native.new(bits) if data is None else _native.new(bits, data)
    h = _PyStreebog(bits)
    if data is not None:
        h.update(data)
    return h
