"""Изображения: сведения через Pillow, для RAW — через rawpy (если установлен)."""
from __future__ import annotations

import io
import re
from pathlib import Path

from .. import formats, textfmt
from ..model import ProbeResult
from . import embedded

try:
    from PIL import Image, ImageCms
except ImportError:  # pragma: no cover
    Image = None
    ImageCms = None

try:
    import rawpy
except ImportError:  # pragma: no cover - необязательная зависимость
    rawpy = None

LOSSY = "с потерями"
LOSSLESS = "без потерь"
NONE = "без сжатия"

TIFF_COMPRESSION = {
    "raw": (NONE, ""),
    "tiff_raw_16": (NONE, ""),
    "packbits": (LOSSLESS, "PackBits"),
    "tiff_lzw": (LOSSLESS, "LZW"),
    "tiff_adobe_deflate": (LOSSLESS, "Deflate (ZIP)"),
    "tiff_deflate": (LOSSLESS, "Deflate (ZIP)"),
    "tiff_ccitt": (LOSSLESS, "CCITT"),
    "group3": (LOSSLESS, "CCITT Group 3"),
    "group4": (LOSSLESS, "CCITT Group 4"),
    "tiff_thunderscan": (LOSSLESS, "ThunderScan"),
    "tiff_jpeg": (LOSSY, "JPEG (старый вариант)"),
    "jpeg": (LOSSY, "JPEG"),
    "tiff_sgilog": (LOSSY, "SGI LogL"),
    "tiff_sgilog24": (LOSSY, "SGI LogLuv"),
    "lzma": (LOSSLESS, "LZMA"),
    "zstd": (LOSSLESS, "Zstandard"),
    "webp": (LOSSY, "WebP"),
    "jpeg2000": (LOSSY, "JPEG 2000"),
}

BMP_COMPRESSION = {0: (NONE, ""), 1: (LOSSLESS, "RLE8"), 2: (LOSSLESS, "RLE4"),
                   3: (NONE, "битовые маски"), 4: (LOSSY, "JPEG"), 5: (LOSSLESS, "PNG"),
                   6: (NONE, "битовые маски с альфа-каналом")}
BMP_HEADER_VERSIONS = {12: "2.0", 40: "3.0", 108: "4.0", 124: "5.0"}

MODES = {
    "1": "чёрно-белое (1 бит)",
    "L": "оттенки серого",
    "LA": "оттенки серого с прозрачностью",
    "La": "оттенки серого с прозрачностью",
    "P": "палитра (индексированные цвета)",
    "PA": "палитра с прозрачностью",
    "RGB": "RGB",
    "RGBA": "RGB с прозрачностью (RGBA)",
    "RGBa": "RGB с прозрачностью (RGBA)",
    "RGBX": "RGB",
    "CMYK": "CMYK",
    "YCbCr": "YCbCr",
    "LAB": "CIE L*a*b*",
    "HSV": "HSV",
    "I": "оттенки серого",
    "I;16": "оттенки серого",
    "I;16L": "оттенки серого",
    "I;16B": "оттенки серого",
    "I;16N": "оттенки серого",
    "F": "оттенки серого (плавающая точка)",
}
MODE_BITS = {"1": 1, "I": 32, "F": 32, "I;16": 16, "I;16L": 16, "I;16B": 16, "I;16N": 16}

PHOTOMETRIC = {0: "оттенки серого", 1: "оттенки серого", 2: "RGB", 3: "палитра (индексированные цвета)",
               4: "маска", 5: "CMYK", 6: "YCbCr", 8: "CIE L*a*b*", 9: "ICC L*a*b*", 10: "ITU L*a*b*",
               32844: "LogL", 32845: "LogLuv", 34892: "Linear Raw", 32803: "CFA (RAW)"}

PNG_COLOR_TYPES = {0: "оттенки серого", 2: "RGB", 3: "палитра (индексированные цвета)",
                   4: "оттенки серого с прозрачностью", 6: "RGB с прозрачностью (RGBA)"}

