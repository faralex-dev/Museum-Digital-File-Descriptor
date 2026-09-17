"""Памятка для заполнения КАМИС и сводная таблица (CSV).

Эти файлы вспомогательные: они не входят в единицу хранения и не
перечисляются в файле контрольных сумм.
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import formats, hashing, textfmt
from .model import FileRecord, Item
from .xmlio import atomic_write

# Порядок свойств в памятке — как в п. 33.14 правил.
ORDER = {
    formats.VIDEO: ["duration", "resolution", "video_bit_rate", "video_codec", "frame_rate"],
    formats.AUDIO: ["duration"],
    formats.IMAGE: ["compression", "pixel_size", "resolution"],
    formats.TEXT: ["encoding", "language", "characters", "pages", "slides", "sheets"],
}
# Подписи для аудиодорожки — как в п. 33.14.
AUDIO_TRACK_LABELS = {
    "codec": "Аудиокодек",
    "bit_rate": "Аудиобитрейт",
    "channels": "Количество каналов",
    "sampling_rate": "Частота",
}


def _prop_map(props) -> dict[str, str]:
    return {p.key: p.text for p in props}


def _extension(record: FileRecord) -> str:
    return record.extension.lower() or "без расширения"


def file_lines(record: FileRecord, topography: str) -> list[str]:
    probe = record.probe
    out = [
        f"Имя файла мастер-копии: {record.relpath}",
        f"Формат: {_extension(record)} ({probe.format_name})",
        f"Размер: {textfmt.size(record.size)}",
        f"Дата создания: {record.date_created.strftime('%d.%m.%Y %H:%M:%S')}",
    ]
    for key, value in record.checksums.items():
        out.append(f"Контрольная сумма {hashing.ALGORITHMS[key].label}: {value}")
    if topography:
        out.append(f"Место хранения: {topography}")

    props = _prop_map(probe.props)
    labels = {p.key: p.label for p in probe.props}
    extra = [f"{labels[k]}: {props[k]}" for k in ORDER.get(probe.category, []) if k in props]
    for n, track in enumerate(t for t in probe.tracks if t.kind == "audio"):
        values = _prop_map(track.props)
        if n:
            extra.append(f"{track.label}:")
        extra += [f"{label}: {values[k]}" for k, label in AUDIO_TRACK_LABELS.items() if k in values]
    if extra:
        out.append("")
        out.append(f"Дополнительные сведения ({formats.CATEGORY_LABELS.get(probe.category, '')}):")
        out += [f"  {line}" for line in extra]
    return out


def write(item: Item) -> Path:
    info = item.info
    lines = ["ПАМЯТКА ДЛЯ ЗАПОЛНЕНИЯ КАМИС (вспомогательный файл, не входит в единицу хранения)", ""]
    for label, value in (("Учётный номер", info.accession_number), ("Наименование", info.title),
                         ("Описание", info.description), ("Носитель", info.carrier),
                         ("Сведения о нормализации", info.normalization)):
        if value:
            lines.append(f"{label}: {value}")
    lines.append(f"Файл метаданных: {item.xml_path.name}")
    lines.append(f"Файл контрольных сумм: {item.checksums_path.name}")
    for n, record in enumerate(item.files, 1):
        lines.append("")
        lines.append(f"=== Файл {n} из {len(item.files)} ===" if len(item.files) > 1 else "=== Файл мастер-копии ===")
        lines += file_lines(record, info.topography)
        for note in dict.fromkeys(record.probe.notes):
            lines.append(f"Замечание: {note}")
    lines.append("")
    atomic_write(item.kamis_path, "\n".join(lines).encode("utf-8"))
    return item.kamis_path


CSV_COLUMNS = [
    "Учётный номер", "Папка предмета", "Файл", "Формат", "Вид", "Размер", "Размер (байт)",
    "Дата создания", "SHA-256", "ГОСТ 34.11-2018", "Место хранения",
    "Продолжительность", "Разрешение", "Битрейт видео", "Кодек видео", "Частота кадров",
    "Аудиокодек", "Битрейт аудио", "Каналы", "Частота дискретизации",
    "Метод сжатия", "Размер изображения", "Кодировка", "Язык", "Количество знаков", "Количество страниц",
    "Замечания",
]


def csv_rows(item: Item):
    for record in item.files:
        p = _prop_map(record.probe.props)
        audio = next((_prop_map(t.props) for t in record.probe.tracks if t.kind == "audio"), {})
        yield {
            "Учётный номер": item.info.accession_number,
            "Папка предмета": str(item.root),
            "Файл": record.relpath,
            "Формат": _extension(record),
            "Вид": formats.CATEGORY_LABELS.get(record.probe.category, ""),
            "Размер": textfmt.size(record.size),
            "Размер (байт)": record.size,
            "Дата создания": record.date_created.strftime("%d.%m.%Y %H:%M:%S"),
            "SHA-256": record.checksums.get("sha256", ""),
            "ГОСТ 34.11-2018": record.checksums.get("gost256", ""),
            "Место хранения": item.info.topography,
            "Продолжительность": p.get("duration", ""),
            "Разрешение": p.get("resolution", ""),
            "Битрейт видео": p.get("video_bit_rate", ""),
            "Кодек видео": p.get("video_codec", ""),
            "Частота кадров": p.get("frame_rate", ""),
            "Аудиокодек": audio.get("codec", ""),
            "Битрейт аудио": audio.get("bit_rate", ""),
            "Каналы": audio.get("channels", ""),
            "Частота дискретизации": audio.get("sampling_rate", ""),
            "Метод сжатия": p.get("compression", ""),
            "Размер изображения": p.get("pixel_size", ""),
            "Кодировка": p.get("encoding", ""),
            "Язык": p.get("language", ""),
            "Количество знаков": p.get("characters", ""),
            "Количество страниц": p.get("pages", ""),
            "Замечания": " ".join(dict.fromkeys(record.probe.notes)),
        }


def write_csv(items: list[Item], path: Path) -> Path:
    """Сводная таблица. Кодировка UTF-8 с BOM и разделитель «;» — так её сразу открывает Excel."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        for item in items:
            writer.writerows(csv_rows(item))
    return path
