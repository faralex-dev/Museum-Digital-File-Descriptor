"""Сверка: проверка технического состояния цифровых музейных предметов (пп. 33.5–33.8).

Для каждого файла контрольных сумм программа:
  * читает каждый файл целиком и пересчитывает контрольные суммы
    (это одновременно проверка на сбои чтения);
  * сравнивает результат с записанными значениями;
  * по желанию пробует открыть файл (структурная целостность);
  * сообщает о файлах, которые лежат в папке, но не перечислены;
  * при сверке резервной копии — проверяет копию по суммам мастер-копии.
"""
from __future__ import annotations

import csv
import logging
import os
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__, checksums, hashing, textfmt, xmlio
from .model import CHECKSUMS_SUFFIX

log = logging.getLogger(__name__)

OK = "ok"
MISMATCH = "mismatch"
MISSING = "missing"
UNREADABLE = "unreadable"
DAMAGED = "damaged"
EXTRA = "extra"
NO_SUMS = "no_sums"
INVALID = "invalid"

LABELS = {
    OK: "в порядке",
    MISMATCH: "КОНТРОЛЬНАЯ СУММА НЕ СОВПАДАЕТ",
    MISSING: "ФАЙЛ ОТСУТСТВУЕТ",
    UNREADABLE: "ОШИБКА ЧТЕНИЯ",
    DAMAGED: "ФАЙЛ НЕ ОТКРЫВАЕТСЯ",
    EXTRA: "лишний файл (нет в файле контрольных сумм)",
    NO_SUMS: "нет контрольных сумм известных алгоритмов",
    INVALID: "НЕДОПУСТИМЫЙ ПУТЬ (выходит за пределы папки предмета)",
}
PROBLEMS = {MISMATCH, MISSING, UNREADABLE, DAMAGED, NO_SUMS, INVALID}

IMAGE_LOAD_LIMIT = 400_000_000  # пикселей; большие изображения только проверяются без декодирования


@dataclass
class FileCheck:
    relpath: str
    status: str
    details: str = ""


@dataclass
class ItemCheck:
    checksum_file: Path
    target_root: Path
    version: str
    files: list[FileCheck] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not any(f.status in PROBLEMS for f in self.files)

    @property
    def status_text(self) -> str:
        if self.error:
            return f"ОШИБКА: {self.error}"
        problems = [f for f in self.files if f.status in PROBLEMS]
        if problems:
            n = len(problems)
            return f"ПРОБЛЕМЫ: {n} {textfmt.plural(n, 'файл', 'файла', 'файлов')}"
        extra = sum(1 for f in self.files if f.status == EXTRA)
        return "в порядке" + (f" (лишних файлов: {extra})" if extra else "")


def find_checksum_files(root: Path) -> list[Path]:
    """Файлы контрольных сумм (версий 2.x и 1.x) в папке и подпапках."""
    root = Path(root)
    if root.is_file():
        return [root] if checksums.parse(root) is not None else []
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            lower = name.lower()
            if not lower.endswith(".txt") or name.startswith("."):
                continue
            path = Path(dirpath) / name
            if lower.endswith(CHECKSUMS_SUFFIX) or checksums.parse(path) is not None:
                found.append(path)
    return found


