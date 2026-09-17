"""Контрольные суммы файлов.

Все выбранные алгоритмы считаются за один проход по файлу. Если файл не
удаётся прочитать до конца, выбрасывается исключение, и в описание
ничего не попадает.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import streebog

CHUNK = 4 * 1024 * 1024

BACKEND = streebog.BACKEND


class Cancelled(Exception):
    """Операция отменена пользователем."""


@dataclass(frozen=True)
class Algorithm:
    key: str          # внутренний ключ
    tag: str          # обозначение в файле контрольных сумм
    label: str        # подпись для человека
    factory: Callable[[], object]
    aliases: tuple[str, ...] = ()


SHA256 = Algorithm(
    "sha256", "SHA256", "SHA-256", hashlib.sha256,
    aliases=("SHA-256", "SHA_256"),
)
GOST256 = Algorithm(
    "gost256", "GOST34.11-2018-256",
    "ГОСТ 34.11-2018 (ГОСТ Р 34.11-2012, «Стрибог», 256 бит)",
    lambda: streebog.new(256),
    aliases=("GR3411_2012_256", "GOST34112012_256", "STREEBOG256", "GOST-34.11-2012-256",
             "GOST R 34.11-2012 256", "md_gost12_256"),
)
GOST512 = Algorithm(
    "gost512", "GOST34.11-2018-512",
    "ГОСТ 34.11-2018 (ГОСТ Р 34.11-2012, «Стрибог», 512 бит)",
    lambda: streebog.new(512),
    aliases=("GR3411_2012_512", "GOST34112012_512", "STREEBOG512", "md_gost12_512"),
)
# SHA-1 и MD5 не используются в новых описаниях: они нужны только для
# сверки описаний, сделанных версией 1.x и другими программами.
SHA1 = Algorithm("sha1", "SHA1", "SHA-1", hashlib.sha1, aliases=("SHA-1",))
MD5 = Algorithm("md5", "MD5", "MD5", hashlib.md5)

ALGORITHMS = {a.key: a for a in (SHA256, GOST256, GOST512, SHA1, MD5)}

# Алгоритмы для новых описаний (п. 33.14 правил: SHA-256 и ГОСТ 34.11-2018).
DEFAULT_ALGORITHMS = ("sha256", "gost256")


def algorithm_by_tag(tag: str) -> Algorithm | None:
    """Находит алгоритм по обозначению из файла контрольных сумм (любой версии)."""
    norm = tag.strip().upper().replace(" ", "")
    for algo in ALGORITHMS.values():
        names = (algo.key, algo.tag, *algo.aliases)
        if norm in {n.upper().replace(" ", "") for n in names}:
            return algo
    return None


ProgressCallback = Callable[[int], None]


def hash_file(
    path: Path,
    algorithms: Iterable[str] = DEFAULT_ALGORITHMS,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, str]:
    """Считает контрольные суммы файла. Возвращает {ключ алгоритма: HEX}.

    progress(n) вызывается с числом прочитанных байт после каждого блока.
    """
    hashers = {key: ALGORITHMS[key].factory() for key in algorithms}
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            chunk = f.read(CHUNK)
            if not chunk:
                break
            for h in hashers.values():
                h.update(chunk)
            if progress is not None:
                progress(len(chunk))
    return {key: h.hexdigest().upper() for key, h in hashers.items()}
