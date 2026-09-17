"""Текст: определение кодировки, языка и количества знаков.

Кодировка определяется без внешних библиотек: сначала метка BOM, затем
строгая проверка UTF-8, затем выбор между распространёнными кириллическими
кодировками по частоте букв русского языка.
"""
from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from pathlib import Path

from .. import textfmt
from ..model import ProbeResult

CHUNK = 1024 * 1024
SAMPLE = 256 * 1024

BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le", "UTF-32 LE (с меткой BOM)"),
    (codecs.BOM_UTF32_BE, "utf-32-be", "UTF-32 BE (с меткой BOM)"),
    (codecs.BOM_UTF8, "utf-8-sig", "UTF-8 (с меткой BOM)"),
    (codecs.BOM_UTF16_LE, "utf-16-le", "UTF-16 LE (с меткой BOM)"),
    (codecs.BOM_UTF16_BE, "utf-16-be", "UTF-16 BE (с меткой BOM)"),
)

LEGACY = (
    ("cp1251", "Windows-1251 (ANSI, кириллица)"),
    ("koi8-r", "KOI8-R"),
    ("cp866", "CP866 (DOS, кириллица)"),
)
LATIN = ("cp1252", "Windows-1252 (ANSI, западноевропейская)")

# Самые частые буквы русского текста.
TOP_RU = set("оеаинтсрвл")

