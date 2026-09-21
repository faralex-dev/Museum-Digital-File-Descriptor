import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mdfd import formats, textfmt
from mdfd.probes import probe_file
from mdfd.probes.office import rtf_to_text
from mdfd.probes.text import detect_encoding

DATA = Path(__file__).parent / "data"


def props(name):
    result = probe_file(DATA / name)
    assert result.warnings == [], result.warnings
    return result, {p.key: p.text for p in result.props}


def track(result, kind):
    t = next(t for t in result.tracks if t.kind == kind)
    return {p.key: p.text for p in t.props}


def test_video_h264():
    r, p = props("video_h264_aac.mp4")
    assert r.category == formats.VIDEO
    assert r.puid == "fmt/199"
    assert p["duration"] == "00:00:01"
    assert p["resolution"] == "160 × 90 пикс."
    assert p["frame_rate"] == "25 кадр/с"
    assert p["video_codec"].startswith("AVC/H.264")
    assert "Мбит/с" in p["video_bit_rate"]
    audio = track(r, "audio")
    assert audio["codec"] == "AAC LC"
    assert audio["channels"] == "2 (стерео, L R)"
    assert audio["sampling_rate"] == "48 000 Гц"
    assert track(r, "video")["compression_mode"] == "с потерями"
    assert any("с потерями" in n for n in r.notes)
    assert r.content_created == "01.05.2024 10:00:00 (UTC)"


def test_video_lossless_has_no_lossy_note():
    r, _ = props("video_ffv1_flac.mkv")
    assert track(r, "video")["compression_mode"] == "без потерь"
    assert track(r, "audio")["compression_mode"] == "без потерь"
    assert not any("потерями" in n for n in r.notes)


def test_audio_formats():
    r, _ = props("audio_pcm.wav")
    assert r.category == formats.AUDIO
    assert r.puid == "fmt/141"
    a = track(r, "audio")
    assert a["compression_mode"] == "без сжатия"
    assert a["channels"] == "1 (моно)"
    assert a["bit_depth"] == "16 бит"

    r, _ = props("audio.mp3")
    assert track(r, "audio")["codec"].startswith("MP3")
    assert track(r, "audio")["bit_rate"] == "0,192 Мбит/с (192 кбит/с)"

    r, _ = props("audio_hires.flac")
    assert track(r, "audio")["sampling_rate"] == "96 000 Гц"


@pytest.mark.parametrize("name,compression,puid", [
    ("photo_exif.jpg", "с потерями (JPEG)", "fmt/1507"),
    ("photo_jfif.jpg", "с потерями (JPEG)", "fmt/43"),
    ("scan_lzw.tif", "без потерь (LZW)", "fmt/353"),
    ("scan_raw.tif", "без сжатия", "fmt/353"),
    ("multipage.tif", "без потерь (Deflate (ZIP))", "fmt/353"),
    ("image.png", "без потерь (Deflate)", ""),
    ("image.gif", "без потерь (LZW; не более 256 цветов)", "fmt/3"),
    ("image.bmp", "без сжатия", "fmt/116"),
    ("lossy.webp", "с потерями (WebP (VP8))", "fmt/566"),
    ("lossless.webp", "без потерь (WebP lossless)", "fmt/567"),
    ("image.jp2", "без потерь (JPEG 2000, обратимое вейвлет-преобразование 5/3)", "x-fmt/392"),
    ("image_lossy.jp2", "с потерями (JPEG 2000, необратимое вейвлет-преобразование 9/7)", "x-fmt/392"),
])
def test_image_compression(name, compression, puid):
    r, p = props(name)
    assert r.category == formats.IMAGE
    assert p["compression"] == compression
    assert r.puid == puid
    if puid:
        assert r.pronom_name


def test_image_details():
    r, p = props("photo_exif.jpg")
    assert p["pixel_size"] == "120 × 80 пикс."
    assert p["resolution"] == "300 точек/дюйм"
    assert p["icc_profile"] == "sRGB built-in"
    assert p["exif_date"] == "15.07.2023 12:34:56"
    assert r.content_created == "15.07.2023 12:34:56"

    _, p = props("rgb16.png")
    assert p["bit_depth"] == "16 бит на канал"
    _, p = props("gray16.tif")
    assert p["bit_depth"] == "16 бит на канал"
    assert p["color_mode"] == "оттенки серого"
    _, p = props("multipage.tif")
    assert p["frames"] == "3"
    _, p = props("image.gif")
    assert p["resolution"] == "не указано в файле"


