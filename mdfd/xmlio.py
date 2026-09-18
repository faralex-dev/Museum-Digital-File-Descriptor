"""Файл метаданных (XML, UTF-8) — формат 2.0, описан в docs/format-2.0.md."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from . import APP_NAME, FORMAT_VERSION, __version__, formats, hashing, textfmt
from .model import FileRecord, Item, Prop

ROOT_TAG = "DigitalMuseumItem"
LEGACY_ROOT_TAGS = {"GMIG"}  # версия 1.x


# Символы, недопустимые в XML 1.0: управляющие (кроме табуляции и переводов
# строки), одиночные суррогаты (так Python представляет непрочитанные байты
# в именах файлов) и U+FFFE/U+FFFF. Они встречаются в тексте, вставленном из
# Word, и в метаданных камер — без очистки XML становится нечитаемым.
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def clean_text(value) -> str:
    return _INVALID_XML.sub("\ufffd", str(value))


def _el(parent, tag: str, text=None, label: str | None = None, **attrs) -> ET.Element:
    clean = {k: clean_text(v) for k, v in attrs.items() if v not in (None, "")}
    if label:
        clean = {"label": label, **clean}
    element = ET.SubElement(parent, tag, clean)
    if text not in (None, ""):
        element.text = clean_text(text)
    return element


def _prop(parent, prop: Prop) -> None:
    _el(parent, "Property", prop.text, prop.label, key=prop.key, raw=prop.raw)


def _date(parent, tag: str, label: str, dt: datetime | None) -> None:
    if dt is not None:
        _el(parent, tag, textfmt.date_time(dt), label, iso=textfmt.iso(dt))


def _file(parent, n: int, record: FileRecord) -> None:
    probe = record.probe
    node = _el(parent, "File", n=n)
    _el(node, "FileName", record.name, "Имя файла мастер-копии")
    if record.relpath != record.name:
        _el(node, "RelativePath", record.relpath, "Путь в папке предмета")

    fmt_text = probe.format_name
    if probe.format_version and probe.format_version not in fmt_text:
        fmt_text += f", {probe.format_version}"
    _el(node, "Format", fmt_text, "Формат", extension=record.extension, mime=probe.mime)
    if probe.puid:
        _el(node, "FormatRegistry", probe.pronom_name or probe.puid, "Формат в реестре PRONOM",
            registry="PRONOM", puid=probe.puid, url=formats.pronom_url(probe.puid))
    _el(node, "Category", formats.CATEGORY_LABELS.get(probe.category, probe.category), "Вид файла",
        code=probe.category)
    _el(node, "Size", textfmt.size(record.size), "Размер", bytes=record.size)
    _date(node, "DateCreated", "Дата создания", record.date_created)
    _date(node, "DateModified", "Дата последнего изменения", record.modified)
    if probe.content_created:
        _el(node, "ContentDate", textfmt.any_date(probe.content_created),
            "Дата создания содержимого (по метаданным файла)")

    sums = _el(node, "Checksums", label="Контрольные суммы")
    for key, value in record.checksums.items():
        algo = hashing.ALGORITHMS[key]
        _el(sums, "Checksum", value, algo.label, algorithm=algo.tag)

    if probe.props:
        props = _el(node, "Properties", label="Технические характеристики")
        for prop in probe.props:
            _prop(props, prop)
    if probe.tracks:
        tracks = _el(node, "Tracks", label="Дорожки")
        for track in probe.tracks:
            t = _el(tracks, "Track", label=track.label, type=track.kind)
            for prop in track.props:
                _prop(t, prop)
    if probe.notes:
        notes = _el(node, "Preservation", label="Замечания о пригодности для длительного хранения")
        for note in dict.fromkeys(probe.notes):
            _el(notes, "Note", note)
    if probe.warnings:
        warns = _el(node, "Warnings", label="Предупреждения программы")
        for warning in probe.warnings:
            _el(warns, "Warning", warning)


def build(item: Item, created: datetime) -> ET.Element:
    root = ET.Element(ROOT_TAG, {"formatVersion": FORMAT_VERSION})
    _el(root, "Generator", APP_NAME, "Программа", version=__version__,
        hashBackend=hashing.BACKEND, pronomSignatureVersion=formats.PRONOM_SIGNATURE_VERSION)
    _date(root, "DescriptionCreated", "Дата создания описания", created)

    info = item.info
    node = _el(root, "Item", label="Сведения о предмете")
    # Идентификатор предмета обязателен (пп. 33.13–33.14 Единых правил) — элемент есть всегда, остальные только если заполнены.
    _el(node, "AccessionNumber", info.accession_number, "Учётный номер (КП)")
    for tag, value, label in (
        ("Museum", info.museum, "Музей"),
        ("Classifier", info.classifier, "Классификатор"),
        ("Title", info.title, "Наименование"),
        ("Description", info.description, "Описание"),
        ("Topography", info.topography, "Место хранения (топография)"),
        ("Carrier", info.carrier, "Носитель"),
        ("Normalization", info.normalization, "Сведения о нормализации"),
    ):
        if value:
            _el(node, tag, value, label)
    _el(node, "FolderName", item.root.name, "Папка предмета")

    files = _el(root, "Files", label="Файлы мастер-копии", count=len(item.files))
    for n, record in enumerate(item.files, 1):
        _file(files, n, record)
    return root


def render(item: Item, created: datetime) -> bytes:
    root = build(item, created)
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8") + b"\n"


def write_all(files: dict[Path, bytes]) -> list[Path]:
    """Записывает несколько файлов «всё или ничего»: сначала во временные файлы,
    затем переименовывает. Если записать не удалось, прежние файлы не тронуты,
    а временные удаляются."""
    temps: dict[Path, Path] = {}
    try:
        for path, data in files.items():
            tmp = path.with_name(f".{path.name}.tmp")
            temps[path] = tmp
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        for path, tmp in temps.items():
            os.replace(tmp, path)
    finally:
        for tmp in temps.values():
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
    return list(files)


def atomic_write(path: Path, data: bytes) -> None:
    """Запись через временный файл: при сбое старый файл остаётся целым."""
    write_all({path: data})


def root_tag(path: Path) -> str | None:
    """Тег корневого элемента XML (читается только начало файла)."""
    try:
        with open(path, "rb") as f:
            for _, elem in ET.iterparse(f, events=("start",)):
                return elem.tag
    except (OSError, ET.ParseError):
        return None
    return None


def is_description(path: Path) -> bool:
    """XML-описание, созданное этой программой (версии 2.x или 1.x)."""
    return path.suffix.lower() == ".xml" and root_tag(path) in ({ROOT_TAG} | LEGACY_ROOT_TAGS)


def read_checksums(path: Path) -> dict[str, dict[str, str]]:
    """Контрольные суммы из XML-описания: {путь файла: {ключ алгоритма: HEX}}.

    Понимает формат 2.x и формат версии 1.x (корневой элемент GMIG).
    """
    tree = ET.parse(path)
    root = tree.getroot()
    result: dict[str, dict[str, str]] = {}
    if root.tag == ROOT_TAG:
        for node in root.iterfind("Files/File"):
            name = node.findtext("RelativePath") or node.findtext("FileName") or ""
            sums = {}
            for cs in node.iterfind("Checksums/Checksum"):
                algo = hashing.algorithm_by_tag(cs.get("algorithm", ""))
                if algo and cs.text:
                    sums[algo.key] = cs.text.strip().upper()
            result[name] = sums
    elif root.tag in LEGACY_ROOT_TAGS:
        for node in root.iter():
            if node.tag == "fileName" and node.text:
                name = node.text.strip()
                sums = {}
                for h in root.iter("hash"):
                    algo = hashing.algorithm_by_tag(h.get("type", ""))
                    if algo and h.text:
                        sums[algo.key] = h.text.strip().upper()
                result[name] = sums
    return result
