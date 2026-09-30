"""JPEG XL (ISO/IEC 18181): сведения из заголовка файла без декодирования.

Pillow формат не читает, поэтому заголовок кодового потока и блоки контейнера
(Exif, XMP) разбираются здесь. Пиксели не декодируются.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

CODESTREAM_SIGNATURE = b"\xff\x0a"
CONTAINER_SIGNATURE = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
HEAD_LIMIT = 64 * 1024            # заголовок кодового потока занимает десятки байт
METADATA_LIMIT = 16 * 1024 * 1024  # блоки Exif/XMP больше этого не читаются

RATIOS = {1: (1, 1), 2: (12, 10), 3: (4, 3), 4: (3, 2), 5: (16, 9), 6: (5, 4), 7: (2, 1)}
WHITE_POINTS = {1: "D65", 2: "заданная", 10: "E", 11: "DCI"}
PRIMARIES = {1: "sRGB", 2: "заданные", 9: "BT.2100", 11: "P3"}
TRANSFER = {1: "BT.709", 2: "неизвестная", 8: "линейная", 13: "sRGB", 16: "PQ", 17: "DCI", 18: "HLG"}
EXTRA_ALPHA, EXTRA_SPOT, EXTRA_BLACK, EXTRA_CFA = 0, 2, 4, 5


class JxlError(ValueError):
    pass


@dataclass
class JxlInfo:
    container: bool = False
    width: int = 0
    height: int = 0
    bits: int = 8
    floating: bool = False
    grey: bool = False
    alpha: bool = False
    extra_channels: int = 0
    xyb: bool = True             # XYB — внутреннее пространство сжатия с потерями
    icc: bool = False            # цвет задан встроенным ICC-профилем
    colour: str = "sRGB"
    animation: bool = False
    jpeg_reconstruction: bool = False   # блок jbrd: перепакованный без потерь JPEG
    level: int | None = None
    exif: bytes = b""            # TIFF-структура EXIF
    xmp: bytes = b""
    compressed_metadata: list[str] = field(default_factory=list)  # блоки brob, которые не удалось распаковать


class _Bits:
    """Чтение битов от младшего к старшему, как в кодовом потоке JPEG XL."""

    def __init__(self, data: bytes):
        self.value = int.from_bytes(data, "little")
        self.total = len(data) * 8
        self.pos = 0

    def u(self, n: int) -> int:
        if self.pos + n > self.total:
            raise JxlError("заголовок JPEG XL обрывается")
        out = (self.value >> self.pos) & ((1 << n) - 1)
        self.pos += n
        return out

    def bool(self) -> bool:
        return bool(self.u(1))

    def u32(self, *dist) -> int:
        """dist — четыре варианта: число (константа) или (бит, смещение)."""
        d = dist[self.u(2)]
        return d if isinstance(d, int) else self.u(d[0]) + d[1]

    def enum(self) -> int:
        return self.u32(0, 1, (4, 2), (6, 18))


def _size(b: _Bits) -> tuple[int, int]:
    small = b.bool()
    big = ((9, 1), (13, 1), (18, 1), (30, 1))
    height = (b.u(5) + 1) * 8 if small else b.u32(*big)
    ratio = b.u(3)
    if ratio:
        num, den = RATIOS[ratio]
        return height * num // den, height
    width = (b.u(5) + 1) * 8 if small else b.u32(*big)
    return width, height


def _preview(b: _Bits) -> None:
    div8 = b.bool()
    a, c = (16, 32, (5, 1), (9, 33)), ((6, 1), (8, 65), (10, 321), (12, 1345))
    b.u32(*(a if div8 else c))
    if b.u(3) == 0:
        b.u32(*(a if div8 else c))


def _bit_depth(b: _Bits) -> tuple[int, bool]:
    if not b.bool():
        return b.u32(8, 10, 12, (6, 1)), False
    bits = b.u32(32, 16, 24, (6, 1))
    b.u(4)  # разрядность экспоненты
    return bits, True


def _custom_xy(b: _Bits) -> None:
    for _ in range(2):
        b.u32((19, 0), (19, 524288), (20, 1048576), (21, 2097152))


def _colour_name(primaries: str, transfer: str, white: str, grey: bool) -> str:
    if grey:
        return f"оттенки серого, передаточная функция {transfer}" if transfer != "sRGB" else "оттенки серого (sRGB)"
    if primaries == "sRGB" and transfer == "sRGB" and white == "D65":
        return "sRGB"
    if primaries == "P3" and transfer == "sRGB" and white == "D65":
        return "Display P3"
    text = f"основные цвета {primaries}, передаточная функция {transfer}"
    return text if white == "D65" else f"{text}, белая точка {white}"


def parse_codestream(data: bytes, info: JxlInfo | None = None) -> JxlInfo:
    """Заголовок кодового потока: размер, разрядность, каналы, цвет."""
    info = info or JxlInfo()
    if data[:2] != CODESTREAM_SIGNATURE:
        raise JxlError("нет сигнатуры кодового потока JPEG XL")
    b = _Bits(data[2:])
    info.width, info.height = _size(b)
    if b.bool():  # все параметры по умолчанию: 8 бит, sRGB, XYB
        return info
    if b.bool():  # extra_fields
        b.u(3)  # ориентация
        if b.bool():
            _size(b)
        if b.bool():
            _preview(b)
        if b.bool():
            info.animation = True
            b.u32(100, 1000, (10, 1), (30, 1))
            b.u32(1, 1001, (8, 1), (10, 1))
            b.u32(0, (3, 0), (16, 0), (32, 0))
            b.bool()
    info.bits, info.floating = _bit_depth(b)
    b.bool()  # modular_16_bit_buffer_sufficient
    info.extra_channels = b.u32(0, 1, (4, 2), (12, 1))
    for _ in range(info.extra_channels):
        kind = EXTRA_ALPHA
        if not b.bool():
            kind = b.enum()
            _bit_depth(b)
            b.u32(0, 3, 4, (3, 1))
            for _ in range(b.u32(0, (4, 0), (5, 16), (10, 48))):
                b.u(8)
            if kind == EXTRA_ALPHA:
                b.bool()
            elif kind == EXTRA_SPOT:
                b.u(64)
            elif kind == EXTRA_CFA:
                b.u32(1, (2, 0), (4, 3), (8, 19))
        if kind == EXTRA_ALPHA:
            info.alpha = True
    info.xyb = b.bool()
    if b.bool():  # цвет по умолчанию: sRGB
        return info
    info.icc = b.bool()
    space = b.enum()
    info.grey = space == 1
    if info.icc:
        info.colour = ""
        return info
    white = primaries = 1
    if space != 2:
        white = b.enum()
        if white == 2:
            _custom_xy(b)
    if space not in (1, 2):
        primaries = b.enum()
        if primaries == 2:
            for _ in range(3):
                _custom_xy(b)
    if b.bool():
        gamma = b.u(24) / 10_000_000
        transfer = f"гамма {1 / gamma:.2f}".replace(".", ",") if gamma else "гамма"
    else:
        code = b.enum()
        transfer = TRANSFER.get(code, f"код {code}")
    info.colour = _colour_name(PRIMARIES.get(primaries, f"код {primaries}"), transfer,
                               WHITE_POINTS.get(white, f"код {white}"), info.grey)
    return info


def _unbrotli(data: bytes) -> bytes | None:
    try:
        import brotli  # необязательная зависимость
    except ImportError:
        return None
    try:
        return brotli.decompress(data)
    except Exception:  # noqa: BLE001
        return None


def _exif_tiff(payload: bytes) -> bytes:
    """Блок Exif: 4 байта смещения, затем TIFF-структура."""
    if len(payload) < 4:
        return b""
    offset = int.from_bytes(payload[:4], "big")
    return payload[4 + offset:]


def read(path: Path) -> JxlInfo:
    """Разбирает файл .jxl: «голый» кодовый поток или контейнер с блоками."""
    info = JxlInfo()
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:2] == CODESTREAM_SIGNATURE:
            f.seek(0)
            return parse_codestream(f.read(HEAD_LIMIT), info)
        if head != CONTAINER_SIGNATURE:
            raise JxlError("это не файл JPEG XL: нет сигнатуры")
        info.container = True
        f.seek(0, 2)
        end = f.tell()
        pos, stream = 0, b""
        while pos < end:
            f.seek(pos)
            header = f.read(16)
            if len(header) < 8:
                raise JxlError("контейнер JPEG XL обрывается")
            size, kind, header_len = int.from_bytes(header[:4], "big"), header[4:8], 8
            if size == 1:
                size, header_len = int.from_bytes(header[8:16], "big"), 16
            elif size == 0:
                size = end - pos
            if size < header_len or pos + size > end:
                raise JxlError(f"контейнер JPEG XL повреждён: блок «{kind.decode('latin-1')}» выходит за конец файла")
            body, body_len = pos + header_len, size - header_len
            f.seek(body)
            if kind == b"jxlc" and not stream:
                stream = f.read(min(body_len, HEAD_LIMIT))
            elif kind == b"jxlp" and len(stream) < HEAD_LIMIT:
                f.seek(body + 4)  # первые 4 байта — номер части
                stream += f.read(min(max(body_len - 4, 0), HEAD_LIMIT - len(stream)))
            elif kind == b"jxll" and body_len:
                info.level = f.read(1)[0]
            elif kind == b"jbrd":
                info.jpeg_reconstruction = True
            elif kind in (b"Exif", b"xml ", b"brob") and body_len <= METADATA_LIMIT:
                payload = f.read(body_len)
                if kind == b"brob":
                    kind, packed = payload[:4], payload[4:]
                    if kind in (b"Exif", b"xml "):
                        payload = _unbrotli(packed)
                        if payload is None:
                            info.compressed_metadata.append("EXIF" if kind == b"Exif" else "XMP")
                            kind = b""
                if kind == b"Exif" and not info.exif:
                    info.exif = _exif_tiff(payload)
                elif kind == b"xml " and not info.xmp:
                    info.xmp = payload
            pos += size
    if not stream:
        raise JxlError("в контейнере JPEG XL нет кодового потока")
    return parse_codestream(stream, info)


def check(path: Path) -> None:
    """Проверка структуры при сверке: сигнатура, блоки контейнера, заголовок.
    Пиксели не декодируются — полную проверку даёт контрольная сумма."""
    info = read(path)
    if not info.width or not info.height:
        raise JxlError("нулевой размер изображения")