@pytest.mark.parametrize("name,encoding,language", [
    ("letter_cp1251.txt", "Windows-1251 (ANSI, кириллица)", "русский; кириллица"),
    ("koi8.txt", "KOI8-R", "русский; кириллица"),
    ("bom.txt", "UTF-8 (с меткой BOM)", "русский; кириллица"),
    ("memoir_utf8.txt", "UTF-8", "русский; кириллица и латиница (преобладает кириллица)"),
])
def test_plain_text(name, encoding, language):
    r, p = props(name)
    assert r.category == formats.TEXT
    assert p["encoding"] == encoding
    assert p["language"] == language
    assert p["characters"].startswith(tuple("123456789"))


def test_text_counts(tmp_path):
    path = tmp_path / "t.txt"
    path.write_bytes("Раз два\nтри\n".encode("utf-8"))
    _, p = props_at(path)
    assert p["characters"] == "12 (без пробелов: 9)"
    assert p["words"] == "3"
    assert p["lines"] == "2"


def props_at(path):
    result = probe_file(path)
    return result, {p.key: p.text for p in result.props}


def test_ascii_and_utf16(tmp_path):
    a = tmp_path / "a.txt"
    a.write_bytes(b"plain ascii text")
    assert detect_encoding(a)[0] == "ascii"
    u = tmp_path / "u.txt"
    u.write_bytes("Привет, мир".encode("utf-16-le"))
    assert detect_encoding(u)[0] == "utf-16-le"


@pytest.mark.parametrize("name,puid", [
    ("document.docx", "fmt/412"),
    ("document.odt", "fmt/136"),
    ("document.rtf", ""),
])
def test_documents(name, puid):
    r, p = props(name)
    assert r.puid == puid
    assert p["language"] == "русский; кириллица"
    assert p["characters"].startswith("1")
    assert int(p["words"]) > 15


def test_doc_ole():
    r, p = props("document.doc")
    assert r.puid == "fmt/40"
    assert any("проприетарный" in n for n in r.notes)


def test_rtf_parser_unicode_and_hex():
    bs = chr(92)  # обратная косая черта
    unicode_part = f"{bs}u1055?{bs}u1088?"
    text, info = rtf_to_text(
        r"{\rtf1\ansi\ansicpg1251\deff0{\fonttbl{\f0 Times;}}{\info{\nofpages3}}"
        + r"\uc1" + unicode_part + r"\'e8\'e2\'e5\'f2\par World}"
    )
    assert text == "Привет\nWorld"
    assert info["nofpages"] == 3


def test_pdf(tmp_path):
    from PIL import Image
    path = tmp_path / "scan.pdf"
    Image.new("RGB", (50, 50), "white").save(path, save_all=True,
                                              append_images=[Image.new("RGB", (50, 50))])
    r, p = props_at(path)
    assert r.warnings == []
    assert p["pages"] == "2"
    assert p["pdf_version"]
    assert r.puid == formats.PDF_VERSIONS[p["pdf_version"]]
    assert p["text_layer"].startswith("нет")
    assert any("PDF/A" in n for n in r.notes)


def test_unknown_file(tmp_path):
    path = tmp_path / "data.xyz"
    path.write_bytes(b"\x00\x01\x02")
    r = probe_file(path)
    assert r.category == formats.OTHER
    assert r.warnings == []


