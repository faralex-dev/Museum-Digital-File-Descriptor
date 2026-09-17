"""Единица хранения (п. 33.16): поиск файлов мастер-копии и создание описания."""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import checksums, hashing, kamis, textfmt, xmlio
from .model import CHECKSUMS_SUFFIX, KAMIS_SUFFIX, FileRecord, Item, ItemInfo
from .probes import probe_file

log = logging.getLogger(__name__)

MODE_FOLDER = "folder"          # папка — один предмет
MODE_SUBFOLDERS = "subfolders"  # каждая подпапка — отдельный предмет
MODE_FILES = "files"            # каждый файл — отдельный предмет

MODE_LABELS = {
    MODE_FOLDER: "Папка — один предмет",
    MODE_SUBFOLDERS: "Каждая подпапка — отдельный предмет",
    MODE_FILES: "Каждый файл — отдельный предмет",
}

SYSTEM_NAMES = {".ds_store", "thumbs.db", "desktop.ini", ".localized", "icon\r"}
LEGACY_KAMIS_SUFFIX = "_kamis.txt"

OK, SKIPPED, ERROR, CANCELLED = "ok", "skipped", "error", "cancelled"
STATUS_LABELS = {OK: "Готово", SKIPPED: "Пропущено", ERROR: "Ошибка", CANCELLED: "Отменено"}


def split_name(name: str) -> tuple[str, str]:
    """'ГМИГ КП ЭФ-55_Петров А.А._Соловки' -> ('ГМИГ КП ЭФ-55', 'Петров А.А._Соловки')."""
    number, _, rest = name.partition("_")
    return number.strip(), rest.strip()


def is_hidden(path: Path) -> bool:
    name = path.name
    return name.startswith(".") or name.startswith("~$") or name.lower() in SYSTEM_NAMES


def is_service_file(path: Path) -> bool:
    """Файлы, которые не являются мастер-копией: описания, служебные и системные файлы."""
    if is_hidden(path):
        return True
    lower = path.name.lower()
    if lower.endswith((CHECKSUMS_SUFFIX, KAMIS_SUFFIX, LEGACY_KAMIS_SUFFIX)):
        return True
    if lower.endswith(".xml") and xmlio.is_description(path):
        return True
    if lower.endswith(".txt") and checksums.parse(path) is not None:
        return True
    return False


def collect_files(folder: Path) -> list[Path]:
    """Все файлы мастер-копии в папке (с подпапками), в стабильном порядке."""
    found = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_file() and not is_service_file(path):
                found.append(path)
    return found


def _item_info(template: ItemInfo, name: str, use_template_number: bool) -> ItemInfo:
    number, classifier = split_name(name)
    info = replace(template)
    if not (use_template_number and template.accession_number):
        info.accession_number = number
        info.classifier = classifier
    return info


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def plan(source: Path, mode: str, template: ItemInfo) -> Plan:
    """Разбивает источник на предметы. Учётный номер берётся из имени папки
    (часть до первого «_»), если он не задан явно для единственного предмета."""
    source = Path(source)
    result = Plan()
    if source.is_file():
        info = _item_info(template, Path(source.stem).name, True)
        result.items.append(Item(source.parent, source.name, info, [source]))
        return result
    if not source.is_dir():
        result.warnings.append(f"Путь не найден: {source}")
        return result

    if mode == MODE_FOLDER:
        info = _item_info(template, source.name, True)
        result.items.append(Item(source, source.name, info, collect_files(source)))
    elif mode == MODE_SUBFOLDERS:
        for child in sorted(source.iterdir()):
            if child.is_dir() and not is_hidden(child):
                info = _item_info(template, child.name, False)
                result.items.append(Item(child, child.name, info, collect_files(child)))
            elif child.is_file() and not is_service_file(child):
                result.warnings.append(f"Файл вне папки предмета пропущен: {child.name}")
    elif mode == MODE_FILES:
        for path in collect_files(source):
            info = _item_info(template, Path(path.stem).name, False)
            result.items.append(Item(path.parent, path.name, info, [path]))
    else:
        raise ValueError(f"Неизвестный режим: {mode}")
    return result


@dataclass
class Report:
    item: Item
    status: str
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    outputs: list[Path] = field(default_factory=list)


ProgressFn = Callable[[str, int], None]   # (текущий файл, прочитано байт с прошлого вызова)


def _relpath(item: Item, path: Path) -> str:
    return path.relative_to(item.root).as_posix()


