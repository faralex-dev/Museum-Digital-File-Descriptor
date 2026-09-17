"""Справочник форматов файлов.

Идентификаторы PRONOM (реестр форматов Национального архива Великобритании)
взяты из файла сигнатур DROID, версия PRONOM_SIGNATURE_VERSION. Программа не
выполняет полную сигнатурную проверку DROID: идентификатор выбирается по
расширению и сведениям из заголовка файла (версия PDF, JFIF/EXIF и т. п.).
Если однозначно выбрать идентификатор нельзя, он не указывается.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PRONOM_SIGNATURE_VERSION = "125"
PRONOM_URL = "https://www.nationalarchives.gov.uk/PRONOM/{puid}"

# Виды файлов (п. 33.14 правил).
VIDEO = "video"
AUDIO = "audio"
IMAGE = "image"
TEXT = "text"
OTHER = "other"

CATEGORY_LABELS = {
    VIDEO: "Видео",
    AUDIO: "Аудио",
    IMAGE: "Изображение",
    TEXT: "Текстовый документ",
    OTHER: "Другое",
}


@dataclass(frozen=True)
class FormatInfo:
    name: str                    # название формата по-русски
    category: str
    mime: str = ""
    puid: str = ""               # идентификатор PRONOM, если он однозначен
    pronom_name: str = ""
    # Замечания о пригодности для длительного хранения (п. 33.10).
    notes: tuple[str, ...] = field(default_factory=tuple)


NOTE_PROPRIETARY = "Закрытый (проприетарный) формат: для длительного хранения рекомендуются открытые форматы (п. 33.10)."
NOTE_RAW = "RAW-файл фотокамеры: формат закрыт и зависит от производителя, для длительного хранения рекомендуются DNG или TIFF (п. 33.10)."
NOTE_LOSSY = "Формат использует сжатие с потерями; для мастер-копии рекомендуются форматы без потерь (п. 33.10)."

_F = FormatInfo

BY_EXTENSION: dict[str, FormatInfo] = {
    # Видео
    "mp4": _F("MPEG-4", VIDEO, "video/mp4", "fmt/199", "MPEG-4 Media File"),
    "m4v": _F("MPEG-4 (Apple M4V)", VIDEO, "video/x-m4v", "fmt/199", "MPEG-4 Media File"),
    "mov": _F("QuickTime", VIDEO, "video/quicktime", "x-fmt/384", "Quicktime"),
    "avi": _F("AVI (Audio Video Interleave)", VIDEO, "video/x-msvideo", "fmt/5", "Audio/Video Interleaved Format"),
    "mkv": _F("Matroska", VIDEO, "video/x-matroska", "fmt/569", "Matroska"),
    "webm": _F("WebM", VIDEO, "video/webm", "fmt/573", "WebM"),
    "wmv": _F("Windows Media Video", VIDEO, "video/x-ms-wmv", "fmt/133", "Windows Media Video", (NOTE_PROPRIETARY,)),
    "flv": _F("Flash Video", VIDEO, "video/x-flv", "x-fmt/382", "Macromedia FLV", (NOTE_PROPRIETARY,)),
    "mpg": _F("MPEG (программный поток)", VIDEO, "video/mpeg"),
    "mpeg": _F("MPEG (программный поток)", VIDEO, "video/mpeg"),
    "vob": _F("DVD Video Object", VIDEO, "video/mpeg"),
    "ts": _F("MPEG-2 Transport Stream", VIDEO, "video/mp2t", "fmt/585", "MPEG-2 Transport Stream"),
    "mts": _F("AVCHD (MPEG-2 Transport Stream)", VIDEO, "video/mp2t", "fmt/585", "MPEG-2 Transport Stream"),
    "m2ts": _F("AVCHD (MPEG-2 Transport Stream)", VIDEO, "video/mp2t", "fmt/585", "MPEG-2 Transport Stream"),
    "mxf": _F("MXF (Material Exchange Format)", VIDEO, "application/mxf"),
    "3gp": _F("3GPP", VIDEO, "video/3gpp"),
    "dv": _F("DV (Digital Video)", VIDEO, "video/x-dv"),
    # Аудио
    "wav": _F("WAVE", AUDIO, "audio/x-wav"),
    "bwf": _F("Broadcast WAVE", AUDIO, "audio/x-wav"),
    "mp3": _F("MP3 (MPEG-1/2 Audio Layer III)", AUDIO, "audio/mpeg", "fmt/134", "MPEG 1/2 Audio Layer 3"),
    "flac": _F("FLAC", AUDIO, "audio/flac", "fmt/279", "FLAC (Free Lossless Audio Codec)"),
    "aac": _F("AAC (ADTS)", AUDIO, "audio/aac", "fmt/1812", "Audio Data Transport Stream"),
    "m4a": _F("MPEG-4 Audio (M4A)", AUDIO, "audio/mp4", "fmt/2094", "M4A Audio"),
    "ogg": _F("Ogg", AUDIO, "audio/ogg"),
    "oga": _F("Ogg Audio", AUDIO, "audio/ogg"),
    "opus": _F("Ogg Opus", AUDIO, "audio/ogg", "fmt/946", "Ogg Opus Codec Compressed Multimedia File"),
    "aif": _F("AIFF", AUDIO, "audio/x-aiff", "fmt/414", "Audio Interchange File Format"),
    "aiff": _F("AIFF", AUDIO, "audio/x-aiff", "fmt/414", "Audio Interchange File Format"),
    "wma": _F("Windows Media Audio", AUDIO, "audio/x-ms-wma", "fmt/132", "Windows Media Audio", (NOTE_PROPRIETARY,)),
    "amr": _F("AMR", AUDIO, "audio/amr"),
    # Изображения
    "jpg": _F("JPEG", IMAGE, "image/jpeg"),
    "jpeg": _F("JPEG", IMAGE, "image/jpeg"),
    "jpe": _F("JPEG", IMAGE, "image/jpeg"),
    "tif": _F("TIFF", IMAGE, "image/tiff", "fmt/353", "Tagged Image File Format"),
    "tiff": _F("TIFF", IMAGE, "image/tiff", "fmt/353", "Tagged Image File Format"),
    "png": _F("PNG", IMAGE, "image/png"),
    "gif": _F("GIF", IMAGE, "image/gif"),
    "bmp": _F("BMP (Windows Bitmap)", IMAGE, "image/bmp"),
    "jp2": _F("JPEG 2000 (JP2)", IMAGE, "image/jp2", "x-fmt/392", "JP2 (JPEG 2000 part 1)"),
    "j2k": _F("JPEG 2000 (кодовый поток)", IMAGE, "image/j2k"),
    "webp": _F("WebP", IMAGE, "image/webp"),
    "heic": _F("HEIC (High Efficiency Image)", IMAGE, "image/heic", "fmt/1101", "High Efficiency Image File Format", (NOTE_LOSSY,)),
    "heif": _F("HEIF (High Efficiency Image)", IMAGE, "image/heif", "fmt/1101", "High Efficiency Image File Format", (NOTE_LOSSY,)),
    "psd": _F("Adobe Photoshop", IMAGE, "image/vnd.adobe.photoshop", notes=(NOTE_PROPRIETARY,)),
    "dng": _F("DNG (Digital Negative)", IMAGE, "image/dng"),
    "cr2": _F("Canon RAW 2", IMAGE, "image/x-canon-cr2", "fmt/592", "Canon RAW", (NOTE_RAW,)),
    "cr3": _F("Canon RAW 3", IMAGE, "image/x-canon-cr3", "fmt/1595", "Canon Raw", (NOTE_RAW,)),
    "crw": _F("Canon RAW", IMAGE, "image/x-canon-crw", notes=(NOTE_RAW,)),
    "nef": _F("Nikon RAW (NEF)", IMAGE, "image/x-nikon-nef", "fmt/202", "Nikon Digital SLR Camera Raw Image File", (NOTE_RAW,)),
    "nrw": _F("Nikon RAW (NRW)", IMAGE, "image/x-nikon-nrw", notes=(NOTE_RAW,)),
    "arw": _F("Sony RAW (ARW)", IMAGE, "image/x-sony-arw", notes=(NOTE_RAW,)),
    "rw2": _F("Panasonic RAW", IMAGE, "image/x-panasonic-rw2", "fmt/662", "Panasonic Raw", (NOTE_RAW,)),
    "orf": _F("Olympus RAW", IMAGE, "image/x-olympus-orf", "fmt/668", "Olympus RAW", (NOTE_RAW,)),
    "raf": _F("Fujifilm RAW", IMAGE, "image/x-fuji-raf", notes=(NOTE_RAW,)),
    "pef": _F("Pentax RAW", IMAGE, "image/x-pentax-pef", notes=(NOTE_RAW,)),
    # Текстовые документы
    "txt": _F("Текст без форматирования", TEXT, "text/plain", "x-fmt/111", "Plain Text File"),
    "csv": _F("CSV (значения через запятую)", TEXT, "text/csv", "x-fmt/18", "Comma Separated Values"),
    "md": _F("Markdown", TEXT, "text/markdown", "fmt/1149", "Markdown"),
    "htm": _F("HTML", TEXT, "text/html"),
    "html": _F("HTML", TEXT, "text/html"),
    "xml": _F("XML", TEXT, "application/xml"),
    "pdf": _F("PDF", TEXT, "application/pdf"),
    "docx": _F("Microsoft Word (DOCX, Office Open XML)", TEXT,
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "fmt/412", "Microsoft Word for Windows"),
    "doc": _F("Microsoft Word 97–2003 (DOC)", TEXT, "application/msword", notes=(NOTE_PROPRIETARY,)),
    "rtf": _F("RTF (Rich Text Format)", TEXT, "application/rtf"),
    "odt": _F("OpenDocument Text (ODT)", TEXT, "application/vnd.oasis.opendocument.text"),
    "ods": _F("OpenDocument Spreadsheet (ODS)", TEXT, "application/vnd.oasis.opendocument.spreadsheet"),
    "odp": _F("OpenDocument Presentation (ODP)", TEXT, "application/vnd.oasis.opendocument.presentation"),
    "xlsx": _F("Microsoft Excel (XLSX)", TEXT,
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "fmt/214", "Microsoft Excel for Windows"),
    "pptx": _F("Microsoft PowerPoint (PPTX)", TEXT,
               "application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "fmt/215", "Microsoft Powerpoint for Windows"),
    "xls": _F("Microsoft Excel 97–2003 (XLS)", TEXT, "application/vnd.ms-excel", notes=(NOTE_PROPRIETARY,)),
    "ppt": _F("Microsoft PowerPoint 97–2003 (PPT)", TEXT, "application/vnd.ms-powerpoint", notes=(NOTE_PROPRIETARY,)),
    "epub": _F("EPUB", TEXT, "application/epub+zip", "fmt/483", "ePub Format"),
    "djvu": _F("DjVu", TEXT, "image/vnd.djvu", "fmt/255", "DjVu File Format"),
}

# Уточнение идентификатора PRONOM по сведениям из файла.
PDF_VERSIONS = {
    "1.0": "fmt/14", "1.1": "fmt/15", "1.2": "fmt/16", "1.3": "fmt/17",
    "1.4": "fmt/18", "1.5": "fmt/19", "1.6": "fmt/20", "1.7": "fmt/276", "2.0": "fmt/1129",
}
PDFA_VERSIONS = {
    "1a": "fmt/95", "1b": "fmt/354", "2a": "fmt/476", "2b": "fmt/477", "2u": "fmt/478",
    "3a": "fmt/479", "3b": "fmt/480", "3u": "fmt/481", "4": "fmt/1910", "4e": "fmt/1911", "4f": "fmt/1912",
}
JFIF_VERSIONS = {"1.00": "fmt/42", "1.01": "fmt/43", "1.02": "fmt/44"}
EXIF_JPEG_VERSIONS = {"2.0": "x-fmt/398", "2.1": "x-fmt/390", "2.2": "x-fmt/391", "2.21": "fmt/645"}
EXIF_23_PUID = "fmt/1507"  # Exchangeable Image File Format (Compressed) 2.3.x
GIF_VERSIONS = {"87a": "fmt/3", "89a": "fmt/4"}
WEBP_KINDS = {"lossy": "fmt/566", "lossless": "fmt/567", "extended": "fmt/568"}
BMP_VERSIONS = {"2.0": "fmt/115", "3.0": "fmt/116", "4.0": "fmt/118", "5.0": "fmt/119"}
WAVE_KINDS = {"PCMWAVEFORMAT": "fmt/141", "WAVEFORMATEX": "fmt/142", "WAVEFORMATEXTENSIBLE": "fmt/143"}
BWF_VERSIONS = {"0": "fmt/1", "1": "fmt/2", "2": "fmt/527"}
ODF_VERSIONS = {
    "odt": {"1.0": "fmt/136", "1.1": "fmt/290", "1.2": "fmt/291", "1.3": "fmt/1756", "1.4": "fmt/2044"},
    "ods": {"1.0": "fmt/137", "1.1": "fmt/294", "1.2": "fmt/295"},
    "odp": {"1.0": "fmt/138", "1.1": "fmt/292", "1.2": "fmt/293", "1.3": "fmt/1754"},
}
DOC_OLE_PUID = "fmt/40"  # Microsoft Word Document 97-2003


def lookup(extension: str) -> FormatInfo:
    ext = extension.lower().lstrip(".")
    return BY_EXTENSION.get(ext, FormatInfo(name=ext.upper() if ext else "без расширения", category=OTHER))


def pronom_url(puid: str) -> str:
    return PRONOM_URL.format(puid=puid)

# Названия в реестре PRONOM для идентификаторов, которые зависят от версии.
PRONOM_NAMES = {
    **{puid: f"Acrobat PDF {v} - Portable Document Format" for v, puid in PDF_VERSIONS.items() if v != "2.0"},
    "fmt/1129": "PDF 2.0 - Portable Document Format",
    **{puid: f"Acrobat PDF/A - Portable Document Format {v}" for v, puid in PDFA_VERSIONS.items()},
    **{puid: f"JPEG File Interchange Format {v}" for v, puid in JFIF_VERSIONS.items()},
    **{puid: f"Exchangeable Image File Format (Compressed) {v}" for v, puid in EXIF_JPEG_VERSIONS.items()},
    EXIF_23_PUID: "Exchangeable Image File Format (Compressed) 2.3.x",
    **{puid: f"Graphics Interchange Format {v}" for v, puid in GIF_VERSIONS.items()},
    **{puid: f"WebP {k.capitalize()}" for k, puid in WEBP_KINDS.items()},
    **{puid: f"Windows Bitmap {v}" for v, puid in BMP_VERSIONS.items()},
    **{puid: f"Waveform Audio ({k})" for k, puid in WAVE_KINDS.items()},
    **{puid: f"Broadcast WAVE {v} Generic" for v, puid in BWF_VERSIONS.items()},
    **{puid: f"OpenDocument Text {v}" for v, puid in ODF_VERSIONS["odt"].items()},
    **{puid: f"OpenDocument Spreadsheet {v}" for v, puid in ODF_VERSIONS["ods"].items()},
    **{puid: f"OpenDocument Presentation {v}" for v, puid in ODF_VERSIONS["odp"].items()},
    DOC_OLE_PUID: "Microsoft Word Document 97-2003",
    "fmt/436": "Digital Negative Format (DNG) 1.0", "fmt/152": "Digital Negative Format (DNG) 1.1",
    "fmt/437": "Digital Negative Format (DNG) 1.2", "fmt/438": "Digital Negative Format (DNG) 1.3",
    "fmt/730": "Digital Negative Format (DNG) 1.4", "fmt/1841": "Digital Negative Format (DNG) 1.5",
    "fmt/1842": "Digital Negative Format (DNG) 1.6", "fmt/1943": "Digital Negative Format (DNG) 1.7",
}
