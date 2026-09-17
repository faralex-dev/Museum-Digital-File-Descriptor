"""Модель данных описания цифрового музейного предмета."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Prop:
    """Одно свойство: машинный ключ, подпись и значение для человека.

    raw — значение без форматирования (число, код), если оно отличается от text.
    """
    key: str
    label: str
    text: str
    raw: str | None = None


@dataclass
class Track:
    """Дорожка медиафайла (видео, аудио, субтитры) или кадр/страница."""
    kind: str        # video | audio | text | image | other
    label: str
    props: list[Prop] = field(default_factory=list)


@dataclass
class ProbeResult:
    """Что удалось узнать о содержимом файла."""
    category: str
    format_name: str = ""
    format_version: str = ""
    puid: str = ""
    pronom_name: str = ""
    mime: str = ""
    props: list[Prop] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # пригодность для хранения
    warnings: list[str] = field(default_factory=list)    # проблемы при анализе
    content_created: datetime | str | None = None        # дата из метаданных файла

    def add(self, key: str, label: str, text, raw=None) -> None:
        if text is None or text == "":
            return
        self.props.append(Prop(key, label, str(text), None if raw is None else str(raw)))


@dataclass
class FileRecord:
    """Файл мастер-копии."""
    path: Path                 # полный путь
    relpath: str               # путь относительно папки предмета, через «/»
    size: int
    created: datetime | None   # дата создания файла в файловой системе
    modified: datetime
    checksums: dict[str, str]  # ключ алгоритма -> HEX
    probe: ProbeResult
    extension: str

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def date_created(self) -> datetime:
        """Дата создания для описания.

        При копировании файла Windows ставит «дату создания» на момент копии,
        а дату изменения сохраняет, поэтому берётся более ранняя из двух.
        """
        if self.created is None:
            return self.modified
        return min(self.created, self.modified)


@dataclass
class ItemInfo:
    """Сведения о предмете, которые вводит хранитель."""
    accession_number: str = ""   # учётный номер по КП
    classifier: str = ""         # ФИО, место заключения и т. п. из имени папки
    title: str = ""
    description: str = ""
    topography: str = ""
    carrier: str = ""
    normalization: str = ""      # исходный формат, инструменты нормализации
    museum: str = ""


@dataclass
class Item:
    """Цифровой музейный предмет: папка (или файл) и файлы мастер-копии."""
    root: Path                   # папка, где лежат файлы описания
    base_name: str               # основа имени файлов описания
    info: ItemInfo
    sources: list[Path]
    files: list[FileRecord] = field(default_factory=list)

    @property
    def xml_path(self) -> Path:
        return self.root / f"{self.base_name}.xml"

    @property
    def checksums_path(self) -> Path:
        return self.root / f"{self.base_name}{CHECKSUMS_SUFFIX}"

    @property
    def kamis_path(self) -> Path:
        return self.root / f"{self.base_name}{KAMIS_SUFFIX}"


CHECKSUMS_SUFFIX = ".checksums.txt"
KAMIS_SUFFIX = ".kamis.txt"