def _file_times(path: Path) -> tuple[datetime | None, datetime]:
    st = path.stat()
    birth = getattr(st, "st_birthtime", None)
    if birth is None and os.name == "nt":
        birth = st.st_ctime
    created = textfmt.local_datetime(birth) if birth else None
    return created, textfmt.local_datetime(st.st_mtime)


class Describer:
    """Создаёт описания предметов: XML, файл контрольных сумм, памятку КАМИС."""

    def __init__(
        self,
        algorithms=hashing.DEFAULT_ALGORITHMS,
        overwrite: bool = False,
        write_kamis: bool = True,
        progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
    ):
        self.algorithms = tuple(algorithms)
        self.overwrite = overwrite
        self.write_kamis = write_kamis
        self.progress = progress
        self.cancel = cancel or threading.Event()

    # --- проверки перед записью ---

    def _check_outputs(self, item: Item) -> str | None:
        """Возвращает текст ошибки/пропуска или None, если можно писать."""
        existing = [p for p in (item.xml_path, item.checksums_path) if p.exists()]
        master_paths = {p.resolve() for p in item.sources}
        for target in (item.xml_path, item.checksums_path, item.kamis_path):
            if target.resolve() in master_paths:
                return f"ERROR:Имя файла описания совпадает с файлом мастер-копии: {target.name}"
        if item.xml_path.exists() and not xmlio.is_description(item.xml_path):
            return f"ERROR:Файл {item.xml_path.name} уже существует и не является описанием — не перезаписываю."
        if not existing:
            return None
        if not self.overwrite:
            return "SKIP:Описание уже есть (включите перезапись, чтобы создать заново)."
        if item.checksums_path.exists():
            parsed = checksums.parse(item.checksums_path)
            if parsed is not None:
                changed = self._changed_files(item, parsed)
                if changed:
                    return ("ERROR:Файлы изменились после прошлого описания: " + ", ".join(changed)
                            + ". Перезапись отменена — проведите сверку и выясните причину.")
        return None

    def _changed_files(self, item: Item, parsed: checksums.ChecksumFile) -> list[str]:
        changed = []
        for relpath, sums in parsed.by_file().items():
            path = item.root / relpath
            if path == item.xml_path:
                continue
            if not path.exists():
                changed.append(f"{relpath} (нет файла)")
                continue
            actual = hashing.hash_file(path, sums.keys(), self._progress_for(relpath), self.cancel)
            if any(actual[k] != v for k, v in sums.items()):
                changed.append(relpath)
        return changed

    def _progress_for(self, label: str):
        if self.progress is None:
            return None
        return lambda n: self.progress(label, n)

    # --- основная работа ---

    def describe(self, item: Item) -> Report:
        try:
            return self._describe(item)
        except hashing.Cancelled:
            return Report(item, CANCELLED, "Отменено пользователем.")
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка при описании %s", item.root)
            return Report(item, ERROR, f"{type(exc).__name__}: {exc}")

    def _describe(self, item: Item) -> Report:
        if not item.sources:
            return Report(item, ERROR, "В папке нет файлов мастер-копии.")
        verdict = self._check_outputs(item)
        if verdict:
            kind, _, text = verdict.partition(":")
            return Report(item, SKIPPED if kind == "SKIP" else ERROR, text)

        warnings: list[str] = []
        item.files = []
        for path in item.sources:
            if self.cancel.is_set():
                raise hashing.Cancelled()
            relpath = _relpath(item, path)
            size = path.stat().st_size
            if size == 0:
                warnings.append(f"{relpath}: файл пустой (0 байт).")
            sums = hashing.hash_file(path, self.algorithms, self._progress_for(relpath), self.cancel)
            probe = probe_file(path)
            warnings += [f"{relpath}: {w}" for w in probe.warnings]
            created, modified = _file_times(path)
            item.files.append(FileRecord(path, relpath, size, created, modified, sums, probe,
                                         path.suffix.lstrip(".")))

        now = textfmt.local_datetime(datetime.now().timestamp())
        outputs = [xmlio.write(item, now)]
        xml_sums = hashing.hash_file(item.xml_path, self.algorithms)
        outputs.append(checksums.write(item, xml_sums, now))
        if self.write_kamis:
            outputs.append(kamis.write(item))
        n = len(item.files)
        message = f"Описано {n} {textfmt.plural(n, 'файл', 'файла', 'файлов')}."
        return Report(item, OK, message, warnings, outputs)


def total_bytes(items: list[Item]) -> int:
    total = 0
    for item in items:
        for path in item.sources:
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total
