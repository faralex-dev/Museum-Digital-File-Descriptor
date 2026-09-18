"""Видео и аудио: сведения через библиотеку MediaInfo (входит в пакет pymediainfo)."""
from __future__ import annotations

import re
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
    add("colour_primaries", "Основные цвета", _first(track.colour_primaries))
    add("compression_mode", "Метод сжатия", _compression(track))
    duration = _num(track.duration)
    if duration:
        add("duration", "Продолжительность", textfmt.duration(duration), duration)
    add("language", "Язык", _language(track))
    add("title", "Название дорожки", _first(track.title))
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
    add("language", "Язык", _language(track))
    add("title", "Название дорожки", _first(track.title))
    return t


def _text_track(track, n: int) -> Track:
    t = Track("text", f"Субтитры {n}")
    add = _adder(t)
    add("format", "Формат", _first(track.format))
    add("language", "Язык", _language(track))
    add("title", "Название дорожки", _first(track.title))
    return t


def _adder(track: Track):
    from ..model import Prop

    def add(key, label, text, raw=None):
        if text:
            track.props.append(Prop(key, label, str(text), None if raw in (None, "") else str(raw)))
    return add


def _wave_puid(path: Path) -> str:
    """Уточняет идентификатор PRONOM для WAVE по заголовку файла."""
    try:
        with open(path, "rb") as f:
            head = f.read(64 * 1024)
    except OSError:
        return ""
    if head[:4] not in (b"RIFF",) or head[8:12] != b"WAVE":
        return ""
    pos, fmt_size, bext_version = 12, None, None
    while pos + 8 <= len(head):
        chunk_id = head[pos:pos + 4]
        size = int.from_bytes(head[pos + 4:pos + 8], "little")
        if chunk_id == b"fmt ":
            fmt_size = size
        elif chunk_id == b"bext" and pos + 8 + 348 <= len(head):
            bext_version = str(int.from_bytes(head[pos + 8 + 346:pos + 8 + 348], "little"))
        pos += 8 + size + (size & 1)
    if bext_version is not None:
        return formats.BWF_VERSIONS.get(bext_version, "")
    kind = {16: "PCMWAVEFORMAT", 18: "WAVEFORMATEX", 40: "WAVEFORMATEXTENSIBLE"}.get(fmt_size or 0)
    return formats.WAVE_KINDS.get(kind, "")


def probe(path: Path, result: ProbeResult) -> ProbeResult:
    if MediaInfo is None:
        result.warnings.append("Библиотека MediaInfo недоступна: технические сведения не получены.")
        return result
    info = MediaInfo.parse(str(path))
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
        if general.encoded_date:
            result.add("encoded_date", "Дата кодирования", textfmt.any_date(_first(general.encoded_date)),
                       _first(general.encoded_date))
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

    if path.suffix.lower() in (".wav", ".bwf"):
        result.puid = _wave_puid(path)
    return result