EXIF_IFD = 0x8769
TAG_MAKE, TAG_MODEL, TAG_DATETIME = 0x010F, 0x0110, 0x0132
TAG_XRES, TAG_YRES, TAG_RESUNIT = 0x011A, 0x011B, 0x0128
TAG_DATETIME_ORIGINAL, TAG_EXIF_VERSION = 0x9003, 0x9000
TAG_BITS_PER_SAMPLE, TAG_PHOTOMETRIC, TAG_SAMPLES = 258, 262, 277
TAG_DNG_VERSION = 50706

DNG_VERSIONS = {"1.0": "fmt/436", "1.1": "fmt/152", "1.2": "fmt/437", "1.3": "fmt/438",
                "1.4": "fmt/730", "1.5": "fmt/1841", "1.6": "fmt/1842", "1.7": "fmt/1943"}

RAW_EXTENSIONS = {"cr2", "cr3", "crw", "nef", "nrw", "arw", "rw2", "orf", "raf", "pef", "dng", "srw", "x3f"}


def _read_head(path: Path, size: int = 64 * 1024) -> bytes:
    with open(path, "rb") as f:
        return f.read(size)


def _number(value) -> str:
    return textfmt._trim(textfmt.decimal(float(value), 2))


def _compression_text(kind: str, method: str) -> str:
    return f"{kind} ({method})" if method else kind


def _jp2_compression(head: bytes) -> tuple[str, str]:
    pos = head.find(b"\xff\x52")
    if pos < 0 or pos + 14 > len(head):
        return "", "JPEG 2000"
    transform = head[pos + 13]
    if transform == 1:
        return LOSSLESS, "JPEG 2000, обратимое вейвлет-преобразование 5/3"
    return LOSSY, "JPEG 2000, необратимое вейвлет-преобразование 9/7"


def _webp_kind(head: bytes) -> str:
    chunk = head[12:16]
    if chunk == b"VP8L":
        return "lossless"
    if chunk == b"VP8 ":
        return "lossy"
    if chunk == b"VP8X":
        return "extended"
    return ""


def _webp_extended_lossless(head: bytes) -> bool | None:
    pos = 12
    while pos + 8 <= len(head):
        cid = head[pos:pos + 4]
        size = int.from_bytes(head[pos + 4:pos + 8], "little")
        if cid == b"VP8L":
            return True
        if cid == b"VP8 ":
            return False
        pos += 8 + size + (size & 1)
    return None


def _icc_description(icc: bytes) -> str:
    if not icc or ImageCms is None:
        return ""
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return (ImageCms.getProfileDescription(profile) or "").strip()
    except Exception:  # noqa: BLE001 - повреждённый профиль не критичен
        return "встроен (описание не читается)"


def _exif_text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii", "replace")
    return str(value).strip("\x00 ").strip()


def _exif_date(value: str) -> str:
    """'2023:07:15 12:34:56' -> '15.07.2023 12:34:56'."""
    text = _exif_text(value)
    try:
        date, time = text.split(" ", 1)
        y, m, d = date.split(":")
        return f"{d}.{m}.{y} {time}"
    except ValueError:
        return text


def _dpi_from_exif(exif) -> tuple[float, float] | None:
    x, y, unit = exif.get(TAG_XRES), exif.get(TAG_YRES), exif.get(TAG_RESUNIT, 2)
    if not x or not y:
        return None
    x, y = float(x), float(y)
    if unit == 3:
        return x * 2.54, y * 2.54
    if unit == 2:
        return x, y
    return None


