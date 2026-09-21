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


@pytest.mark.parametrize("make,model,expected", [
    ("Canon", "Canon EOS 6D", "Canon EOS 6D"),
    ("SONY", "ILCE-7M3", "SONY ILCE-7M3"),
    ("NIKON CORPORATION", "NIKON D850", "NIKON D850"),
    ("", "Scanner X", "Scanner X"),
    ("Epson", "", "Epson"),
])
def test_camera_name(make, model, expected):
    from mdfd.probes.image import camera_name
    assert camera_name(make, model) == expected


XMP_PACKET = """<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
     xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmpMM:PreservedFileName="DSC_0833.NEF" xmp:CreatorTool="Adobe Photoshop Lightroom Classic 14.0.1">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Концерт в Доме радио</rdf:li></rdf:Alt></dc:title>
   <dc:subject><rdf:Bag><rdf:li>концерт</rdf:li><rdf:li>хор</rdf:li></rdf:Bag></dc:subject>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def _jpeg_with_metadata(path):
    """JPEG с EXIF (автор, права, программа, серийный номер, GPS) и XMP."""
    import io
    from PIL import Image
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "NIKON CORPORATION", "NIKON Z 8"
    exif[0x013B] = "Александр Фарукшин".encode("utf-8")  # программы пишут в EXIF UTF-8
    exif[0x8298] = "ГМИГ".encode("utf-8")
    exif[0x0131] = "Adobe Photoshop Lightroom Classic 14.0.1 (Macintosh)"
    exif[0x010E] = "SONY DSC"  # подпись камеры, не описание
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = "2025:01:25 19:00:09"
    sub[0xA431] = "7806606"
    sub[0x920A] = 240.0
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (55.0, 45.0, 0.0), "E", (37.0, 37.0, 12.0)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "JPEG", exif=exif.tobytes())
    data = buf.getvalue()
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + XMP_PACKET.encode("utf-8")
    app1 = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    path.write_bytes(data[:2] + app1 + data[2:])


def test_image_author_keywords_gps_from_exif_and_xmp(tmp_path):
    path = tmp_path / "снимок.jpg"
    _jpeg_with_metadata(path)
    r, p = props_at(path)
    assert r.warnings == []
    assert p["author"] == "Александр Фарукшин"
    assert p["copyright"] == "ГМИГ"
    assert p["title"] == "Концерт в Доме радио"
    assert "description" not in p
    assert p["keywords"] == "концерт; хор"
    assert p["camera"] == "NIKON Z 8"
    assert p["camera_serial"] == "7806606"
    assert p["exposure"] == "240 мм"
    assert p["gps"] == "55,750000° с. ш., 37,620000° в. д."
    assert p["software"] == "Adobe Photoshop Lightroom Classic 14.0.1 (Macintosh)"
    assert p["original_name"] == "DSC_0833.NEF"


def test_xmp_old_xap_format_and_bad_packet():
    from mdfd.probes.embedded import parse_xmp
    old = """<x:xapmeta xmlns:x='adobe:ns:meta/'><rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
      <rdf:Description about='' xmlns:xap='http://ns.adobe.com/xap/1.0/'>
       <xap:CreateDate>2006-05-27T20:57:35+03:00</xap:CreateDate>
       <xap:CreatorTool>Adobe Photoshop CS Windows</xap:CreatorTool>
      </rdf:Description></rdf:RDF></x:xapmeta>"""
    x = parse_xmp(old)
    assert x["xmp:CreateDate"] == ["2006-05-27T20:57:35+03:00"]
    assert x["xmp:CreatorTool"] == ["Adobe Photoshop CS Windows"]
    assert parse_xmp(b"<x:xmpmeta><broken") == {}
    assert parse_xmp('<!DOCTYPE x [<!ENTITY a "b">]><rdf:RDF/>') == {}


def test_iptc_utf8_and_cp1251():
    from mdfd.probes.embedded import parse_iptc
    assert parse_iptc({(1, 90): b"\x1b%G", (2, 80): "Фотограф".encode("utf-8"),
                       (2, 25): [b"a", b"b"]}) == {"by_line": ["Фотограф"], "keywords": ["a", "b"]}
    assert parse_iptc({(2, 116): "Музей".encode("cp1251")}) == {"copyright": ["Музей"]}


def _nikon_makernote():
    """Служебный блок Nikon: объектив (0x0084), серийный номер (0x001D), ISO (0x0025)."""
    import struct
    entries, blobs = [], b""
    count = 3
    data_off = 8 + 2 + count * 12 + 4
    lens = b"".join(struct.pack(">II", int(v * 10), 10) for v in (24, 70, 2.8, 2.8))
    entries.append(struct.pack(">HHI", 0x001D, 2, 8) + struct.pack(">I", data_off))
    blobs += b"2061922\0"
    entries.append(struct.pack(">HHI", 0x0025, 7, 4) + bytes([60, 1, 12, 0]))
    entries.append(struct.pack(">HHI", 0x0084, 5, 4) + struct.pack(">I", data_off + 8))
    blobs += lens
    tiff = b"MM\0*" + struct.pack(">I", 8) + struct.pack(">H", count) + b"".join(entries) + b"\0\0\0\0" + blobs
    return b"Nikon\0\x02\x11\0\0" + tiff


def test_nikon_makernote_lens_iso_serial():
    from mdfd.probes import image
    note = image._nikon_makernote({0x927C: _nikon_makernote()})
    assert image._nikon_iso(note) == 100
    assert image._lens_from_spec(note[0x0084]) == "24–70 мм f/2,8"
    assert note[0x001D] == "2061922"
    r = formats  # noqa: F841
    from mdfd.model import ProbeResult
    result = ProbeResult(category=formats.IMAGE)
    image._add_camera_info(result, {0x010F: "NIKON CORPORATION", 0x0110: "NIKON D3S"},
                           {0x829A: 0.005, 0x829D: 16.0, 0x927C: _nikon_makernote()})
    p = {x.key: x.text for x in result.props}
    assert p["lens"] == "24–70 мм f/2,8"
    assert p["exposure"] == "1/200 с, f/16, ISO 100"
    assert p["camera_serial"] == "2061922"


@pytest.mark.parametrize("spec,expected", [
    ((50, 50, float("nan"), float("nan")), "50 мм"),
    ((24, 85, 3.5, 4.5), "24–85 мм f/3,5–4,5"),
    ((0, 0, 0, 0), ""),
    (None, ""),
])
def test_lens_from_spec(spec, expected):
    from mdfd.probes.image import _lens_from_spec
    assert _lens_from_spec(spec) == expected


def _bwf(path, originator=b"ZOOM Handy Recorder H6", version=1):
    import struct
    bext = bytearray(602)
    bext[0:16] = "Интервью".encode("utf-8")
    bext[256:256 + len(originator)] = originator
    bext[320:330] = b"2025-04-24"
    bext[330:338] = b"19-06-17"
    bext[346:348] = struct.pack("<H", version)
    bext += b"A=PCM,F=48000,W=16,M=mono\r\n"
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    data = b"\0\0" * 4800
    body = b"WAVE" + b"bext" + struct.pack("<I", len(bext)) + bytes(bext)
    body += b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def test_broadcast_wave_bext(tmp_path):
    path = tmp_path / "запись.wav"
    _bwf(path)
    r, p = props_at(path)
    assert r.format_name == "Broadcast WAVE (BWF), версия 1"
    assert r.puid == "fmt/2"
    assert p["bwf_originator"] == "ZOOM Handy Recorder H6"
    assert p["bwf_date"] == "24.04.2025 19:06:17"
    assert p["bwf_description"] == "Интервью"
    assert p["bwf_coding_history"] == "A=PCM,F=48000,W=16,M=mono"
    assert "encoded_date" not in p
    assert r.content_created == "24.04.2025 19:06:17"


def test_date_with_hyphenated_time():
    assert textfmt.any_date("2025-04-24 19-06-17") == "24.04.2025 19:06:17"
    assert textfmt.any_date("2025-04-24 19:06:17 UTC") == "24.04.2025 19:06:17 (UTC)"
    assert textfmt.any_date("2025-04-24-03:00") == "24.04.2025 (UTC-03:00)"


class _Track:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None


def test_generic_track_titles_and_colour():
    from mdfd.probes.media import _colour, _track_title
    assert _track_title(_Track(title="Stereo / Stereo")) == ""
    assert _track_title(_Track(title="Core Media Audio")) == ""
    assert _track_title(_Track(title="Комментарий режиссёра")) == "Комментарий режиссёра"
    assert _colour(_Track(color_primaries="BT.709", transfer_characteristics="BT.709",
                          matrix_coefficients="BT.709", color_range="Limited")) == "BT.709, ограниченный диапазон"
    assert _colour(_Track(color_primaries="BT.709", transfer_characteristics="xvYCC")) == \
        "BT.709, передаточная функция xvYCC"
    assert _colour(_Track()) == ""


def test_opus_channels_in_mp4(tmp_path):
    import struct
    from mdfd.probes.media import _mp4_opus_channels

    def box(kind, payload):
        return struct.pack(">I", 8 + len(payload)) + kind + payload
    dops = box(b"dOps", bytes([0, 2]) + b"\0" * 9)
    moov = box(b"moov", box(b"trak", box(b"Opus", b"\0" * 28 + dops)))
    path = tmp_path / "a.mp4"
    path.write_bytes(box(b"ftyp", b"mp42\0\0\0\0") + box(b"mdat", b"\0" * 100) + moov)
    assert _mp4_opus_channels(path) == 2
    path.write_bytes(box(b"ftyp", b"mp42\0\0\0\0") + box(b"mdat", b"\0" * 10))
    assert _mp4_opus_channels(path) is None
