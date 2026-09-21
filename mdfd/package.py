"""Единица хранения (п. 33.16): поиск файлов мастер-копии и создание описания."""
from __future__ import annotations

import logging
import os
import re
import threading
import unicodedata
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


DEFAULT_SEPARATOR = "_"


def split_name(name: str, separator: str = DEFAULT_SEPARATOR) -> tuple[str, str]:
    """Учётный номер и классификатор из имени папки или файла.

    'ГМИГ КП ЭФ-55_Петров А.А._Соловки' -> ('ГМИГ КП ЭФ-55', 'Петров А.А._Соловки').
    Пустой разделитель — номером считается всё имя.
    """
    if not separator:
        return name.strip(), ""
    number, _, rest = name.partition(separator)
    return number.strip(), rest.strip()


def natural_key(name: str):
    """Порядок «как у человека»: стр_2 раньше стр_10 (а не 1, 10, 100, 101, 2 …)."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
            for part in re.split(r"(\d+)", name)]


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


def collect_files(folder: Path, warnings: list[str] | None = None) -> list[Path]:
    """Все файлы мастер-копии в папке (с подпапками), в стабильном порядке.

    Пропускаются служебные файлы, символические ссылки и подпапки, в которых
    уже есть своё описание (это отдельные предметы). О пропущенном
    сообщается в warnings.
    """
    warnings = warnings if warnings is not None else []
    folder = Path(folder)
    found = []
    for dirpath, dirnames, filenames in os.walk(folder):
        here = Path(dirpath)
        keep = []
        for d in sorted(dirnames, key=natural_key):
            sub = here / d
            if d.startswith("."):
                continue
            if sub.is_symlink():
                warnings.append(f"Ссылка на папку пропущена: {sub.relative_to(folder).as_posix()}")
            elif checksums.files_in(sub):
                warnings.append(f"Подпапка «{sub.relative_to(folder).as_posix()}» — отдельный предмет "
                                "со своим описанием, её файлы не включены.")
            else:
                keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames, key=natural_key):
            path = here / name
            if path.is_symlink():
                warnings.append(f"Символическая ссылка пропущена: {path.relative_to(folder).as_posix()}")
            elif path.is_file() and not is_service_file(path):
                found.append(path)
    return found


def nfc(text: str) -> str:
    """Имена в описаниях — в нормальной форме NFC. macOS может хранить «й» как
    «и» + знак краткости (NFD); без приведения такие имена не совпадут на Windows."""
    return unicodedata.normalize("NFC", text)


_DRIVE = re.compile(r"^[A-Za-z]:([\\/]|$)")  # «C:\…», но не «a:b.png»


def is_safe_relpath(relpath: str) -> bool:
    """Путь из файла контрольных сумм не должен выходить за пределы папки предмета."""
    parts = relpath.replace("\\", "/").split("/")
    return (bool(relpath) and not relpath.startswith(("/", "\\")) and not _DRIVE.match(relpath)
            and all(p not in ("", ".", "..") for p in parts))


def resolve(root: Path, relpath: str) -> Path | None:
    """Находит файл по пути из описания, не различая формы NFC/NFD.
    Возвращает None, если файла нет или путь небезопасен."""
    if not is_safe_relpath(relpath):
        return None
    parts = relpath.replace("\\", "/").split("/")
    direct = root.joinpath(*parts)
    if direct.exists():
        return direct
    current = root
    for part in parts:
        try:
            match = next((c for c in current.iterdir() if nfc(c.name) == nfc(part)), None)
        except OSError:
            return None
        if match is None:
            return None
        current = match
    return current


def _item_info(template: ItemInfo, name: str, use_template_number: bool,
               separator: str = DEFAULT_SEPARATOR) -> ItemInfo:
    number, classifier = split_name(name, separator)
    info = replace(template)
    if not (use_template_number and template.accession_number):
        info.accession_number = number
        info.classifier = classifier
    return info


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def plan(source: Path, mode: str, template: ItemInfo, separator: str = DEFAULT_SEPARATOR) -> Plan:
    """Разбивает источник на предметы. Учётный номер берётся из имени папки
    (часть до первого разделителя, по умолчанию «_»), если он не задан явно
    для единственного предмета."""
    source = Path(source)
    result = Plan()
    if source.is_file():
        info = _item_info(template, Path(source.stem).name, True, separator)
        result.items.append(Item(source.parent, source.name, info, [source]))
        return result
    if not source.is_dir():
        result.warnings.append(f"Путь не найден: {source}")
        return result

    if mode == MODE_FOLDER:
        info = _item_info(template, source.name, True, separator)
        result.items.append(Item(source, source.name, info, collect_files(source, result.warnings)))
    elif mode == MODE_SUBFOLDERS:
        for child in sorted(source.iterdir()):
            if child.is_dir() and not is_hidden(child) and not child.is_symlink():
                info = _item_info(template, child.name, False, separator)
                result.items.append(Item(child, child.name, info, collect_files(child, result.warnings)))
            elif child.is_file() and not is_service_file(child):
                result.warnings.append(f"Файл вне папки предмета пропущен: {child.name}")
    elif mode == MODE_FILES:
        for path in collect_files(source, result.warnings):
            info = _item_info(template, Path(path.stem).name, False, separator)
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
    return nfc(path.relative_to(item.root).as_posix())


def _safe_datetime(timestamp) -> datetime | None:
    """Дата из файловой системы. Повреждённые даты (до 1970 года на Windows,
    далёкое будущее) не должны останавливать работу."""
    if timestamp is None:
        return None
    try:
        return textfmt.local_datetime(timestamp)
    except (OverflowError, OSError, ValueError):
        return None


def _file_times(path: Path) -> tuple[datetime | None, datetime | None]:
    st = path.stat()
    birth = getattr(st, "st_birthtime", None)
    if birth is None and os.name == "nt":
        birth = st.st_ctime
    return _safe_datetime(birth), _safe_datetime(st.st_mtime)


BAD_NAME_CHARS = ("\n", "\r")


class DescribeError(Exception):
    """Ошибка с понятным для хранителя текстом."""


def _read_error(exc: OSError, relpath: str) -> DescribeError:
    if isinstance(exc, PermissionError):
        return DescribeError(f"Нет доступа к файлу «{relpath}» (недостаточно прав).")
    if isinstance(exc, FileNotFoundError):
        return DescribeError(f"Файл «{relpath}» исчез во время работы.")
    return DescribeError(f"Не удалось прочитать файл «{relpath}»: {exc.strerror or exc}. "
                         "Возможна неисправность носителя.")


def _write_error(exc: OSError, folder: Path) -> DescribeError:
    if isinstance(exc, PermissionError):
        return DescribeError(f"Нет прав на запись в папку «{folder.name}».")
    return DescribeError(f"Не удалось записать описание в папку «{folder.name}»: {exc.strerror or exc}.")


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
            if nfc(relpath) == nfc(item.xml_path.name):
                continue
            path = resolve(item.root, relpath)
            if path is None:
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
        except DescribeError as exc:
            return Report(item, ERROR, str(exc))
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

        bad_names = [_relpath(item, p) for p in item.sources if any(c in p.name for c in BAD_NAME_CHARS)]
        if bad_names:
            shown = ", ".join(repr(n) for n in bad_names)
            return Report(item, ERROR, f"В имени файла есть перевод строки: {shown}. Переименуйте файл — "
                                       "такое имя нельзя записать в файл контрольных сумм, и Windows его не откроет.")

        warnings: list[str] = []
        item.files = []
        for path in item.sources:
            if self.cancel.is_set():
                raise hashing.Cancelled()
            relpath = _relpath(item, path)
            try:
                before = path.stat()
                sums = hashing.hash_file(path, self.algorithms, self._progress_for(relpath), self.cancel)
                after = path.stat()
            except OSError as exc:
                raise _read_error(exc, relpath) from exc
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise DescribeError(f"Файл «{relpath}» изменялся во время чтения (копирование ещё идёт?). "
                                    "Дождитесь окончания и повторите.")
            if after.st_size == 0:
                warnings.append(f"{relpath}: файл пустой (0 байт).")
            probe = probe_file(path)
            warnings += [f"{relpath}: {w}" for w in probe.warnings]
            created, modified = _file_times(path)
            if modified is None:
                warnings.append(f"{relpath}: дата файла повреждена и не записана.")
            item.files.append(FileRecord(path, relpath, after.st_size, created, modified, sums, probe,
                                         path.suffix.lstrip(".")))

        # Всё готовится в памяти и записывается в конце одним шагом: при сбое
        # не остаётся XML без файла контрольных сумм.
        now = textfmt.local_datetime(datetime.now().timestamp())
        xml_data = xmlio.render(item, now)
        files = {item.xml_path: xml_data,
                 item.checksums_path: checksums.render(item, hashing.hash_bytes(xml_data, self.algorithms), now)}
        if self.write_kamis:
            files[item.kamis_path] = kamis.render(item)
        try:
            outputs = xmlio.write_all(files)
        except OSError as exc:
            raise _write_error(exc, item.root) from exc
        n = len(item.files)
        message = f"Описано {n} {textfmt.plural(n, 'файл', 'файла', 'файлов')}."
        return Report(item, OK, message, warnings + self._item_warnings(item), outputs)

    @staticmethod
    def _item_warnings(item: Item) -> list[str]:
        """Подозрительное в предмете в целом: одинаковые файлы, странный учётный номер."""
        out = []
        same: dict[tuple, list[str]] = {}
        for record in item.files:
            if record.size:
                same.setdefault((record.size, tuple(sorted(record.checksums.items()))), []).append(record.relpath)
        for names in same.values():
            if len(names) > 1:
                out.append("Файлы с одинаковым содержимым (побайтно): " + ", ".join(names)
                           + ". Возможно, лишняя копия — проверьте.")
        number = item.info.accession_number
        if number and not any(ch.isdigit() for ch in number):
            out.append(f"В учётном номере «{number}» нет цифр — возможно, разделитель разрезал номер. "
                       "Проверьте разделитель на вкладке «Настройки» или введите номер вручную.")
        return out


def total_bytes(items: list[Item]) -> int:
    total = 0
    for item in items:
        for path in item.sources:
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total