def test_broken_image_is_warning_not_crash(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0 not really")
    r = probe_file(path)
    assert r.warnings


def test_formatting():
    assert textfmt.size(3_545_994) == "3,38 МБ (3 545 994 байт)"
    assert textfmt.size(512) == "512 байт"
    assert textfmt.bitrate(5_234_567) == "5,23 Мбит/с (5 234 567 бит/с)"
    assert textfmt.bitrate(128_000) == "0,128 Мбит/с (128 кбит/с)"
    assert textfmt.duration(3_723_456) == "01:02:03.456"
    assert textfmt.duration(60_000) == "00:01:00"
    assert textfmt.frame_rate(29.97) == "29,97 кадр/с"
    assert textfmt.any_date("2024-05-01T10:00:00Z") == "01.05.2024 10:00:00 (UTC)"
    assert textfmt.any_date("2024-05-01 10:00:00 UTC") == "01.05.2024 10:00:00 (UTC)"
    assert textfmt.any_date("нечто") == "нечто"
    dt = datetime(2022, 10, 5, 14, 3, 59, tzinfo=timezone.utc)
    assert textfmt.date_only(dt) == "05.10.2022"
    assert textfmt.date_time(dt) == "05.10.2022 14:03:59 (UTC+00:00)"
    assert [textfmt.plural(n, "файл", "файла", "файлов") for n in (1, 2, 5, 11, 21, 22)] == [
        "файл", "файла", "файлов", "файлов", "файл", "файла"]


@pytest.mark.skipif(sys.platform == "win32", reason="на Windows MediaInfo получает путь в UTF-16")
def test_media_with_cyrillic_path_without_locale(tmp_path):
    """Приложение, запущенное из Finder, стартует с локалью «C»: MediaInfo не
    открывал файлы с русскими буквами в пути (ошибка в 2.0.1)."""
    import locale
    import shutil
    from mdfd.probes import media
    path = tmp_path / "Истории ＂Слыхали ль вы？..＂.mp4"
    shutil.copy(DATA / "video_h264_aac.mp4", path)
    saved = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, "C")
        r = probe_file(path)
        assert r.warnings == [], r.warnings
        # окно Tk сбрасывает локаль уже после запуска программы (ошибка 2.0.2)
        locale.setlocale(locale.LC_CTYPE, "C")
        r = probe_file(path)
        assert r.warnings == [], r.warnings
        assert {p.key for p in r.props} >= {"duration", "resolution", "video_codec"}
    finally:
        locale.setlocale(locale.LC_CTYPE, saved)


def test_audio_tags():
    r, p = props("audio_tagged.flac")
    assert p["tag_track_name"] == "Ария Il balen"
    assert p["tag_performer"] == "Николай Шевелёв"
    assert p["tag_track_name_position"] == "20"
    assert p["tag_album"] == "Архив"


def _tiff_with_exif(path):
    """Минимальный TIFF с IFD0 и вложенным EXIF IFD, как в RAW-файлах камер
    (Pillow при сохранении TIFF вложенный EXIF не пишет)."""
    import struct
    ascii_ = 2
    data = bytearray()
    blobs = []

    def entry(tag, typ, count, value):
        return struct.pack("<HHI", tag, typ, count) + value

    def rational(num, den):
        return struct.pack("<II", num, den)

    # раскладка: заголовок(8) | IFD0 | EXIF IFD | данные
    ifd0_tags = 3
    exif_tags = 5
    ifd0_off = 8
    exif_off = ifd0_off + 2 + ifd0_tags * 12 + 4
    data_off = exif_off + 2 + exif_tags * 12 + 4

    def put(blob):
        nonlocal data_off
        off = data_off
        blobs.append(blob)
        data_off += len(blob)
        return struct.pack("<I", off)

    ifd0 = [
        entry(0x010F, ascii_, 5, put(b"SONY\0")),
        entry(0x0110, ascii_, 9, put(b"ILCE-9M2\0")),
        entry(0x8769, 4, 1, struct.pack("<I", exif_off)),
    ]
    exif = [
        entry(0x829A, 5, 1, put(rational(1, 250))),
        entry(0x829D, 5, 1, put(rational(35, 10))),
        entry(0x8827, 3, 1, struct.pack("<HH", 640, 0)),
        entry(0x9003, ascii_, 20, put(b"2025:03:06 14:24:12\0")),
        entry(0xA434, ascii_, 19, put(b"FE 24-70mm F2.8 GM\0")),
    ]
    data += b"II*\0" + struct.pack("<I", ifd0_off)
    data += struct.pack("<H", ifd0_tags) + b"".join(ifd0) + b"\0\0\0\0"
    data += struct.pack("<H", exif_tags) + b"".join(exif) + b"\0\0\0\0"
    data += b"".join(blobs)
    path.write_bytes(bytes(data))


def test_raw_exif_when_pillow_cannot_open(tmp_path, monkeypatch):
    """Sony ARW и др.: Pillow файл не открывает, EXIF читается напрямую из структуры TIFF."""
    from mdfd.probes import image
    path = tmp_path / "ЦНАР_43.1.arw"
    _tiff_with_exif(path)

    # имитируем RAW: rawpy файл прочитал, Pillow — нет
    monkeypatch.setattr(image, "_probe_raw", lambda p, r: True)
    monkeypatch.setattr(image.Image, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("cannot identify")))
    r, p = props_at(path)
    assert p["camera"] == "SONY ILCE-9M2"
    assert p["lens"] == "FE 24-70mm F2.8 GM"
    assert p["exposure"] == "1/250 с, f/3,5, ISO 640"
    assert p["exif_date"] == "06.03.2025 14:24:12"
    assert r.content_created == "06.03.2025 14:24:12"
