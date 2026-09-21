"""Видео и аудио: сведения через библиотеку MediaInfo (входит в пакет pymediainfo)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .. import formats, textfmt
from ..model import ProbeResult, Track

try:
    from pymediainfo import MediaInfo
except ImportError:  # pragma: no cover
    MediaInfo = None

# Названия кодеков в привычном виде («AVC/H.264»).
VIDEO_CODECS = {
    "AVC": "AVC/H.264",
    "HEVC": "HEVC/H.265",
    "VVC": "VVC/H.266",
    "AV1": "AV1",
    "VP8": "VP8",
    "VP9": "VP9",
    "FFV1": "FFV1",
    "ProRes": "Apple ProRes",
    "DV": "DV",
    "MPEG-4 Visual": "MPEG-4 Part 2",
    "JPEG 2000": "JPEG 2000",
    "VC-1": "VC-1 (Windows Media Video 9)",
    "Theora": "Theora",
}
AUDIO_CODECS = {
    "AAC": "AAC",
    "AC-3": "Dolby Digital (AC-3)",
    "E-AC-3": "Dolby Digital Plus (E-AC-3)",
    "FLAC": "FLAC",
    "Opus": "Opus",
    "Vorbis": "Vorbis",
    "ALAC": "Apple Lossless (ALAC)",
    "WMA": "Windows Media Audio",
    "PCM": "PCM",
    "DTS": "DTS",
}
LOSSLESS_VIDEO = {"FFV1", "HuffYUV", "Lagarith", "UTVideo"}
# Кодеки, которые на практике всегда сжимают с потерями (MediaInfo не всегда это сообщает).
LOSSY_VIDEO = {"AVC", "HEVC", "VVC", "AV1", "VP8", "VP9", "MPEG Video", "MPEG-4 Visual", "VC-1",
               "Theora", "ProRes", "DV", "WMV1", "WMV2", "WMV3", "H.263", "Sorenson Spark"}
LOSSY_AUDIO = {"AAC", "MPEG Audio", "AC-3", "E-AC-3", "Opus", "Vorbis", "WMA", "DTS", "AMR"}
LOSSLESS_AUDIO = {"FLAC", "ALAC", "Monkey's Audio", "WavPack", "TTA", "MLP", "TrueHD"}
UNCOMPRESSED_AUDIO = {"PCM", "ADPCM"}

CHANNEL_NAMES = {1: "моно", 2: "стерео", 3: "2.1", 6: "5.1", 8: "7.1"}

LANGUAGES = {
    "ru": "русский", "rus": "русский", "russian": "русский",
    "en": "английский", "eng": "английский", "english": "английский",
    "de": "немецкий", "ger": "немецкий", "deu": "немецкий", "german": "немецкий",
    "fr": "французский", "fre": "французский", "fra": "французский", "french": "французский",
    "uk": "украинский", "ukr": "украинский", "ukrainian": "украинский",
    "pl": "польский", "pol": "польский", "polish": "польский",
}

TRANSLATE = {
    "Progressive": "прогрессивная",
    "Interlaced": "чересстрочная",
    "MBAFF": "чересстрочная (MBAFF)",
    "PAFF": "чересстрочная (PAFF)",
    "Mixed": "смешанная",
    "CFR": "постоянная",
    "VFR": "переменная",
    "CBR": "постоянный",
    "VBR": "переменный",
    "Lossy": "с потерями",
    "Lossless": "без потерь",
}


_UTF8_LOCALES = ("C.UTF-8", "en_US.UTF-8", "ru_RU.UTF-8", "UTF-8")


def _is_utf8(name: str) -> bool:
    return "utf8" in name.lower().replace("-", "")


def ensure_utf8_locale() -> None:
    """MediaInfo на macOS и Linux переводит путь к файлу в байты по текущей
    локали. У приложения, запущенного из Finder, локали нет («C»), и тогда
    файлы с русскими буквами в пути не открываются.

    Вызывается перед каждым обращением к MediaInfo: окно Tk при создании
    сбрасывает локаль в «C» (ошибка 2.0.2). Переменная LC_CTYPE задаётся,
    чтобы и сам Tk при запуске выбрал UTF-8."""
    if sys.platform == "win32":
        return
    import locale
    import os
    try:
        if _is_utf8(locale.setlocale(locale.LC_CTYPE)):
            return
    except locale.Error:
        pass
    for name in ("", *_UTF8_LOCALES):
        try:
            chosen = locale.setlocale(locale.LC_CTYPE, name)
        except locale.Error:
            continue
        if _is_utf8(chosen):
            if not _is_utf8(os.environ.get("LC_ALL", "") or os.environ.get("LC_CTYPE", "")):
                os.environ["LC_CTYPE"] = chosen
            return


def available() -> bool:
    return MediaInfo is not None and MediaInfo.can_parse()


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def _first(value) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return "" if value is None else str(value)


def _tr(value) -> str:
    text = _first(value)
    return TRANSLATE.get(text, text)


def _codec(track, table: dict) -> str:
    fmt = _first(track.format)
    name = table.get(fmt, fmt)
    if fmt == "MPEG Video":
        version = _first(track.format_version).replace("Version ", "")
        name = f"MPEG-{version} Video" if version else "MPEG Video"
    if fmt == "MPEG Audio":
        version = _first(track.format_version).replace("Version ", "")
        layer = _first(track.format_profile).replace("Layer ", "")
        name = {"3": "MP3", "2": "MP2", "1": "MP1"}.get(layer, "MPEG Audio")
        if version or layer:
            name += f" (MPEG-{version or '?'} Audio Layer {layer or '?'})"
    if fmt == "AAC" and track.format_additionalfeatures:
        name = f"AAC {track.format_additionalfeatures}"
    details = []
    if fmt not in ("MPEG Audio",) and track.format_profile:
        details.append(f"профиль {track.format_profile}")
    if fmt == "FFV1" and track.format_version:
        details.append(_first(track.format_version).replace("Version", "версия"))
    if details:
        name += f", {', '.join(details)}"
    return name


def _compression_code(track) -> str:
    """'Lossy', 'Lossless', 'None' или ''."""
    fmt = _first(track.format)
    if fmt in UNCOMPRESSED_AUDIO:
        return "None"
    mode = _first(track.compression_mode)
    if mode:
        return mode
    if fmt in LOSSLESS_VIDEO or fmt in LOSSLESS_AUDIO:
        return "Lossless"
    if fmt in LOSSY_VIDEO or fmt in LOSSY_AUDIO:
        return "Lossy"
    return ""


def _compression(track) -> str:
    code = _compression_code(track)
    return "без сжатия" if code == "None" else TRANSLATE.get(code, code)


# Служебные названия дорожек, которые ставят программы записи, — ничего не сообщают
GENERIC_TRACK_TITLES = {"core media video", "core media audio", "core media metadata", "soundhandler",
                        "videohandler", "sound media handler", "video media handler", "apple sound media handler",
                        "apple video media handler", "mainconcept video media handler", "gpac isomedia handler",
                        # HandBrake и другие конвертеры называют дорожку по раскладке каналов
                        "stereo", "mono", "surround", "surround 5.1", "surround 7.1", "5.1", "7.1", "2.0",
                        "dolby surround"}


def _track_title(track) -> str:
    title = _first(track.title)
    parts = [x.strip().casefold() for x in title.split(" / ")]
    return "" if all(x in GENERIC_TRACK_TITLES for x in parts) else title


def _language(track) -> str:
    code = _first(track.language).lower()
    if not code:
        return ""
    return LANGUAGES.get(code, code)


def _channels(track) -> str:
    count = _num(track.channel_s)
    if count is None:
        return ""
    count = int(count)
    layout = _first(track.channel_layout)
    if layout in ("M", "C"):
        layout = ""
    parts = [n for n in (CHANNEL_NAMES.get(count), layout) if n]
    return f"{count} ({', '.join(parts)})" if parts else str(count)


RANGES = {"Limited": "ограниченный диапазон", "Full": "полный диапазон"}


def _colour(track) -> str:
    """«BT.709, ограниченный диапазон»; передаточная функция и матрица — если отличаются."""
    primaries = _first(track.color_primaries or track.colour_primaries)
    if not primaries:
        return ""
    parts = [primaries]
    transfer = _first(track.transfer_characteristics)
    if transfer and transfer != primaries:
        parts.append(f"передаточная функция {transfer}")
    matrix = _first(track.matrix_coefficients)
    if matrix and matrix != primaries:
        parts.append(f"матрица {matrix}")
    colour_range = _first(track.color_range or track.colour_range)
    if colour_range:
        parts.append(RANGES.get(colour_range, colour_range))
    return ", ".join(parts)


def _video_track(track, n: int) -> Track:
    t = Track("video", f"Видеодорожка {n}")
    add = _adder(t)
    add("codec", "Кодек", _codec(track, VIDEO_CODECS), track.format)
    if track.width and track.height:
        add("resolution", "Разрешение", f"{track.width} × {track.height} пикс.", f"{track.width}x{track.height}")
    if track.other_display_aspect_ratio:
        add("display_aspect_ratio", "Соотношение сторон", _first(track.other_display_aspect_ratio),
            track.display_aspect_ratio)
    bitrate = _num(track.bit_rate) or _num(track.nominal_bit_rate)
    if bitrate:
        add("bit_rate", "Битрейт", textfmt.bitrate(bitrate), int(bitrate))
    add("bit_rate_mode", "Вид битрейта", _tr(track.bit_rate_mode))
    fps = _num(track.frame_rate)
    if fps:
        add("frame_rate", "Частота кадров", textfmt.frame_rate(fps), track.frame_rate)
    add("frame_rate_mode", "Режим частоты кадров", _tr(track.frame_rate_mode))
    add("scan_type", "Развёртка", _tr(track.scan_type))
    if track.bit_depth:
        add("bit_depth", "Разрядность цвета", f"{track.bit_depth} бит", track.bit_depth)
    add("chroma_subsampling", "Субдискретизация цвета", _first(track.chroma_subsampling))
    add("color_space", "Цветовая модель", _first(track.color_space))
    add("colour", "Цветовой стандарт", _colour(track))
    add("compression_mode", "Метод сжатия", _compression(track))
    duration = _num(track.duration)
    if duration:
        add("duration", "Продолжительность", textfmt.duration(duration), duration)
    add("language", "Язык (метка в файле)", _language(track))
    add("title", "Название дорожки", _track_title(track))
    return t


def _audio_track(track, n: int) -> Track:
    t = Track("audio", f"Аудиодорожка {n}")
    add = _adder(t)
    add("codec", "Кодек", _codec(track, AUDIO_CODECS), track.format)
    bitrate = _num(track.bit_rate) or _num(track.nominal_bit_rate)
    if bitrate:
        add("bit_rate", "Битрейт", textfmt.bitrate(bitrate), int(bitrate))
    add("bit_rate_mode", "Вид битрейта", _tr(track.bit_rate_mode))
    add("channels", "Каналы", _channels(track), track.channel_s)
    add("channel_positions", "Расположение каналов", _first(track.channel_positions))
    rate = _num(track.sampling_rate)
    if rate:
        add("sampling_rate", "Частота дискретизации", textfmt.sampling_rate(rate), int(rate))
    if track.bit_depth:
        add("bit_depth", "Разрядность", f"{track.bit_depth} бит", track.bit_depth)
    add("compression_mode", "Метод сжатия", _compression(track))
    duration = _num(track.duration)
    if duration:
        add("duration", "Продолжительность", textfmt.duration(duration), duration)
    add("language", "Язык (метка в файле)", _language(track))
    add("title", "Название дорожки", _track_title(track))
    return t


def _text_track(track, n: int) -> Track:
    t = Track("text", f"Субтитры {n}")
    add = _adder(t)
    add("format", "Формат", _first(track.format))
    add("language", "Язык (метка в файле)", _language(track))
    add("title", "Название дорожки", _track_title(track))
    return t


def _adder(track: Track):
    from ..model import Prop

    def add(key, label, text, raw=None):
        if text:
            track.props.append(Prop(key, label, str(text), None if raw in (None, "") else str(raw)))
    return add


def _bext_text(data: bytes) -> str:
    raw = data.split(b"\x00", 1)[0].strip()
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return raw.decode("cp1251", "replace").strip()


def _wave_info(path: Path) -> tuple[str, dict]:
    """Идентификатор PRONOM для WAVE и поля блока bext (Broadcast WAVE, EBU Tech 3285):
    описание, устройство или программа записи, дата и время записи, история кодирования."""
    try:
        with open(path, "rb") as f:
            head = f.read(64 * 1024)
    except OSError:
        return "", {}
    if head[:4] not in (b"RIFF",) or head[8:12] != b"WAVE":
        return "", {}
    pos, fmt_size, bext = 12, None, None
    while pos + 8 <= len(head):
        chunk_id = head[pos:pos + 4]
        size = int.from_bytes(head[pos + 4:pos + 8], "little")
        if chunk_id == b"fmt ":
            fmt_size = size
        elif chunk_id == b"bext" and pos + 8 + 348 <= len(head):
            data = head[pos + 8:pos + 8 + size]
            bext = {
                "version": str(int.from_bytes(data[346:348], "little")),
                "description": _bext_text(data[0:256]),
                "originator": _bext_text(data[256:288]),
                "originator_reference": _bext_text(data[288:320]),
                "date": _bext_text(data[320:330]),
                "time": _bext_text(data[330:338]),
                "coding_history": _bext_text(data[602:]) if len(data) > 602 else "",
            }
        pos += 8 + size + (size & 1)
    if bext is not None:
        return formats.BWF_VERSIONS.get(bext["version"], ""), bext
    kind = {16: "PCMWAVEFORMAT", 18: "WAVEFORMATEX", 40: "WAVEFORMATEXTENSIBLE"}.get(fmt_size or 0)
    return formats.WAVE_KINDS.get(kind, ""), {}


def _mp4_opus_channels(path: Path) -> int | None:
    """Число каналов Opus из блока dOps в MP4: MediaInfo его не сообщает."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            end = f.tell()
            pos = 0
            while pos + 8 <= end:
                f.seek(pos)
                header = f.read(16)
                size, kind = int.from_bytes(header[:4], "big"), header[4:8]
                if size == 1:
                    size = int.from_bytes(header[8:16], "big")
                elif size == 0:
                    size = end - pos
                if size < 8:
                    return None
                if kind == b"moov":
                    if size > 64 * 1024 * 1024:
                        return None
                    f.seek(pos)
                    moov = f.read(size)
                    i = moov.find(b"dOps")
                    return moov[i + 5] if i >= 0 and i + 5 < len(moov) and moov[i + 5] else None
                pos += size
    except OSError:
        return None
    return None