def _set_resolution(result: ProbeResult, width: int, height: int, dpi) -> None:
    result.add("pixel_size", "Размер изображения", f"{width} × {height} пикс.", f"{width}x{height}")
    if dpi and dpi[0] and dpi[1] and dpi[0] > 1 and dpi[1] > 1:
        dx, dy = round(float(dpi[0]), 2), round(float(dpi[1]), 2)
        text = f"{_number(dx)} точек/дюйм" if dx == dy else f"{_number(dx)} × {_number(dy)} точек/дюйм"
        result.add("resolution", "Разрешение", text, f"{dx}x{dy}")
        w_cm, h_cm = width / dx * 2.54, height / dy * 2.54
        result.add("print_size", "Размер при печати",
                   f"{textfmt.decimal(w_cm, 1)} × {textfmt.decimal(h_cm, 1)} см",
                   f"{w_cm:.2f}x{h_cm:.2f}")
    else:
        result.add("resolution", "Разрешение", "не указано в файле")


def _probe_raw(path: Path, result: ProbeResult) -> bool:
    if rawpy is None:
        return False
    try:
        with rawpy.imread(str(path)) as raw:
            sizes = raw.sizes
            _set_resolution(result, sizes.width, sizes.height, None)
            result.add("sensor_size", "Размер матрицы (RAW)",
                       f"{sizes.raw_width} × {sizes.raw_height} пикс.")
            if raw.white_level:
                result.add("bit_depth", "Разрядность", f"{int(raw.white_level).bit_length()} бит (данные сенсора)")
            result.add("color_mode", "Цветовая модель",
                       f"данные сенсора ({raw.color_desc.decode('ascii', 'replace')})")
            result.add("compression", "Метод сжатия", "данные сенсора (RAW), сжатие определяется производителем")
        return True
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(f"RAW-файл не прочитан: {exc}")
        return False


TAG_LENS_MODEL, TAG_EXPOSURE, TAG_FNUMBER, TAG_ISO = 0xA434, 0x829A, 0x829D, 0x8827
TAG_DESCRIPTION, TAG_SOFTWARE, TAG_ARTIST, TAG_COPYRIGHT = 0x010E, 0x0131, 0x013B, 0x8298
TAG_FOCAL_LENGTH, TAG_BODY_SERIAL, TAG_LENS_SPEC, TAG_MAKERNOTE = 0x920A, 0xA431, 0xA432, 0x927C
TAG_XMP, TAG_IPTC, GPS_IFD = 700, 0x83BB, 0x8825

# Подписи, которые камеры ставят вместо описания снимка
GENERIC_DESCRIPTIONS = {"olympus digital camera", "sony dsc", "digital camera", "konica minolta digital camera",
                        "minolta dsc", "samsung", "default", "exif_jpeg_picture", "lg digital camera",
                        "camera", "image", "picture"}


def read_tiff_ifds(path: Path) -> tuple[dict, dict, dict]:
    """IFD0, EXIF и GPS из файла, устроенного как TIFF (ARW, NEF, CR2, DNG, PEF и др.),
    без декодирования изображения. Нужен, когда Pillow сам файл не открывает."""
    from PIL import TiffImagePlugin

    def load(f, header, offset):
        ifd = TiffImagePlugin.ImageFileDirectory_v2(header)
        f.seek(offset)
        ifd.load(f)
        return dict(ifd)

    with open(path, "rb") as f:
        header = f.read(8)
        if header[:4] not in (b"II*\x00", b"MM\x00*"):
            return {}, {}, {}
        ifd0 = load(f, header, int.from_bytes(header[4:8], "little" if header[:2] == b"II" else "big"))
        exif_ifd = load(f, header, int(ifd0[EXIF_IFD])) if EXIF_IFD in ifd0 else {}
        gps = {}
        if GPS_IFD in ifd0:
            try:
                gps = load(f, header, int(ifd0[GPS_IFD]))
            except Exception:  # noqa: BLE001 - координаты не обязательны
                gps = {}
    return ifd0, exif_ifd, gps


def read_tiff_exif(path: Path) -> tuple[dict, dict]:
    """(IFD0, EXIF IFD) — см. read_tiff_ifds."""
    return read_tiff_ifds(path)[:2]


