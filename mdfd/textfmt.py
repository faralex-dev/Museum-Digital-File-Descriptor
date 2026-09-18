"""Форматирование значений для описаний (по образцам внутримузейных правил ГМИГ)."""
from __future__ import annotations

import re
from datetime import datetime, timezone


def group_digits(value: int) -> str:
    """3545994 -> '3 545 994'."""
    return f"{value:,}".replace(",", " ")


def decimal(value: float, digits: int = 2) -> str:
    """Число с десятичной запятой: 3.38 -> '3,38'."""
    return f"{value:.{digits}f}".replace(".", ",")


def _trim(text: str) -> str:
    """'25,000' -> '25', '29,970' -> '29,97'."""
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def size(num_bytes: int) -> str:
    """Размер файла: '3,38 МБ (3 545 994 байт)'."""
    exact = f"{group_digits(num_bytes)} байт"
    if num_bytes < 1024:
        return exact
    value = float(num_bytes)
    for unit in ("КБ", "МБ", "ГБ", "ТБ", "ПБ"):
        value /= 1024
        if value < 1024 or unit == "ПБ":
            return f"{decimal(value)} {unit} ({exact})"
    raise AssertionError("unreachable")


def bitrate(bits_per_second: float) -> str:
    """Битрейт в Мбит/с, для небольших значений — ещё и в кбит/с."""
    bps = int(round(bits_per_second))
    mbit = bps / 1_000_000
    exact = f"{group_digits(bps)} бит/с"
    if mbit >= 1:
        return f"{_trim(decimal(mbit, 2))} Мбит/с ({exact})"
    return f"{_trim(decimal(mbit, 3))} Мбит/с ({_trim(decimal(bps / 1000, 1))} кбит/с)"


def duration(milliseconds: float) -> str:
    """Продолжительность 'чч:мм:сс', с миллисекундами, если они есть."""
    total_ms = int(round(milliseconds))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, ms = divmod(rest, 1000)
    text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if ms:
        text += f".{ms:03d}"
    return text


def frame_rate(fps: float) -> str:
    return f"{_trim(decimal(fps, 3))} кадр/с"


def sampling_rate(hz: float) -> str:
    return f"{group_digits(int(round(hz)))} Гц"


def local_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()


def utc_offset(dt: datetime) -> str:
    offset = dt.utcoffset()
    if offset is None:
        return ""
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def date_time(dt: datetime) -> str:
    """Дата для описания: '05.10.2022 14:03:59 (UTC+03:00)'."""
    text = dt.strftime("%d.%m.%Y %H:%M:%S")
    offset = utc_offset(dt)
    return f"{text} ({offset})" if offset else text


def date_only(dt: datetime) -> str:
    """Дата для поля «Сверка» в КАМИС: '05.10.2022' (так требуют внутримузейные правила)."""
    return dt.strftime("%d.%m.%Y")


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(3, 'файл', 'файла', 'файлов') -> 'файла'."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


_ISO_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(Z|UTC|[+-]\d{2}:?\d{2})?"
)


def any_date(value) -> str:
    """Дата из метаданных файла в виде 'дд.мм.гггг чч:мм:сс'.

    Понимает datetime, ISO 8601 ('2024-05-01T10:00:00Z') и формат MediaInfo
    ('2024-05-01 10:00:00 UTC'). Нераспознанный текст возвращается как есть.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return date_time(value) if value.tzinfo else value.strftime("%d.%m.%Y %H:%M:%S")
    text = str(value).strip()
    match = _ISO_RE.match(text)
    if not match:
        return text
    y, mo, d, h, mi, s, tz = match.groups()
    out = f"{d}.{mo}.{y}"
    if h is not None:
        out += f" {h}:{mi}:{s or '00'}"
    if tz:
        tz = "UTC" if tz in ("Z", "UTC") else f"UTC{tz[:3]}:{tz[-2:]}"
        out += f" ({tz})"
    return out