def probe(path: Path, result: ProbeResult) -> ProbeResult:
    if MediaInfo is None:
        result.warnings.append("Библиотека MediaInfo недоступна: технические сведения не получены.")
        return result
    ensure_utf8_locale()
    try:
        info = MediaInfo.parse(str(path))
    except Exception:  # noqa: BLE001 - текст ошибки libmediainfo бесполезен для хранителя
        result.warnings.append("MediaInfo не смог открыть файл: технические сведения о видео и звуке не получены.")
        return result
    general = next((t for t in info.tracks if t.track_type == "General"), None)
    videos = [t for t in info.tracks if t.track_type == "Video"]
    audios = [t for t in info.tracks if t.track_type == "Audio"]
    texts = [t for t in info.tracks if t.track_type == "Text"]
    images = [t for t in info.tracks if t.track_type == "Image"]

    if videos:
        result.category = formats.VIDEO
    elif audios:
        result.category = formats.AUDIO
    elif general is None or not general.format:
        result.warnings.append("MediaInfo не распознал формат файла.")
        return result

    wave_puid, bext = ("", {})
    if path.suffix.lower() in (".wav", ".bwf"):
        wave_puid, bext = _wave_info(path)
        if bext:
            result.format_name = f"Broadcast WAVE (BWF), версия {bext['version']}"
    for track in audios:
        if not track.channel_s and _first(track.format) == "Opus" and _first(general.format if general else "") == "MPEG-4":
            track.channel_s = _mp4_opus_channels(path)

    if general is not None:
        container = _first(general.format)
        if container:
            profile = _first(general.format_profile)
            version = _first(general.format_version)
            extra = ", ".join(x for x in (profile, version) if x)
            result.add("container", "Контейнер", f"{container} ({extra})" if extra else container, container)
        duration = _num(general.duration)
        if duration:
            result.add("duration", "Продолжительность", textfmt.duration(duration), duration)
        overall = _num(general.overall_bit_rate)
        if overall:
            result.add("overall_bit_rate", "Общий битрейт", textfmt.bitrate(overall), int(overall))
        for key in ("recorded_date", "encoded_date"):
            value = _first(getattr(general, key))
            if value:
                result.content_created = textfmt.any_date(value)
                break
        if general.recorded_date:
            result.add("recorded_date", "Дата записи", textfmt.any_date(_first(general.recorded_date)),
                       _first(general.recorded_date))
        if bext:
            # BWF: дата и время записи из блока bext (MediaInfo выдаёт их же как дату кодирования)
            recorded = " ".join(x for x in (bext["date"], bext["time"]) if x)
            if recorded:
                result.content_created = textfmt.any_date(recorded)
                result.add("bwf_date", "Дата и время записи (BWF)", textfmt.any_date(recorded), recorded)
            result.add("bwf_originator", "Устройство или программа записи (BWF)", bext["originator"])
            result.add("bwf_reference", "Идентификатор записи (BWF)", bext["originator_reference"])
            result.add("bwf_description", "Описание (BWF)", bext["description"])
            result.add("bwf_coding_history", "История кодирования (BWF)", bext["coding_history"])
        elif general.encoded_date:
            result.add("encoded_date", "Дата кодирования", textfmt.any_date(_first(general.encoded_date)),
                       _first(general.encoded_date))
        # Описательные теги внутри файла (ID3, Vorbis comments, MP4) — как записаны
        for key, label in (("track_name", "Название (тег файла)"), ("performer", "Исполнитель (тег файла)"),
                           ("composer", "Композитор (тег файла)"), ("album", "Альбом (тег файла)"),
                           ("track_name_position", "Номер дорожки (тег файла)"),
                           ("genre", "Жанр (тег файла)"),
                           ("comment", "Комментарий (тег файла)"), ("copyright", "Авторские права (тег файла)")):
            result.add(f"tag_{key}", label, _first(getattr(general, key)))
        app = _first(general.writing_application) or _first(general.encoded_application)
        result.add("writing_application", "Программа записи", app)
        if general.encryption or any(t.encryption for t in videos + audios):
            result.notes.append("Файл зашифрован (DRM): такие файлы не рекомендуются для хранения (п. 33.10).")

    if result.category == formats.VIDEO and videos:
        v = videos[0]
        if v.width and v.height:
            result.add("resolution", "Разрешение", f"{v.width} × {v.height} пикс.", f"{v.width}x{v.height}")
        fps = _num(v.frame_rate)
        if fps:
            result.add("frame_rate", "Частота кадров", textfmt.frame_rate(fps), v.frame_rate)
        bitrate = _num(v.bit_rate) or _num(v.nominal_bit_rate)
        if bitrate:
            result.add("video_bit_rate", "Битрейт видео", textfmt.bitrate(bitrate), int(bitrate))
        result.add("video_codec", "Кодек видео", _codec(v, VIDEO_CODECS), v.format)

    for n, track in enumerate(videos, 1):
        result.tracks.append(_video_track(track, n))
    for n, track in enumerate(audios, 1):
        result.tracks.append(_audio_track(track, n))
    for n, track in enumerate(texts, 1):
        result.tracks.append(_text_track(track, n))
    if images and result.category == formats.AUDIO:
        result.add("cover", "Обложка", "есть")

    lossy = [t for t in videos + audios if _compression_code(t) == "Lossy"]
    if lossy:
        kinds = sorted({"видео" if t.track_type == "Video" else "аудио" for t in lossy})
        result.notes.append(
            f"Сжатие с потерями ({', '.join(kinds)}): для мастер-копии рекомендуются форматы без потерь (п. 33.10)."
        )
    if any(_first(t.frame_rate_mode) == "VFR" for t in videos):
        result.notes.append("Переменная частота кадров: при конвертации возможен рассинхрон звука и изображения.")

    if wave_puid:
        result.puid = wave_puid
    return result
