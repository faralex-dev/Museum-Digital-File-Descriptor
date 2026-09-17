"""PDF: версия, PDF/A, количество страниц, текстовый слой (через pypdf)."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from .. import formats, textfmt
from ..model import ProbeResult
from . import text as textprobe

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

TEXT_PAGE_LIMIT = 500      # страниц, из которых извлекается текст
TEXT_TIME_LIMIT = 60.0     # секунд на извлечение текста

PDFA_PART = re.compile(rb"pdfaid:part(?:>|=\")\s*(\d)")
PDFA_CONF = re.compile(rb"pdfaid:conformance(?:>|=\")\s*([A-Za-z])")

logging.getLogger("pypdf").setLevel(logging.ERROR)


def _header_version(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(1024)
    match = re.search(rb"%PDF-(\d\.\d)", head)
    return match.group(1).decode() if match else ""


def _xmp_raw(reader) -> bytes:
    try:
        meta = reader.trailer["/Root"].get("/Metadata")
        return meta.get_object().get_data() if meta is not None else b""
    except Exception:  # noqa: BLE001
        return b""


def probe(path: Path, result: ProbeResult) -> ProbeResult:
    version = _header_version(path)
    if PdfReader is None:
        result.warnings.append("Пакет pypdf не установлен: сведения о PDF не получены.")
        return result
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            opened = reader.decrypt("") != 0
        except Exception:  # noqa: BLE001
            opened = False
        if opened:
            result.notes.append("PDF зашифрован (есть ограничения прав): такие файлы не рекомендуются для хранения (п. 33.10).")
        else:
            result.notes.append("PDF защищён паролем: такие файлы не рекомендуются для хранения (п. 33.10).")
            result.add("pdf_version", "Версия PDF", version)
            return result

    catalog_version = reader.trailer["/Root"].get("/Version")
    if catalog_version:
        version = str(catalog_version).lstrip("/")
    result.format_version = version
    result.puid = formats.PDF_VERSIONS.get(version, "")
    result.add("pdf_version", "Версия PDF", version)

    xmp = _xmp_raw(reader)
    part = PDFA_PART.search(xmp)
    if part:
        level = part.group(1).decode()
        conf = PDFA_CONF.search(xmp)
        level += conf.group(1).decode().lower() if conf else ""
        result.format_name = f"PDF/A-{level}"
        result.format_version = f"PDF/A-{level}"
        result.puid = formats.PDFA_VERSIONS.get(level, "")
        result.add("pdfa", "Соответствие PDF/A", f"PDF/A-{level} (заявлено в метаданных файла)")
    else:
        result.notes.append("Файл не заявлен как PDF/A: для длительного хранения документов рекомендуется PDF/A.")

    pages = len(reader.pages)
    result.add("pages", "Количество страниц", pages)

    info = reader.metadata or {}
    producer = info.get("/Producer") or info.get("/Creator")
    result.add("application", "Программа", producer)
    try:
        created = info.creation_date if info else None
    except Exception:  # noqa: BLE001
        created = None
    if created:
        result.content_created = textfmt.any_date(created)
        result.add("doc_created", "Дата создания документа (по свойствам файла)", result.content_created)

    lang = reader.trailer["/Root"].get("/Lang")
    declared = ""
    if lang:
        from .office import _lang_name
        declared = _lang_name(str(lang))

    if pages > TEXT_PAGE_LIMIT:
        result.add("text_layer", "Текстовый слой", f"не проверялся (больше {TEXT_PAGE_LIMIT} страниц)")
        result.add("language", "Язык", declared)
        return result

    started = time.monotonic()
    parts = []
    for n, page in enumerate(reader.pages):
        if time.monotonic() - started > TEXT_TIME_LIMIT:
            result.warnings.append(f"Текст извлечён только из {n} страниц: превышено время.")
            break
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            parts.append("")
    body = "\n".join(parts)
    if body.strip():
        result.add("text_layer", "Текстовый слой", "есть")
        textprobe.add_text_stats(result, body, declared)
    else:
        result.add("text_layer", "Текстовый слой", "нет (вероятно, скан без распознавания)")
        result.add("language", "Язык", declared)
    return result