def open_check(path: Path) -> str | None:
    """Пробует открыть файл. Возвращает текст ошибки или None.

    Для видео и аудио проверяется только структура контейнера:
    воспроизводимость нужно проверять плеером (п. 33.8).
    """
    ext = path.suffix.lower()
    try:
        if ext in {".jpg", ".jpeg", ".jpe", ".tif", ".tiff", ".png", ".gif", ".bmp", ".webp", ".jp2"}:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = None
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                if img.width * img.height <= IMAGE_LOAD_LIMIT:
                    for frame in range(getattr(img, "n_frames", 1)):
                        img.seek(frame)
                        img.load()
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted and reader.decrypt("") == 0:
                return None  # содержимое проверить нельзя без пароля
            for page in reader.pages:
                page.get_contents()
        elif ext in {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub"}:
            with zipfile.ZipFile(path) as zf:
                bad = zf.testzip()
                if bad:
                    return f"повреждён элемент архива {bad}"
        elif ext in {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".mpg", ".mpeg", ".ts",
                     ".mts", ".m2ts", ".mxf", ".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg", ".aif",
                     ".aiff", ".wma"}:
            from pymediainfo import MediaInfo
            info = MediaInfo.parse(str(path))
            if not any(t.track_type in ("Video", "Audio") for t in info.tracks):
                return "MediaInfo не нашёл ни видео-, ни аудиодорожек"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return None


ProgressFn = Callable[[str, int], None]


def verify_item(
    checksum_path: Path,
    target_root: Path | None = None,
    open_files: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> ItemCheck:
    """Сверяет один предмет. target_root — папка резервной копии (если сверяется копия)."""
    parsed = checksums.parse(checksum_path)
    root = Path(target_root) if target_root else checksum_path.parent
    if parsed is None:
        return ItemCheck(checksum_path, root, "?", error="файл контрольных сумм не распознан")
    result = ItemCheck(checksum_path, root, parsed.version)

    if target_root is not None:
        copy = root / checksum_path.name
        if not copy.exists():
            result.files.append(FileCheck(checksum_path.name, MISSING, "в резервной копии нет файла контрольных сумм"))
        elif copy.read_bytes() != checksum_path.read_bytes():
            result.files.append(FileCheck(checksum_path.name, MISMATCH,
                                          "файл контрольных сумм в копии отличается от мастер-копии"))

    from .package import is_safe_relpath, resolve
    listed = parsed.by_file()
    for relpath, expected in listed.items():
        if cancel is not None and cancel.is_set():
            raise hashing.Cancelled()
        if not is_safe_relpath(relpath):
            result.files.append(FileCheck(relpath, INVALID))
            continue
        path = resolve(root, relpath)
        if path is None or not path.is_file():
            result.files.append(FileCheck(relpath, MISSING))
            continue
        if not expected:
            result.files.append(FileCheck(relpath, NO_SUMS))
            continue
        callback = (lambda n, r=relpath: progress(r, n)) if progress else None
        try:
            actual = hashing.hash_file(path, expected.keys(), callback, cancel)
        except hashing.Cancelled:
            raise
        except PermissionError:
            result.files.append(FileCheck(relpath, UNREADABLE, "нет доступа (недостаточно прав)"))
            continue
        except OSError as exc:
            result.files.append(FileCheck(relpath, UNREADABLE,
                                          f"{exc.strerror or exc} — возможна неисправность носителя"))
            continue
        bad = [hashing.ALGORITHMS[k].tag for k, v in expected.items() if actual[k] != v]
        if bad:
            result.files.append(FileCheck(relpath, MISMATCH, "не совпадает: " + ", ".join(bad)))
            continue
        if open_files and not xmlio.is_description(path):
            problem = open_check(path)
            if problem:
                result.files.append(FileCheck(relpath, DAMAGED, problem))
                continue
        algos = ", ".join(hashing.ALGORITHMS[k].tag for k in expected)
        result.files.append(FileCheck(relpath, OK, f"проверено: {algos}"))

    # Лишние файлы: лежат в папке предмета, но не перечислены ни в одном
    # файле контрольных сумм этой папки. Подпапки со своими описаниями — другие предметы.
    from .package import collect_files, nfc
    covered = {nfc(p) for p in listed}
    for sibling in checksums.files_in(checksum_path.parent):
        if sibling != checksum_path:
            other = checksums.parse(sibling)
            covered.update(nfc(p) for p in (other.by_file() if other else ()))
    for path in collect_files(root, warnings=[]):
        rel = nfc(path.relative_to(root).as_posix())
        if rel not in covered:
            result.files.append(FileCheck(rel, EXTRA))
    return result


def verify_tree(
    master_root: Path,
    backup_root: Path | None = None,
    open_files: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    on_item: Callable[[ItemCheck], None] | None = None,
) -> list[ItemCheck]:
    """Сверяет все предметы в папке. Если задан backup_root, проверяется резервная
    копия с той же структурой папок по контрольным суммам мастер-копии."""
    master_root = Path(master_root)
    base = master_root if master_root.is_dir() else master_root.parent
    results = []
    for cf in find_checksum_files(master_root):
        target = None
        if backup_root is not None:
            target = Path(backup_root) / cf.parent.relative_to(base)
        try:
            check = verify_item(cf, target, open_files, progress, cancel)
        except hashing.Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Сверка %s", cf)
            check = ItemCheck(cf, target or cf.parent, "?", error=f"{type(exc).__name__}: {exc}")
        results.append(check)
        if on_item:
            on_item(check)
    return results


def planned_bytes(master_root: Path, backup_root: Path | None = None) -> int:
    total = 0
    base = master_root if master_root.is_dir() else master_root.parent
    for cf in find_checksum_files(master_root):
        parsed = checksums.parse(cf)
        root = (Path(backup_root) / cf.parent.relative_to(base)) if backup_root else cf.parent
        for relpath in parsed.by_file() if parsed else ():
            try:
                total += (root / relpath).stat().st_size
            except OSError:
                pass
    return total


def write_report(results: list[ItemCheck], path: Path, master_root: Path, backup_root: Path | None,
                 started: datetime) -> Path:
    """Отчёт о сверке: .csv — таблица для Excel, иначе текст."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Дата сверки", "Файл контрольных сумм", "Проверяемая папка", "Файл", "Результат",
                             "Подробности"])
            for item in results:
                if item.error:
                    writer.writerow([textfmt.date_only(started), str(item.checksum_file), str(item.target_root),
                                     "", "ОШИБКА", item.error])
                for fc in item.files:
                    writer.writerow([textfmt.date_only(started), str(item.checksum_file), str(item.target_root),
                                     fc.relpath, LABELS[fc.status], fc.details])
        return path

    problems = [r for r in results if not r.ok]
    lines = [
        "ОТЧЁТ О СВЕРКЕ ЦИФРОВЫХ МУЗЕЙНЫХ ПРЕДМЕТОВ",
        f"Дата сверки: {textfmt.date_only(started)} (для поля «Сверка» в КАМИС)",
        f"Начало: {textfmt.date_time(started)}",
        f"Проверено: {master_root}",
    ]
    if backup_root:
        lines.append(f"Резервная копия: {backup_root}")
    lines += [
        f"Программа: {APP_NAME} {__version__}",
        f"Предметов: {len(results)}, с проблемами: {len(problems)}",
        "",
    ]
    for item in results:
        lines.append(f"[{item.status_text}] {item.target_root}")
        lines.append(f"    файл контрольных сумм: {item.checksum_file.name} (формат {item.version})")
        for fc in item.files:
            if fc.status != OK:
                detail = f" — {fc.details}" if fc.details else ""
                lines.append(f"    {LABELS[fc.status]}: {fc.relpath}{detail}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
