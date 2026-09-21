"""Сведения, которые фотографы и программы записывают внутрь файла:
XMP (Adobe) и IPTC. Читаются без внешних библиотек."""
from __future__ import annotations

import xml.etree.ElementTree as ET

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NAMESPACES = {
    "http://purl.org/dc/elements/1.1/": "dc",
    "http://ns.adobe.com/xap/1.0/": "xmp",
    "http://ns.adobe.com/xap/1.0/mm/": "xmpMM",
    "http://ns.adobe.com/exif/1.0/aux/": "aux",
    "http://ns.adobe.com/photoshop/1.0/": "photoshop",
    "http://cipa.jp/exif/1.0/": "exifEX",
    "http://ns.adobe.com/xap/1.0/rights/": "xmpRights",
}


def _local(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        uri, name = tag[1:].split("}", 1)
        return NAMESPACES.get(uri, ""), name
    return "", tag


def parse_xmp(packet) -> dict[str, list[str]]:
    """Пакет XMP -> {'dc:creator': [...], 'xmp:CreatorTool': [...], ...}.
    Берутся только известные пространства имён; повреждённый пакет — пустой словарь."""
    if not packet:
        return {}
    if isinstance(packet, bytes):
        packet = packet.decode("utf-8", "replace")
    if "<!DOCTYPE" in packet or "<!ENTITY" in packet:
        return {}
    start = min((i for i in (packet.find("<x:xmpmeta"), packet.find("<x:xapmeta"), packet.find("<rdf:RDF"))
                 if i >= 0), default=-1)
    if start < 0:
        return {}
    end_tag = next((t for t in ("</x:xmpmeta>", "</x:xapmeta>", "</rdf:RDF>") if t in packet[start:]), "")
    body = packet[start:packet.find(end_tag, start) + len(end_tag)] if end_tag else packet[start:]
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return {}
    out: dict[str, list[str]] = {}

    def put(prefix, name, values):
        values = [v.strip() for v in values if v and v.strip()]
        if prefix and values:
            out.setdefault(f"{prefix}:{name}", []).extend(values)

    for desc in root.iter(f"{{{RDF}}}Description"):
        for attr, value in desc.attrib.items():
            put(*_local(attr), [value])
        for child in desc:
            prefix, name = _local(child.tag)
            if not prefix:
                continue
            items = [li.text or "" for li in child.iter(f"{{{RDF}}}li")]
            put(prefix, name, items if items else [child.text or ""])
    return out


def _iptc_text(value: bytes, utf8: bool) -> str:
    if utf8:
        return value.decode("utf-8", "replace")
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("cp1251", "replace")


def parse_iptc(info) -> dict[str, list[str]]:
    """Словарь Pillow {(запись, поле): bytes | [bytes]} -> {'by_line': [...], ...}."""
    if not info:
        return {}
    fields = {(2, 5): "object_name", (2, 25): "keywords", (2, 80): "by_line", (2, 116): "copyright",
              (2, 120): "caption", (2, 110): "credit", (2, 115): "source"}
    charset = info.get((1, 90), b"")
    if isinstance(charset, list):
        charset = charset[0] if charset else b""
    utf8 = charset == b"\x1b%G"
    out: dict[str, list[str]] = {}
    for key, name in fields.items():
        value = info.get(key)
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        texts = [_iptc_text(v, utf8).strip("\x00 ").strip() for v in values if isinstance(v, bytes)]
        texts = [t for t in texts if t]
        if texts:
            out[name] = texts
    return out