def camera_name(make: str, model: str) -> str:
    """«Canon» + «Canon EOS 6D» -> «Canon EOS 6D» (многие камеры повторяют производителя в модели)."""
    make, model = make.strip(), model.strip()
    first = make.split()[0].casefold() if make else ""
    if first and model.casefold().startswith(first):
        return model
    return " ".join(x for x in (make, model) if x)


def _exif_string(value) -> str:
    """Строка EXIF. Pillow читает её как latin-1, а русские программы пишут UTF-8."""
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    text = str(value).strip("\x00 ").strip()
    if any(ord(c) > 127 for c in text):
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def _nikon_makernote(exif_ifd: dict) -> dict:
    """Служебные теги Nikon (формат «Nikon\\0\\x02»): там ISO, объектив и серийный номер,
    которых в EXIF старых камер нет."""
    data = exif_ifd.get(TAG_MAKERNOTE)
    if not isinstance(data, bytes) or not data.startswith(b"Nikon\x00\x02") or len(data) < 18:
        return {}
    from PIL import TiffImagePlugin
    body = data[10:]
    if body[:4] not in (b"II*\x00", b"MM\x00*"):
        return {}
    ifd = TiffImagePlugin.ImageFileDirectory_v2(body[:8])
    stream = io.BytesIO(body)
    stream.seek(int.from_bytes(body[4:8], "little" if body[:2] == b"II" else "big"))
    try:
        ifd.load(stream)
    except Exception:  # noqa: BLE001
        return {}
    return dict(ifd)


def _nikon_iso(note: dict):
    iso = note.get(0x0002)
    if isinstance(iso, tuple) and len(iso) > 1 and iso[1]:
        return iso[1]
    info = note.get(0x0025)
    if isinstance(info, bytes) and info and info[0]:
        return round(100 * 2 ** (info[0] / 12 - 5))
    return None


def _lens_from_spec(spec) -> str:
    """(24, 70, 2.8, 2.8) -> «24–70 мм f/2,8»."""
    try:
        low, high, ap_low, ap_high = (float(x) for x in spec[:4])
    except (TypeError, ValueError):
        return ""
    if not low or low != low:
        return ""

    def num(x):
        return textfmt._trim(textfmt.decimal(x, 1))
    text = f"{num(low)} мм" if not high or high == low or high != high else f"{num(low)}–{num(high)} мм"
    if ap_low and ap_low == ap_low:
        aperture = num(ap_low)
        if ap_high and ap_high == ap_high and ap_high != ap_low:
            aperture += f"–{num(ap_high)}"
        text += f" f/{aperture}"
    return text


def _gps_text(gps: dict) -> tuple[str, str]:
    def degrees(value):
        d, m, s = (float(x) for x in value)
        return d + m / 60 + s / 3600
    try:
        lat, lon = degrees(gps[2]), degrees(gps[4])
    except (KeyError, TypeError, ValueError):
        return "", ""
    if lat != lat or lon != lon or (lat == 0 and lon == 0):
        return "", ""
    south = _exif_string(gps.get(1, "N")).upper() == "S"
    west = _exif_string(gps.get(3, "E")).upper() == "W"
    text = (f"{textfmt.decimal(lat, 6)}° {'ю' if south else 'с'}. ш., "
            f"{textfmt.decimal(lon, 6)}° {'з' if west else 'в'}. д.")
    return text, f"{-lat if south else lat:.6f},{-lon if west else lon:.6f}"


def _first_value(*candidates) -> str:
    for value in candidates:
        if isinstance(value, list):
            value = "; ".join(dict.fromkeys(v for v in value if v))
        if value:
            return value
    return ""


