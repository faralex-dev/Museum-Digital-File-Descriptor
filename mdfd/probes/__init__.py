"""Анализ содержимого файлов: выбор модуля по виду файла."""
from __future__ import annotations

from pathlib import Path

from .. import formats
from ..model import ProbeResult
from . import image, media, office, pdf, text

PLAIN_TEXT = {".txt", ".csv", ".md", ".htm", ".html", ".xml", ".json", ".tsv"}
OFFICE = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".doc", ".xls", ".ppt", ".rtf"}


def probe_file(path: Path) -> ProbeResult:
    """Собирает технические сведения о файле. Ошибки анализа не прерывают работу:
    они попадают в warnings, а контрольные суммы и общие сведения всё равно будут записаны."""
    ext = path.suffix.lower()
    info = formats.lookup(ext)
    result = ProbeResult(
        category=info.category,
        format_name=info.name,
        puid=info.puid,
        pronom_name=info.pronom_name,
        mime=info.mime,
        notes=list(info.notes),
    )
    try:
        if info.category in (formats.VIDEO, formats.AUDIO):
            media.probe(path, result)
        elif info.category == formats.IMAGE:
            image.probe(path, result)
            if not result.props and media.available():
                # HEIC и другие форматы, которые Pillow не читает
                media_result = ProbeResult(category=formats.IMAGE)
                media.probe(path, media_result)
                result.props.extend(media_result.props)
        elif ext == ".pdf":
            pdf.probe(path, result)
        elif ext in OFFICE:
            office.probe(path, result)
        elif ext in PLAIN_TEXT:
            text.probe(path, result)
        elif info.category == formats.OTHER and media.available():
            # Незнакомое расширение: вдруг это медиафайл
            media.probe(path, result)
            if result.category == formats.OTHER:
                result.warnings.clear()
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(f"Технические сведения получены не полностью: {exc}")

    if result.puid and result.puid != info.puid:
        result.pronom_name = formats.PRONOM_NAMES.get(result.puid, "")
    return result
