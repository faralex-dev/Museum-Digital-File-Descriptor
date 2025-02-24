# Извлечение метаданных медиафайлов

from typing import Dict, Any, Optional
from wand.image import Image as WandImage
from wand.exceptions import WandException
from pymediainfo import MediaInfo
import os
import chardet

# Константы
_UNKNOWN = "unknown"
_SIZE_FORMAT = "{:.2f} x {:.2f}"

# Словарь для сопоставления типов сжатия с описанием
COMPRESSION_MAP = {
    'undefined': "Не определено",
    'b44a': "B44A (с потерями)",
    'b44': "B44 (с потерями)",
    'bzip': "BZIP (без потерь)",
    'dxt1': "DXT1 (с потерями)",
    'dxt3': "DXT3 (с потерями)",
    'dxt5': "DXT5 (с потерями)",
    'fax': "Fax (без потерь)",
    'group4': "Group4 (без потерь)",
    'jbig1': "JBIG1 (без потерь)",
    'jbig2': "JBIG2 (без потерь)",
    'jpeg2000': "JPEG2000 (с потерями)",
    'jpeg': "JPEG (с потерями)",
    'losslessjpeg': "Lossless JPEG (без потерь)",
    'lzma': "LZMA (без потерь)",
    'lzw': "LZW (без потерь)",
    'no': "Нет сжатия",
    'piz': "PIZ (без потерь)",
    'pxr24': "PXR24 (без потерь)",
    'rle': "RLE (без потерь)",
    'zip': "ZIP (без потерь)",
    'zips': "ZIPS (без потерь)"
}

def get_image_info(file_path: str) -> Dict[str, Any]:
    """Извлекает метаданные изображения с использованием ImageMagick (Wand).
    """

    try:
        with WandImage(filename=file_path) as img:
            dpi = img.resolution  # кортеж (dpi_x, dpi_y)
            # Получаем единицы измерения (может возвращаться как строка или числовой код)
            # Если единицы заданы как 'pixelspercentimeter' или числовой код (например, 2), конвертируем в DPI
            units = getattr(img, "units", "PixelsPerInch")
            if isinstance(units, str) and units.lower() == "pixelspercentimeter":
                dpi = (dpi[0] * 2.54, dpi[1] * 2.54)
            elif isinstance(units, int):
                # В некоторых версиях Wand: 1 = PixelsPerInch, 2 = PixelsPerCentimeter
                if units == 2:
                    dpi = (dpi[0] * 2.54, dpi[1] * 2.54)

            dpi_str = f"{dpi[0]:.0f} x {dpi[1]:.0f}" if dpi[0] and dpi[1] else "unknown"
            # Вычисляем физический размер в дюймах, затем переводим в сантиметры
            if dpi[0] and dpi[1]:
                width_in = img.width / dpi[0]
                height_in = img.height / dpi[1]
                print_size = f"{width_in * 2.54:.2f} x {height_in * 2.54:.2f}"
            else:
                print_size = "unknown"

            # Извлекаем тип сжатия (Wand возвращает числовой код, но его можно преобразовать в строку)
            compression = img.compression
            compression_str = (COMPRESSION_MAP.get(compression.lower(), compression)
                               if compression else "N/A")

            # Извлекаем битовую глубину
            bit_depth = img.depth  # глубина цвета (обычно на канал)
            bit_depth_str = f"{bit_depth} bit" if bit_depth else _UNKNOWN

            # Если формат TIFF, можно попробовать извлечь дополнительные метаданные
            tiff_metadata = dict(img.metadata) if img.format.upper() == "TIFF" else None

            return {
                "format": img.format,
                "color_mode": img.colorspace,
                "width_px": img.width,
                "height_px": img.height,
                "dpi": dpi_str,
                "print_size_cm": print_size,
                "compression": compression_str,
                "bit_depth": bit_depth_str,
                "tiff_metadata": tiff_metadata
            }
    except WandException as e:
        return {"Error": f"Не удалось обработать файл: {str(e)}"}


def get_media_info(file_path):
    """Получает медиа-информацию с pymediainfo."""
    return MediaInfo.parse(file_path)


def get_txt_meta(file_path: str) -> Dict[str, Any]:
    """Извлекает метаинформацию из текстового файла (.txt)"""
    with open(file_path, 'rb') as f:
        raw_data = f.read()
    detection = chardet.detect(raw_data)
    encoding = detection.get('encoding', 'utf-8')
    try:
        text = raw_data.decode(encoding)
    except Exception:
        text = raw_data.decode('utf-8', errors='replace')
    word_count = len(text.split())
    char_count = len(text)
    return {
        'encoding': encoding,
        'word_count': word_count,
        'char_count': char_count
    }

def get_docx_meta(file_path: str) -> Dict[str, Any]:
    """Извлекает метаинформацию из файла DOCX с помощью библиотеки python-docx"""
    from docx import Document
    doc = Document(file_path)
    text = "\n".join(para.text for para in doc.paragraphs)
    word_count = len(text.split())
    char_count = len(text)
    return {
        'encoding': 'utf-8',
        'word_count': word_count,
        'char_count': char_count
    }

def get_rtf_meta(file_path: str) -> Dict[str, Any]:
    """Извлекает метаинформацию из RTF-файла с использованием striprtf"""
    from striprtf.striprtf import rtf_to_text
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        rtf_content = f.read()
    text = rtf_to_text(rtf_content)
    word_count = len(text.split())
    char_count = len(text)
    return {
        'encoding': 'utf-8',
        'word_count': word_count,
        'char_count': char_count
    }

def get_paragraph_text(element) -> str:
    """Рекурсивно извлекает текст из элемента ODF."""
    text_content = ""
    for node in element.childNodes:
        # Если узел является текстовым, берем его данные
        if node.nodeType == node.TEXT_NODE:
            text_content += node.data
        # Если узел имеет дочерние узлы, рекурсивно извлекаем текст
        elif hasattr(node, "childNodes"):
            text_content += get_paragraph_text(node)
    return text_content

def get_odt_meta(file_path: str) -> Dict[str, Any]:
    """Извлекает метаинформацию из ODT-файла с использованием odfpy."""
    from odf.opendocument import load
    from odf.text import P
    doc = load(file_path)
    paragraphs = doc.getElementsByType(P)
    text = "\n".join(get_paragraph_text(p) for p in paragraphs)
    word_count = len(text.split())
    char_count = len(text)
    return {
        'encoding': 'utf-8',
        'word_count': word_count,
        'char_count': char_count
    }


def get_text_file_meta(file_path: str) -> Dict[str, Any]:
    """Определяет тип текстового файла и возвращает его метаинформацию"""
    ext = os.path.splitext(file_path.lower())[1]
    if ext == '.txt':
        return get_txt_meta(file_path)
    elif ext == '.docx':
        return get_docx_meta(file_path)
    elif ext == '.rtf':
        return get_rtf_meta(file_path)
    elif ext == '.odt':
        return get_odt_meta(file_path)
    else:
        return {'Error': f"Неподдерживаемый тип файла: {ext}"}
