"""Офисные документы: DOCX/XLSX/PPTX, ODT/ODS/ODP, DOC/XLS/PPT, RTF.

OOXML и OpenDocument — это ZIP-архивы с XML, их разбирает стандартная
библиотека. Для старых форматов Microsoft Office нужен пакет olefile.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .. import formats, textfmt
from ..model import ProbeResult
from . import text as textprobe

try:
    import olefile
except ImportError:  # pragma: no cover
    olefile = None

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

NS = {
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

LANGUAGE_CODES = {
    "ru": "русский", "en": "английский", "de": "немецкий", "fr": "французский",
    "uk": "украинский", "be": "белорусский", "pl": "польский", "it": "итальянский", "es": "испанский",
}

WORD_TEXT_LIMIT = 50 * 1024 * 1024  # не разбираем текст из document.xml больше этого размера


def _lang_name(code: str) -> str:
    code = (code or "").strip()
    if not code:
        return ""
    return LANGUAGE_CODES.get(code.split("-")[0].lower(), code)


def _int(text) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _xml(zf: zipfile.ZipFile, name: str):
    try:
        with zf.open(name) as f:
            return ET.parse(f).getroot()
    except (KeyError, ET.ParseError):
        return None


def _word_text(zf: zipfile.ZipFile) -> str:
    """Текст основной части DOCX: абзацы через перевод строки."""
    try:
        info = zf.getinfo("word/document.xml")
    except KeyError:
        return ""
    if info.file_size > WORD_TEXT_LIMIT:
        return ""
    paragraphs = []
    w = "{%s}" % NS["w"]
    with zf.open(info) as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag == w + "p":
                parts = []
                for node in elem.iter():
                    if node.tag == w + "t" and node.text:
                        parts.append(node.text)
                    elif node.tag == w + "tab":
                        parts.append("\t")
                paragraphs.append("".join(parts))
                elem.clear()
    return "\n".join(paragraphs)


def _ooxml(path: Path, result: ProbeResult) -> None:
    ext = path.suffix.lower()
    with zipfile.ZipFile(path) as zf:
        app = _xml(zf, "docProps/app.xml")
        core = _xml(zf, "docProps/core.xml")
        stats = {}
        if app is not None:
            for key in ("Pages", "Words", "Characters", "CharactersWithSpaces", "Slides", "Application", "AppVersion"):
                node = app.find(f"ep:{key}", NS)
                if node is not None and node.text:
                    stats[key] = node.text
        if "Application" in stats:
            version = f" {stats['AppVersion']}" if "AppVersion" in stats else ""
            result.add("application", "Программа", stats["Application"] + version)

        declared = ""
        if core is not None:
            lang = core.find("dc:language", NS)
            if lang is not None and lang.text:
                declared = _lang_name(lang.text)
            created = core.find("dcterms:created", NS)
            if created is not None and created.text:
                result.content_created = textfmt.any_date(created.text)
                result.add("doc_created", "Дата создания документа (по свойствам файла)",
                           result.content_created, created.text)

        if ext == ".docx":
            styles = _xml(zf, "word/styles.xml")
            if not declared and styles is not None:
                lang = styles.find(".//w:docDefaults//w:lang", NS)
                if lang is not None:
                    declared = _lang_name(lang.get("{%s}val" % NS["w"], ""))
            result.add("encoding", "Кодировка текста", "UTF-8 (Office Open XML)")
            body = _word_text(zf)
            textprobe.add_text_stats(result, body, declared)
            pages = _int(stats.get("Pages"))
            if pages:
                result.add("pages", "Количество страниц (по данным программы, сохранившей файл)", pages)
        elif ext == ".pptx":
            slides = _int(stats.get("Slides"))
            if slides is None:
                slides = sum(1 for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
            result.add("slides", "Количество слайдов", slides)
        elif ext == ".xlsx":
            book = _xml(zf, "xl/workbook.xml")
            if book is not None:
                result.add("sheets", "Количество листов", len(book.findall("s:sheets/s:sheet", NS)))


def _odf_text(root) -> str:
    t = "{%s}" % NS["text"]
    out = []
    for elem in root.iter():
        if elem.tag in (t + "p", t + "h"):
            out.append("".join(elem.itertext()))
    return "\n".join(out)


def _odf(path: Path, result: ProbeResult) -> None:
    ext = path.suffix.lower().lstrip(".")
    with zipfile.ZipFile(path) as zf:
        meta = _xml(zf, "meta.xml")
        content = _xml(zf, "content.xml")
        version = ""
        for root in (content, meta):
            if root is not None:
                version = root.get("{%s}version" % NS["office"], "")
                if version:
                    break
        if version:
            result.format_version = version
            result.puid = formats.ODF_VERSIONS.get(ext, {}).get(version, "")

        stats, declared = {}, ""
        if meta is not None:
            node = meta.find(".//meta:document-statistic", NS)
            if node is not None:
                stats = {k.split("}")[-1]: v for k, v in node.attrib.items()}
            gen = meta.find(".//meta:generator", NS)
            if gen is not None and gen.text:
                result.add("application", "Программа", gen.text)
            lang = meta.find(".//dc:language", NS)
            if lang is not None and lang.text:
                declared = _lang_name(lang.text)
            created = meta.find(".//meta:creation-date", NS)
            if created is not None and created.text:
                result.content_created = textfmt.any_date(created.text)
                result.add("doc_created", "Дата создания документа (по свойствам файла)",
                           result.content_created, created.text)

        if ext == "odt":
            result.add("encoding", "Кодировка текста", "UTF-8 (OpenDocument)")
            textprobe.add_text_stats(result, _odf_text(content) if content is not None else "", declared)
            pages = _int(stats.get("page-count"))
            if pages:
                result.add("pages", "Количество страниц (по данным программы, сохранившей файл)", pages)
        elif ext == "odp":
            result.add("slides", "Количество слайдов", _int(stats.get("page-count")))
        elif ext == "ods":
            result.add("sheets", "Количество листов", _int(stats.get("table-count")))


def _ole(path: Path, result: ProbeResult) -> None:
    if olefile is None:
        result.warnings.append("Пакет olefile не установлен: сведения о документе не получены.")
        return
    with olefile.OleFileIO(str(path)) as ole:
        if ole.exists("EncryptionInfo") or ole.exists("EncryptedPackage"):
            result.notes.append("Документ зашифрован паролем: такие файлы не рекомендуются для хранения (п. 33.10).")
            return
        meta = ole.get_metadata()
        app = (meta.creating_application or b"").decode("cp1251", "replace").strip("\x00 ")
        result.add("application", "Программа", app)
        codepage = (meta.codepage or 0) & 0xFFFF
        if codepage:
            name = {1251: "Windows-1251 (ANSI, кириллица)", 1252: "Windows-1252 (ANSI)",
                    1200: "UTF-16", 65001: "UTF-8"}.get(codepage, f"кодовая страница {codepage}")
            result.add("encoding", "Кодировка свойств документа", name, codepage)
        if path.suffix.lower() == ".doc":
            if ole.exists("WordDocument"):
                result.puid = formats.DOC_OLE_PUID
            if meta.num_chars:
                result.add("characters", "Количество знаков (по данным Word, без пробелов)",
                           textfmt.group_digits(meta.num_chars), meta.num_chars)
            if meta.num_words:
                result.add("words", "Количество слов (по данным Word)", textfmt.group_digits(meta.num_words),
                           meta.num_words)
            if meta.num_pages:
                result.add("pages", "Количество страниц (по данным программы, сохранившей файл)", meta.num_pages)
        elif path.suffix.lower() == ".ppt" and meta.slides:
            result.add("slides", "Количество слайдов", meta.slides)
        if meta.create_time:
            result.content_created = textfmt.any_date(meta.create_time)
            result.add("doc_created", "Дата создания документа (по свойствам файла)", result.content_created)


RTF_DEST = re.compile(r"\\([a-z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-z])|([{}])|[\r\n]+|([^\\{}\r\n]+)")
RTF_SKIP = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "footer", "headerl",
    "headerr", "footerl", "footerr", "footnote", "xmlnstbl", "listtable", "listoverridetable",
    "rsidtbl", "generator", "themedata", "colorschememapping", "latentstyles", "datastore",
    "filetbl", "revtbl", "pgdsctbl", "fldinst", "bkmkstart", "bkmkend", "shppict", "nonshppict",
}


def rtf_to_text(data: str) -> tuple[str, dict]:
    """Простой разбор RTF: текст и сведения из группы {\\info}."""
    stack = []
    skip = False
    codepage = "cp1251"
    uc_skip = 1
    pending_skip = 0
    star = False
    out: list[str] = []
    info: dict[str, int | str] = {}
    info_key = None
    for match in RTF_DEST.finditer(data):
        word, arg, hexcode, symbol, brace, plain = match.groups()
        if brace == "{":
            stack.append((skip, uc_skip, info_key))
            star = False
            continue
        if brace == "}":
            if stack:
                skip, uc_skip, info_key = stack.pop()
            continue
        if word:
            if word in ("nofpages", "nofwords", "nofchars", "nofcharsws") and arg:
                info[word] = int(arg)
                continue
            if word == "ansicpg" and arg:
                codepage = f"cp{arg}"
                info["codepage"] = arg
                continue
            if word == "deflang" and arg:
                info["deflang"] = int(arg)
            if word in RTF_SKIP or star:
                skip = True
                star = False
                continue
            if word == "uc" and arg:
                uc_skip = int(arg)
            elif word == "u" and arg and not skip:
                code = int(arg)
                out.append(chr(code + 65536 if code < 0 else code))
                pending_skip = uc_skip
            elif word in ("par", "line", "sect", "page") and not skip:
                out.append("\n")
            elif word == "tab" and not skip:
                out.append("\t")
            continue
        if symbol:
            if symbol == "*":
                star = True
            elif not skip and symbol in "\\{}":
                out.append(symbol)
            elif not skip and symbol == "~":
                out.append("\u00a0")
            continue
        if hexcode:
            if pending_skip:
                pending_skip -= 1
                continue
            if not skip:
                try:
                    out.append(bytes([int(hexcode, 16)]).decode(codepage, "replace"))
                except LookupError:
                    out.append(bytes([int(hexcode, 16)]).decode("cp1252", "replace"))
            continue
        if plain:
            if pending_skip:
                cut = min(pending_skip, len(plain))
                plain = plain[cut:]
                pending_skip -= cut
            if not skip:
                out.append(plain)
    return "".join(out), info


RTF_LANG_IDS = {1049: "русский", 1033: "английский", 2057: "английский", 1031: "немецкий",
                1036: "французский", 1058: "украинский", 1059: "белорусский", 1045: "польский"}


def _rtf(path: Path, result: ProbeResult) -> None:
    data = path.read_bytes().decode("latin-1")
    body, info = rtf_to_text(data)
    codepage = info.get("codepage")
    if codepage:
        label = {"1251": "Windows-1251 (ANSI, кириллица)", "1252": "Windows-1252 (ANSI)",
                 "65001": "UTF-8"}.get(str(codepage), f"кодовая страница {codepage}")
        result.add("encoding", "Кодировка текста", label, f"cp{codepage}")
    declared = RTF_LANG_IDS.get(int(info.get("deflang", 0)), "")
    textprobe.add_text_stats(result, body.strip(), declared)
    if info.get("nofpages"):
        result.add("pages", "Количество страниц (по данным программы, сохранившей файл)", info["nofpages"])


def probe(path: Path, result: ProbeResult) -> ProbeResult:
    ext = path.suffix.lower()
    with open(path, "rb") as f:
        head = f.read(8)
    if ext in (".docx", ".xlsx", ".pptx") and head.startswith(OLE_MAGIC):
        result.notes.append("Документ зашифрован паролем: такие файлы не рекомендуются для хранения (п. 33.10).")
        return result
    if ext in (".docx", ".xlsx", ".pptx"):
        _ooxml(path, result)
    elif ext in (".odt", ".ods", ".odp"):
        _odf(path, result)
    elif ext in (".doc", ".xls", ".ppt"):
        if head.startswith(OLE_MAGIC):
            _ole(path, result)
        else:
            result.warnings.append("Файл не похож на документ Microsoft Office 97–2003 (другая внутренняя структура).")
    elif ext == ".rtf":
        _rtf(path, result)
    return result
