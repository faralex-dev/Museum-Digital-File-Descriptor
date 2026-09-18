"""Файл контрольных сумм (п. 33.15 правил).

Формат 2.0 — строки вида «АЛГОРИТМ (имя файла) = значение» (BSD-формат,
его понимают shasum и sha1sum --check для строк SHA1). Строки,
начинающиеся с «#», — пояснения для человека.

Программа также читает файлы контрольных сумм версии 1.x.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import APP_NAME, FORMAT_VERSION, __version__, hashing, textfmt
from .model import CHECKSUMS_SUFFIX, Item
from .xmlio import atomic_write

HEADER = "# Контрольные суммы цифрового музейного предмета"
LINE_RE = re.compile(r"^(?P<algo>[A-Za-z0-9_.\-]+) \((?P<name>.*)\) = (?P<hex>[0-9A-Fa-f]+)\s*$")
LEGACY_MARK = "Контрольная сумма:"
LEGACY_LINE_RE = re.compile(r"^(?P<algo>[A-Za-z0-9_]+): (?P<hex>[0-9A-Fa-f]+)\s*$")
LEGACY_MAX_SIZE = 64 * 1024

@dataclass
class Entry:
    relpath: str
    algorithm: str   # ключ алгоритма
    value: str

@dataclass
class ChecksumFile:
    path: Path
    version: str                       # "2.0" или "1.x"
    entries: list[Entry] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.path.parent

    def by_file(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for e in self.entries:
            out.setdefault(e.relpath, {})[e.algorithm] = e.value
        return out

def _line(algo_key: str, relpath: str, value: str) -> str:
    return f"{hashing.ALGORITHMS[algo_key].tag} ({relpath}) = {value}"

def write(item: Item, xml_sums: dict[str, str], created: datetime) -> Path:
    lines = [
        HEADER,
        f"# Формат файла: {FORMAT_VERSION}. Создан: {textfmt.date_time(created)}, {APP_NAME} {__version__}.",
        f"# Предмет: {item.info.accession_number or item.base_name} (папка «{item.root.name}»).",
        "# Строки: АЛГОРИТМ (путь к файлу относительно этой папки) = контрольная сумма.",
        "# " + "; ".join(f"{hashing.ALGORITHMS[k].tag} — {hashing.ALGORITHMS[k].label}"
                         for k in dict.fromkeys(k for r in item.files for k in r.checksums)),
        "",
    ]
    for record in item.files:
        lines.append(f"# Мастер-копия: {record.relpath}, {textfmt.size(record.size)}")
        lines += [_line(k, record.relpath, v) for k, v in record.checksums.items()]
        lines.append("")
    lines.append(f"# Файл метаданных: {item.xml_path.name}")
    lines += [_line(k, item.xml_path.name, v) for k, v in xml_sums.items()]
    lines.append("")
    atomic_write(item.checksums_path, "\n".join(lines).encode("utf-8"))
    return item.checksums_path

def _parse_v2(path: Path, text: str) -> ChecksumFile:
    result = ChecksumFile(path, FORMAT_VERSION)
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        algo = hashing.algorithm_by_tag(match["algo"])
        if algo:
            result.entries.append(Entry(match["name"], algo.key, match["hex"].upper()))
    return result

def _parse_legacy(path: Path, text: str) -> ChecksumFile:
    """Формат 1.x. Файл принимается, только если он целиком состоит из блоков
    «имя файла / Контрольная сумма: / АЛГОРИТМ: значение…» — иначе это обычный
    текстовый документ, и он не должен пропасть из мастер-копий."""
    result = ChecksumFile(path, "1.x")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    i = 0
    while i < len(lines):
        if i + 2 >= len(lines) or lines[i + 1] != LEGACY_MARK:
            return ChecksumFile(path, "1.x")
        name = lines[i]
        i += 2
        found = 0
        while i < len(lines) and (match := LEGACY_LINE_RE.match(lines[i])):
            algo = hashing.algorithm_by_tag(match["algo"])
            if algo is None:
                return ChecksumFile(path, "1.x")
            result.entries.append(Entry(name, algo.key, match["hex"].upper()))
            found += 1
            i += 1
        if not found:
            return ChecksumFile(path, "1.x")
    return result


def parse(path: Path) -> ChecksumFile | None:
    """Читает файл контрольных сумм. Возвращает None, если это не он."""
    name = path.name.lower()
    if not name.endswith(".txt"):
        return None
    try:
        if name.endswith(CHECKSUMS_SUFFIX):
            text = path.read_text(encoding="utf-8-sig")
            return _parse_v2(path, text)
        if path.stat().st_size > LEGACY_MAX_SIZE:
            return None
        with open(path, "rb") as f:
            raw = f.read(LEGACY_MAX_SIZE)
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    if text.startswith(HEADER):
        return _parse_v2(path, text)
    if LEGACY_MARK in text:
        parsed = _parse_legacy(path, text)
        if parsed.entries:
            return parsed
    return None