UKRAINIAN = set("іїєґІЇЄҐ")
BELARUSIAN = set("ўЎ")
STOPWORDS = {
    "русский": {"и", "в", "не", "на", "что", "с", "по", "это", "как", "из", "к", "за", "от", "для", "он"},
    "английский": {"the", "and", "of", "to", "in", "is", "that", "for", "with", "on", "was", "as"},
    "немецкий": {"der", "die", "und", "das", "ist", "nicht", "mit", "den", "sich", "des", "auf"},
    "французский": {"le", "la", "les", "et", "des", "est", "une", "dans", "que", "pour", "pas"},
}
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass
class TextStats:
    chars: int = 0             # все знаки, включая пробелы
    chars_no_spaces: int = 0
    words: int = 0
    lines: int = 0
    cyrillic: int = 0
    latin: int = 0
    other_letters: int = 0
    sample: str = ""

    def feed(self, text: str) -> None:
        self.chars += len(text)
        self.chars_no_spaces += sum(1 for ch in text if not ch.isspace())
        self.lines += text.count("\n")
        for ch in text:
            if ch.isalpha():
                if "Ѐ" <= ch <= "ӿ":
                    self.cyrillic += 1
                elif ch.isascii() or "À" <= ch <= "ɏ":
                    self.latin += 1
                else:
                    self.other_letters += 1
        if len(self.sample) < SAMPLE:
            self.sample += text[: SAMPLE - len(self.sample)]


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def _score_cyrillic(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    lower = [ch for ch in letters if "а" <= ch <= "я" or ch == "ё"]
    frequent = sum(1 for ch in lower if ch in TOP_RU)
    # Доля строчных кириллических букв и доля самых частых букв среди них.
    return len(lower) / len(letters) + (frequent / len(lower) if lower else 0)


def detect_encoding(path: Path) -> tuple[str, str]:
    """Возвращает (кодек Python, название для описания)."""
    with open(path, "rb") as f:
        head = f.read(SAMPLE)
    for bom, codec, label in BOMS:
        if head.startswith(bom):
            return codec, label
    if not head:
        return "ascii", "ASCII"

    # UTF-16 без BOM: в каждом втором байте почти всегда одно значение
    # (0x00 для латиницы, 0x04 для кириллицы), а управляющих байтов в обычном тексте нет.
    window = head[:4096]
    if len(window) >= 4 and any(b < 0x09 for b in window):
        for codec, high in (("utf-16-le", window[1::2]), ("utf-16-be", window[0::2])):
            top = max(set(high), key=high.count)
            if top in (0x00, 0x04) and high.count(top) / len(high) > 0.6:
                sample = window[: len(window) // 2 * 2].decode(codec, errors="replace")
                good = sum(1 for ch in sample if ch.isalnum() or ch.isspace() or ch in ".,;:!?-—«»()\"'")
                if sample and good / len(sample) > 0.9:
                    return codec, f"{codec.upper().replace('-LE', ' LE').replace('-BE', ' BE')} (без метки BOM)"

    # Строгая проверка UTF-8 по всему файлу.
    decoder = codecs.getincrementaldecoder("utf-8")()
    has_non_ascii = False
    try:
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK):
                if not has_non_ascii and any(b > 0x7F for b in chunk):
                    has_non_ascii = True
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        if not has_non_ascii:
            return "ascii", "ASCII (совместима с UTF-8)"
        return "utf-8", "UTF-8"
    except UnicodeDecodeError:
        pass

    best, best_score = LATIN, 0.6
    for codec, label in LEGACY:
        try:
            text = head.decode(codec)
        except UnicodeDecodeError:
            continue
        score = _score_cyrillic(text)
        if score > best_score:
            best, best_score = (codec, label), score
    return best


def describe_language(stats: TextStats, sample: str, declared: str = "") -> str:
    """Язык и письменность текста: «русский (кириллица)»."""
    letters = stats.cyrillic + stats.latin + stats.other_letters
    if letters == 0:
        return declared
    shares = {
        "кириллица": stats.cyrillic / letters,
        "латиница": stats.latin / letters,
        "другая письменность": stats.other_letters / letters,
    }
    scripts = [name for name, share in sorted(shares.items(), key=lambda x: -x[1]) if share >= 0.1]

    language = ""
    main_script = scripts[0] if scripts else ""
    if main_script == "кириллица":
        if any(ch in UKRAINIAN for ch in sample):
            language = "украинский"
        elif any(ch in BELARUSIAN for ch in sample):
            language = "белорусский"
    if not language and main_script in ("кириллица", "латиница"):
        # Язык ищем только среди языков основной письменности текста.
        candidates = {lang: sw for lang, sw in STOPWORDS.items()
                      if (lang == "русский") == (main_script == "кириллица")}
        words = [w.lower() for w in WORD_RE.findall(sample[:SAMPLE])]
        if words:
            counts = {lang: sum(1 for w in words if w in sw) for lang, sw in candidates.items()}
            lang, hits = max(counts.items(), key=lambda x: x[1])
            if hits >= max(2, len(words) * 0.02):
                language = lang
    if declared and not language:
        language = declared

    script_text = " и ".join(scripts) if scripts else ""
    if len(scripts) > 1:
        script_text += f" (преобладает {scripts[0]})"
    if language and script_text:
        return f"{language}; {script_text}"
    return language or script_text


def add_text_stats(result: ProbeResult, text: str, declared_language: str = "", pages: int | None = None,
                   pages_label: str = "Количество страниц") -> None:
    stats = TextStats()
    stats.feed(text)
    _add_stats(result, stats, count_words(text), declared_language)
    if pages:
        result.add("pages", pages_label, pages)


def _add_stats(result: ProbeResult, stats: TextStats, words: int, declared_language: str = "") -> None:
    result.add("language", "Язык", describe_language(stats, stats.sample, declared_language))
    result.add(
        "characters", "Количество знаков",
        f"{textfmt.group_digits(stats.chars)} (без пробелов: {textfmt.group_digits(stats.chars_no_spaces)})",
        stats.chars,
    )
    result.add("words", "Количество слов", textfmt.group_digits(words), words)


def probe(path: Path, result: ProbeResult) -> ProbeResult:
    codec, label = detect_encoding(path)
    result.add("encoding", "Кодировка текста", label, codec)
    decoder = codecs.getincrementaldecoder(codec)(errors="replace")
    stats = TextStats()
    words = 0
    tail = ""
    last = ""
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            text = tail + decoder.decode(chunk)
            # слово на границе блоков переносим в следующий блок
            cut = max(text.rfind(" "), text.rfind("\n"))
            if cut > 0:
                text, tail = text[:cut], text[cut:]
            else:
                tail = ""
            stats.feed(text)
            words += count_words(text)
            last = text[-1:] or last
        text = tail + decoder.decode(b"", final=True)
        stats.feed(text)
        words += count_words(text)
        last = text[-1:] or last
    result.add("lines", "Количество строк", stats.lines + (1 if last and last != "\n" else 0))
    _add_stats(result, stats, words)
    return result