def _add_camera_info(result: ProbeResult, ifd0: dict, exif_ifd: dict,
                     gps: dict | None = None, xmp: dict | None = None, iptc: dict | None = None) -> None:
    xmp, iptc, gps = xmp or {}, iptc or {}, gps or {}
    note = _nikon_makernote(exif_ifd)

    # Сведения об авторе и содержании снимка — как их записал фотограф
    result.add("author", "Автор (по метаданным файла)",
               _first_value(_exif_string(ifd0.get(TAG_ARTIST, "")), xmp.get("dc:creator"), iptc.get("by_line")))
    result.add("copyright", "Авторские права (по метаданным файла)",
               _first_value(_exif_string(ifd0.get(TAG_COPYRIGHT, "")), xmp.get("dc:rights"), iptc.get("copyright")))
    result.add("title", "Название (по метаданным файла)", _first_value(xmp.get("dc:title"), iptc.get("object_name")))
    description = _exif_string(ifd0.get(TAG_DESCRIPTION, ""))
    if description.casefold() in GENERIC_DESCRIPTIONS:
        description = ""
    result.add("description", "Описание (по метаданным файла)",
               _first_value(description, xmp.get("dc:description"), iptc.get("caption")))
    result.add("keywords", "Ключевые слова", _first_value(xmp.get("dc:subject"), iptc.get("keywords")))

    result.add("camera", "Камера / сканер",
               camera_name(_exif_string(ifd0.get(TAG_MAKE, "")), _exif_string(ifd0.get(TAG_MODEL, ""))))
    result.add("camera_serial", "Серийный номер камеры",
               _first_value(_exif_string(exif_ifd.get(TAG_BODY_SERIAL, "")), xmp.get("aux:SerialNumber"),
                            _exif_string(note.get(0x001D, ""))))
    # aux:Lens у Nikon — лишь диапазон «24.0-85.0 mm f/3.5-4.5»; тогда понятнее запись по спецификации
    aux_lens = _first_value(xmp.get("aux:Lens"))
    spec_like = bool(re.match(r"^[\d.]+(?:-[\d.]+)?\s*mm\b", aux_lens))
    result.add("lens", "Объектив",
               _first_value(_exif_string(exif_ifd.get(TAG_LENS_MODEL, "")), xmp.get("exifEX:LensModel"),
                            "" if spec_like else aux_lens, _lens_from_spec(exif_ifd.get(TAG_LENS_SPEC)),
                            _lens_from_spec(note.get(0x0084)), aux_lens))
    parts = []
    exposure = exif_ifd.get(TAG_EXPOSURE)
    if exposure:
        value = float(exposure)
        parts.append(f"1/{round(1 / value)} с" if 0 < value < 1 else f"{textfmt._trim(textfmt.decimal(value, 1))} с")
    fnumber = exif_ifd.get(TAG_FNUMBER)
    if fnumber:
        parts.append(f"f/{textfmt._trim(textfmt.decimal(float(fnumber), 1))}")
    iso = exif_ifd.get(TAG_ISO) or _nikon_iso(note)
    if iso:
        parts.append(f"ISO {iso[0] if isinstance(iso, tuple) else iso}")
    focal = exif_ifd.get(TAG_FOCAL_LENGTH)
    if focal and float(focal) == float(focal) and float(focal) > 0:
        parts.append(f"{textfmt._trim(textfmt.decimal(float(focal), 1))} мм")
    result.add("exposure", "Параметры съёмки", ", ".join(parts))

    original = exif_ifd.get(TAG_DATETIME_ORIGINAL)
    xmp_created = _first_value(xmp.get("xmp:CreateDate"), xmp.get("photoshop:DateCreated"))
    taken = original or ifd0.get(TAG_DATETIME)
    if taken:
        label = "Дата съёмки (EXIF)" if original else "Дата изменения (EXIF)"
        result.add("exif_date", label, _exif_date(taken), _exif_text(taken))
        result.content_created = _exif_date(taken)
    if not original and xmp_created:
        # Снимок без даты съёмки (например, скан): дата создания из XMP раньше даты изменения
        result.add("xmp_date", "Дата создания (XMP)", textfmt.any_date(xmp_created), xmp_created)
        result.content_created = textfmt.any_date(xmp_created)
    coords, raw = _gps_text(gps)
    result.add("gps", "Координаты съёмки (GPS)", coords, raw or None)

    result.add("software", "Программа создания или обработки",
               _first_value(_exif_string(ifd0.get(TAG_SOFTWARE, "")), xmp.get("xmp:CreatorTool")))
    result.add("original_name", "Исходное имя файла", _first_value(xmp.get("xmpMM:PreservedFileName")))


def _embedded(img, tags) -> tuple[dict, dict]:
    """XMP и IPTC из открытого в Pillow изображения."""
    packet = img.info.get("xmp") or img.info.get("XML:com.adobe.xmp") or tags.get(TAG_XMP)
    xmp = embedded.parse_xmp(packet)
    try:
        from PIL import IptcImagePlugin
        iptc = embedded.parse_iptc(IptcImagePlugin.getiptcinfo(img))
    except Exception:  # noqa: BLE001 - повреждённый блок IPTC не мешает описанию
        iptc = {}
    return xmp, iptc


def probe(path: Path, result: ProbeResult) -> ProbeResult:
    ext = path.suffix.lower().lstrip(".")
    raw_done = ext in RAW_EXTENSIONS and _probe_raw(path, result)

    if Image is None:
        result.warnings.append("Библиотека Pillow недоступна: сведения об изображении не получены.")
        return result
    Image.MAX_IMAGE_PIXELS = None  # пиксели не декодируются, ограничение не нужно
    try:
        img = Image.open(path)
    except Exception as exc:  # noqa: BLE001
        if raw_done:
            # Pillow не открывает многие RAW (например, Sony ARW), но EXIF в них — обычный TIFF
            try:
                ifd0, exif_ifd, gps = read_tiff_ifds(path)
                _add_camera_info(result, ifd0, exif_ifd, gps, embedded.parse_xmp(ifd0.get(TAG_XMP)))
            except Exception:  # noqa: BLE001 - без EXIF описание всё равно полное
                pass
        if not raw_done:
            if ext in RAW_EXTENSIONS and rawpy is None:
                result.warnings.append("Для RAW-файлов установите пакет rawpy.")
            else:
                result.warnings.append(f"Изображение не открылось: {exc}")
        return result

    with img:
        head = _read_head(path)
        fmt = img.format or ""
        exif = img.getexif()
        exif_ifd = exif.get_ifd(EXIF_IFD) if exif else {}
        tags = getattr(img, "tag_v2", {}) or {}

        if raw_done:
            # Pillow открывает RAW как TIFF и видит только миниатюру — берём из него лишь EXIF.
            pass
        else:
            dpi = img.info.get("dpi") or (_dpi_from_exif(exif) if exif else None)
            _set_resolution(result, img.width, img.height, dpi)

            mode = img.mode
            color = MODES.get(mode, mode)
            bits = MODE_BITS.get(mode, 8)
            if TAG_PHOTOMETRIC in tags:
                color = PHOTOMETRIC.get(tags[TAG_PHOTOMETRIC], color)
            if TAG_BITS_PER_SAMPLE in tags:
                sample_bits = tags[TAG_BITS_PER_SAMPLE]
                bits = sample_bits[0] if isinstance(sample_bits, tuple) else sample_bits
            if fmt == "PNG" and head[12:16] == b"IHDR":
                bits = head[24]
                color = PNG_COLOR_TYPES.get(head[25], color)
            if fmt == "BMP" and len(head) >= 30:
                header_size = int.from_bytes(head[14:18], "little")
                offset = 24 if header_size == 12 else 28
                bits = int.from_bytes(head[offset:offset + 2], "little")
            result.add("color_mode", "Цветовая модель", color, mode)
            if mode in ("P", "PA") or fmt == "GIF":
                result.add("bit_depth", "Глубина цвета", f"{bits} бит на пиксель (палитра)", bits)
            elif fmt == "BMP":
                result.add("bit_depth", "Глубина цвета", f"{bits} бит на пиксель", bits)
            else:
                result.add("bit_depth", "Глубина цвета", f"{bits} бит на канал", bits)

            kind, method = "", ""
            if fmt in ("JPEG", "MPO"):
                kind, method = LOSSY, "JPEG"
                if img.info.get("progressive"):
                    method = "JPEG, прогрессивный"
            elif fmt == "TIFF":
                kind, method = TIFF_COMPRESSION.get(img.info.get("compression", ""), ("", img.info.get("compression", "")))
            elif fmt == "PNG":
                kind, method = LOSSLESS, "Deflate"
            elif fmt == "GIF":
                kind, method = LOSSLESS, "LZW; не более 256 цветов"
            elif fmt == "BMP" and len(head) >= 34:
                header_size = int.from_bytes(head[14:18], "little")
                code = int.from_bytes(head[30:34], "little") if header_size >= 40 else 0
                kind, method = BMP_COMPRESSION.get(code, ("", f"код {code}"))
                result.format_version = BMP_HEADER_VERSIONS.get(header_size, "")
                result.puid = formats.BMP_VERSIONS.get(result.format_version, "")
            elif fmt == "WEBP":
                webp = _webp_kind(head)
                lossless = webp == "lossless" or (webp == "extended" and _webp_extended_lossless(head))
                kind, method = (LOSSLESS, "WebP lossless") if lossless else (LOSSY, "WebP (VP8)")
                result.puid = formats.WEBP_KINDS.get(webp, "")
            elif fmt == "JPEG2000":
                kind, method = _jp2_compression(head)
            if kind:
                result.add("compression", "Метод сжатия", _compression_text(kind, method), method or kind)
            if kind == LOSSY:
                result.notes.append(formats.NOTE_LOSSY)

            frames = getattr(img, "n_frames", 1)
            if frames > 1:
                label = "Количество кадров" if fmt in ("GIF", "WEBP", "PNG") else "Количество страниц"
                result.add("frames", label, frames)

            icc = _icc_description(img.info.get("icc_profile"))
            result.add("icc_profile", "Цветовой профиль (ICC)", icc)

        # Версия формата для реестра PRONOM
        if fmt == "JPEG":
            exif_version = _exif_text(exif_ifd.get(TAG_EXIF_VERSION, b"")) if exif_ifd else ""
            jfif = img.info.get("jfif_version")
            if exif_version:
                version = f"{int(exif_version[:2])}.{exif_version[2:].rstrip('0') or '0'}"
                result.format_name = "JPEG (EXIF)"
                result.format_version = f"EXIF {version}"
                result.puid = formats.EXIF_JPEG_VERSIONS.get(version, "")
                if not result.puid and version.startswith("2.3"):
                    result.puid = formats.EXIF_23_PUID
            elif jfif:
                version = f"{jfif[0]}.{jfif[1]:02d}"
                result.format_name = "JPEG (JFIF)"
                result.format_version = f"JFIF {version}"
                result.puid = formats.JFIF_VERSIONS.get(version, "")
        elif fmt == "GIF":
            version = head[3:6].decode("ascii", "replace")
            result.format_version = version
            result.puid = formats.GIF_VERSIONS.get(version, "")
        elif ext == "dng" and TAG_DNG_VERSION in tags:
            version = ".".join(str(b) for b in bytes(tags[TAG_DNG_VERSION])[:2])
            result.format_version = version
            result.puid = DNG_VERSIONS.get(version, "")

        xmp, iptc = _embedded(img, tags)
        if exif or xmp or iptc:
            gps = exif.get_ifd(GPS_IFD) if exif else {}
            _add_camera_info(result, dict(exif) if exif else {}, dict(exif_ifd) if exif_ifd else {},
                             dict(gps) if gps else {}, xmp, iptc)
    return result
