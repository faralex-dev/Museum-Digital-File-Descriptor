# Генерация XML-файлов
import os
import re
import xml.etree.ElementTree as ET
import time
from checksum import generate_file_checksum
from media_info import get_image_info, get_text_file_meta
from utils import replace_eng_with_rus, round_to_kb_or_mb, file_size_calc, insert_spaces_from_end
from pymediainfo import MediaInfo
import logging

class BaseFileHandler:
    """Базовый класс для обработки файлов"""
    def __init__(self, file_path: str, save_path: str, topography: str):
        self.file_path = file_path
        self.save_path = save_path
        self.topography = topography
        self.analyzer = FileAnalyzer(file_path, save_path, topography)

    def process(self):
        """Основной процесс обработки файла"""
        try:
            self._validate_file()
            self._create_generic_info()
            self._create_specific_info()
            self._write_output_files()
            logging.info(f"Успешно обработан файл: {self.file_path}")
        except Exception as e:
            logging.error(f"Ошибка обработки файла {self.file_path}: {str(e)}")
            raise

    def _validate_file(self):
        """Валидация входного файла"""
        if not os.path.isfile(self.file_path):
            raise FileNotFoundError(f"Файл не найден: {self.file_path}")
        if os.path.getsize(self.file_path) == 0:
            raise ValueError("Файл пустой")

    def _create_generic_info(self):
        """Создание общей информации для всех типов файлов"""
        self.analyzer._create_generic_info_xml()

    def _create_specific_info(self):
        """Создание специфической информации (должен быть реализован в подклассах)"""
        raise NotImplementedError

    def _write_output_files(self):
        """Запись выходных файлов"""
        self.analyzer._write_xml()
        self.analyzer._write_txt()
        self.analyzer._write_kamis_txt()


class VideoHandler(BaseFileHandler):
    """Обработчик видеофайлов"""
    def _create_specific_info(self):
        self.analyzer._create_video_info_xml()

class AudioHandler(BaseFileHandler):
    """Обработчик аудиофайлов"""
    def _create_specific_info(self):
        self.analyzer._create_audio_info_xml()

class ImageHandler(BaseFileHandler):
    """Обработчик изображений"""
    def _create_specific_info(self):
        self.analyzer._create_image_info_xml()

class PDFHandler(BaseFileHandler):
    """Обработчик PDF-документов"""
    def _create_specific_info(self):
        self.analyzer._create_pdf_info_xml()

class DocumentHandler(BaseFileHandler):
    """Обработчик текстовых документов"""
    def _create_specific_info(self):
        self.analyzer._create_document_info_xml()

class GenericHandler(BaseFileHandler):
    """Обработчик для неизвестных типов файлов"""
    def _create_specific_info(self):
        pass  # Нет дополнительной информации


class FileAnalyzer:
    def __init__(self, file_path: str, save_path: str, topography: str):
        self.file_path = file_path
        self.save_path = save_path
        self.metadata = {}
        self.metadata["RootXML"] = 'GMIG'
        self.metadata["hash_algo"] = 'SHA1'
        self.metadata["hash_algo_gost"] = 'GR3411_2012_256'
        self.metadata["topography"] = topography
        self.metadata["File"] = os.path.splitext(os.path.basename(self.file_path))[0]
        self.metadata["File_ext"] = os.path.splitext(os.path.basename(self.file_path))[1]
        self.key_list = ['format_info', 'format_url', 'format', 'other_duration', 'bit_rate', 'frame_rate', 'file_last_modification_date',
                         'width', 'height', 'other_display_aspect_ratio', 'scan_type', 'encoded_date', 'other_bit_depth',
                         'channel_s', 'channel_positions', 'sampling_rate', 'compression_mode', 'density', 'color_space', 'colour_primaries',
                         'BitRate_Mode', 'BitRate_Maximum', 'file_extension', 'other_maximum_bit_rate', 'other_language', 'other_bit_rate_mode']


    def _create_generic_info_xml(self):
        a, self.metadata["checksum_gost"] = generate_file_checksum(self.file_path, self.metadata["hash_algo_gost"])
        b, self.metadata["checksum"] = generate_file_checksum(self.file_path, self.metadata["hash_algo"])

        self.metadata["Type"] = 'Generic'

        self.root = ET.Element(self.metadata["RootXML"])

        self.file_info = ET.SubElement(self.root, 'File', name=self.metadata["File"])
        self.file_base_info = ET.SubElement(self.file_info, 'Сommon', name="Общие свойства")

        self.file_name = ET.SubElement(self.file_base_info, 'fileName', name="Имя файла мастер-копии")
        self.file_name.text = self.metadata["File"] + self.metadata["File_ext"]

        self.file_ext = ET.SubElement(self.file_base_info, 'file_extension', name="Формат")
        self.file_ext.text = self.metadata["File_ext"]

        self.file_date = ET.SubElement(self.file_base_info, 'date', name="Дата последнего изменения")
        self.file_date.text = str(time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(os.path.getmtime(self.file_path)))) + ' UTC'

        self.file_size = ET.SubElement(self.file_base_info, 'size', name="Размер")
        self.file_size.text = str(file_size_calc(self.file_path))

        self.file_topo = ET.SubElement(self.file_base_info, 'topography', name="Топография")
        self.file_topo.text = self.metadata["topography"]

        self.file_checksum = ET.SubElement(self.file_base_info, 'Checksum', name="Контрольная сумма")

        self.file_checksum_gost = ET.SubElement(self.file_checksum, 'hash', type=self.metadata["hash_algo_gost"])
        self.file_checksum_gost.text = self.metadata["checksum_gost"]

        self.file_checksum_sha256 = ET.SubElement(self.file_checksum, 'hash', type=self.metadata["hash_algo"])
        self.file_checksum_sha256.text = self.metadata["checksum"]

    def _create_video_info_xml(self):
        # self._create_generic_info_xml()
        self.metadata["Type"] = 'Video'
        self.media_info = MediaInfo.parse(self.file_path)
        self.media_tracks = ET.SubElement(self.file_info, 'Extended', name="Расширенные свойства")

        for track in self.media_info.tracks:
            track_element = ET.SubElement(self.media_tracks, 'Ext', type=track.track_type)
            for key, value in track.to_data().items():
                if value:
                    if str(key) in self.key_list:
                        if str(key) == 'file_last_modification_date':
                            self.file_date.text = str(value)

                        elif str(key) == 'other_duration' and str(track.track_type) == 'General':
                            element = ET.SubElement(track_element, 'duration', name='Продолжительность')
                            self.metadata["file_duration"] = element.text = replace_eng_with_rus(str(value[1])) + ' (' + str(value[4]) + ')'

                        elif str(key) == 'frame_rate' and str(track.track_type) == 'General':
                            element = ET.SubElement(track_element, 'frame_rate', name='Частота кадров (FPS)')
                            self.metadata["file_fps"] = element.text = str(value) + ' кадров/сек'

                        elif str(key) == 'format':
                            element = ET.SubElement(track_element, key, name='Формат')
                            self.metadata["file_format"] = element.text = str(value)
                            if track.track_type == 'General':
                                self.metadata["file_format_general"] = str(value)
                            if track.track_type == 'Video':
                                self.metadata["file_format_video"] = str(value)
                            if track.track_type == 'Audio':
                                self.metadata["file_format_audio"] = str(value)
                            if track.track_type == 'Image':
                                self.metadata["file_format_image"] = str(value)


                        elif str(key) == 'format_info':
                            element = ET.SubElement(track_element, key, name='Формат/Информация')
                            self.metadata["file_format_info"] = element.text = str(value)
                            if track.track_type == 'Video':
                                self.metadata["file_format_info_video"] = str(value)
                            if track.track_type == 'Audio':
                                self.metadata["file_format_info_audio"] = str(value)
                            if track.track_type == 'Image':
                                self.metadata["file_format_info_image"] = str(value)

                        elif str(key) == 'format_url':
                            element = ET.SubElement(track_element, key, name='Описание формата в интернете')
                            if str(value) == "http://developers.videolan.org/x264.html":
                                element.text = 'https://www.videolan.org/developers/x264.html'
                            else:
                                element.text = str(value)

                        elif str(key) == 'other_bit_rate_mode':
                            element = ET.SubElement(track_element, 'bit_rate_mode', name='Вид битрейта')
                            if str(value[0]) == 'Variable':
                                element.text = 'Переменный'
                            elif str(value[0]) == 'Constant':
                                element.text = 'Постоянный'
                            else:
                                element.text = str(value[0])


                        elif str(key) == 'bit_rate':
                            # Ищем число в строке значения битрейта
                            number_match = re.search(r'\d+', str(value))
                            if number_match:
                                # Преобразуем найденное число в целое
                                number = int(number_match.group())
                                # Преобразуем битрейт в килобиты или мегабиты
                                round_bit = round_to_kb_or_mb(number)
                                # Формируем строку с битрейтом и добавляем пробелы для читаемости
                                bitrate_value = (
                                    f"{round_bit} ({insert_spaces_from_end(str(number))} бит/с)"
                                )
                                element = ET.SubElement(track_element, 'bit_rate', name='Битрейт')
                                # Сохраняем значение битрейта в метаданные и XML
                                if track.track_type == 'Audio':
                                    self.metadata["file_bitrate_audio"] = element.text = bitrate_value
                                else:
                                    self.metadata["file_bitrate_video"] = element.text = bitrate_value

                        elif str(key) == 'other_maximum_bit_rate':
                            element = ET.SubElement(track_element, 'maximum_bit_rate', name='Максимальный битрейт')
                            element.text = str(value[0])

                        elif str(key) == 'width':
                            element = ET.SubElement(track_element, key, name='Ширина')
                            self.metadata["file_width"] = element.text = str(value)

                        elif str(key) == 'height':
                            element = ET.SubElement(track_element, key, name='Высота')
                            self.metadata["file_height"] = element.text = str(value)

                        elif str(key) == 'other_display_aspect_ratio':
                            element = ET.SubElement(track_element, 'display_aspect_ratio', name='Соотношение сторон дисплея')
                            element.text = str(value[0])

                        elif str(key) == 'scan_type':
                            element = ET.SubElement(track_element, key, name='Тип развёртки')
                            if str(value) == 'Progressive':
                                element.text = 'Прогрессивная'
                            elif str(value) == 'Interlaced':
                                element.text = 'Чересстрочная'
                            else:
                                element.text = str(value)

                        elif str(key) == 'encoded_date':
                            element = ET.SubElement(track_element, key, name='Дата кодирования')
                            self.metadata["file_enc_date"] = element.text = str(value)

                        elif str(key) == 'other_language' and str(track.track_type) == 'Audio':
                            element = ET.SubElement(track_element, 'language', name='Язык')
                            if str(value[0]) == 'English':
                                element.text = 'Английский'
                            elif str(value[0]) == 'Russian':
                                element.text = 'Русский'
                            else:
                                element.text = str(value[0])

                        elif str(key) == 'sampling_rate':
                            element = ET.SubElement(track_element, key, name='Частота дискретизации')
                            self.metadata["file_hz"] = element.text = insert_spaces_from_end(str(value)) + ' Hz'

                        elif str(key) == 'channel_s':
                            element = ET.SubElement(track_element, key, name='Канал(-ы)')
                            self.metadata["file_chanel"] = element.text = str(value)

                        elif str(key) == 'channel_positions':
                            element = ET.SubElement(track_element, key, name='Расположение каналов')
                            self.metadata["file_chanel_num"] = element.text = str(value)

                        elif str(key) == 'compression_mode':
                            element = ET.SubElement(track_element, key, name='Метод сжатия')
                            if str(value) == 'Lossy':
                                self.metadata["file_compression"] = element.text = 'С потерями'
                                if track.track_type == 'Video':
                                    self.metadata["file_compression_video"] = element.text
                                if track.track_type == 'Audio':
                                    self.metadata["file_compression_audio"] = element.text
                                if track.track_type == 'Image':
                                    self.metadata["file_compression_image"] = element.text
                            elif str(value) == 'Lossless':
                                element.text = 'Без потерь'
                                if track.track_type == 'Video':
                                    self.metadata["file_compression_video"] = element.text
                                if track.track_type == 'Audio':
                                    self.metadata["file_compression_audio"] = element.text
                                if track.track_type == 'Image':
                                    self.metadata["file_compression_image"] = element.text
                            else:
                                self.metadata["file_compression"] = element.text = str(value)

                        elif str(key) == 'color_space':
                            element = ET.SubElement(track_element, key, name='Цветовое пространство')
                            self.metadata["file_color_space"] = element.text = str(value)

                        elif str(key) == 'other_bit_depth':
                            element = ET.SubElement(track_element, key, name='Битовая глубина')
                            self.metadata["file_bit_depth"] = element.text = str(value[0])

                        elif str(key) == 'colour_primaries':
                            element = ET.SubElement(track_element, key, name='Основные цвета')
                            element.text = str(value[0])

                        elif str(key) == 'file_extension':
                            self.file_ext.text = self.metadata["File_ext"] = str(value)

                        else:
                            if str(key) != 'other_duration' and str(key) != 'frame_rate' and str(key) != 'other_language' \
                                    and str(key) != 'encoded_date' and str(key) != 'format' and str(key) != 'format_info':
                                element = ET.SubElement(track_element, key)
                                element.text = str(value)

    def _create_audio_info_xml(self):
        # self._create_generic_info_xml()
        self._create_video_info_xml()
        self.metadata["Type"] = 'Audio'


    def _create_image_info_xml(self):
        # self._create_generic_info_xml()
        self.metadata["Type"] = 'Image'
        self.image_info = get_image_info(self.file_path)

        media_tracks = ET.SubElement(self.file_info, 'Extended', name="Расширенные свойства")
        track_element = ET.SubElement(media_tracks, 'Ext', type="Image")

        if self.image_info.get('format'):
            element = ET.SubElement(track_element, 'format', name='Формат')
            element.text = self.image_info['format']
        if self.image_info.get('color_mode'):
            element = ET.SubElement(track_element, 'color_space', name='Цветовое пространство')
            self.metadata["color_mode"] = element.text = self.image_info['color_mode']
        if self.image_info.get('bit_depth'):
            element = ET.SubElement(track_element, 'bit_depth', name='Битовая глубина')
            self.metadata["file_bit_depth"] = element.text = self.image_info['bit_depth']
        if self.image_info.get('width_px'):
            element = ET.SubElement(track_element, 'width', name='Ширина')
            self.metadata["file_width"] = element.text = str(self.image_info['width_px'])
        if self.image_info.get('height_px'):
            element = ET.SubElement(track_element, 'height', name='Высота')
        self.metadata["file_height"] =  element.text = str(self.image_info['height_px'])
        if self.image_info.get('dpi'):
            element = ET.SubElement(track_element, 'density', name='Точек на дюйм')
            self.metadata["density"] = element.text = self.image_info['dpi']
        if self.image_info.get('print_size_cm'):
            element = ET.SubElement(track_element, 'print_size_cm', name='Размер при печати (см)')
            self.metadata["print_size_cm"] = element.text = self.image_info['print_size_cm']
        if self.image_info.get('compression'):
            element = ET.SubElement(track_element, 'compression_mode', name='Метод сжатия')
            self.metadata["compression"] = element.text = self.image_info['compression']
        if self.image_info.get('tiff_metadata'):
            tiff_meta = self.image_info['tiff_metadata']
            tiff_meta_element = ET.SubElement(track_element, 'tiff_metadata', name='tiff метаданные')
            if isinstance(tiff_meta, dict):
                for key, value in tiff_meta.items():
                    tag_element = ET.SubElement(tiff_meta_element, 'tag', name=key)
                    tag_element.text = str(value)
            else:
                tiff_meta_element.text = str(tiff_meta)


    def _create_pdf_info_xml(self):
        """Генерация XML для PDF-файлов."""
       # self._create_generic_info_xml()

        self.metadata["Type"] = 'PDF'
        import PyPDF2
        pdf_reader = PyPDF2.PdfReader(self.file_path)
        self.metadata["total_pages"] = str(len(pdf_reader.pages))

        media_tracks = ET.SubElement(self.file_info, 'Extended', name="Расширенные свойства")
        track_element = ET.SubElement(media_tracks, 'Ext', type="Document")
        element = ET.SubElement(track_element, 'totalPages', name='Количество страниц')
        element.text = self.metadata["total_pages"]

    def _create_document_info_xml(self):
        """Генерация XML для PDF-файлов."""
        # self._create_generic_info_xml()
        self.metadata["Type"] = 'Document'

        media_tracks = ET.SubElement(self.file_info, 'Extended', name="Расширенные свойства")
        track_element = ET.SubElement(media_tracks, 'Ext', type="Document")
        self.docdata = get_text_file_meta(self.file_path)
        if self.docdata.get('encoding'):
            element = ET.SubElement(track_element, 'encoding', name='Кодировка текста')
            element.text = self.docdata['encoding']
        if self.docdata.get('word_count'):
            element = ET.SubElement(track_element, 'word_count', name='Количество слов')
            element.text = str(self.docdata['word_count'])
        if self.docdata.get('char_count'):
            element = ET.SubElement(track_element, 'char_count', name='Количество букв')
            element.text = str(self.docdata['char_count'])



    def _write_xml(self):
        # Преобразование XML в форматированный текст
        ET.indent(self.root, space="    ")
        # Запись форматированного XML в файл
        with open(self.save_path, "w", encoding="utf-8") as f:
            f.write(ET.tostring(self.root, encoding='unicode', method='xml', xml_declaration=True))

    def _write_txt(self):
        # Запись файла контрольных сумм
        crc_file = self.metadata["File"] + '.txt'
        with open(os.path.dirname(self.save_path) + '\\' + crc_file, "w+", encoding="utf-8") as f:
            f.write(os.path.basename(self.file_path) + '\n')
            f.write('Контрольная сумма:' + '\n')
            f.write(self.metadata["hash_algo_gost"] + ': ' + self.metadata["checksum_gost"] + '\n')
            f.write(self.metadata["hash_algo"] + ': ' + self.metadata["checksum"] + '\n')
            f.write('\n')
            f.write(os.path.basename(self.save_path) + '\n')
            f.write('Контрольная сумма:' + '\n')
            xml_hash_algo_gost, xml_hash_gost = generate_file_checksum(self.save_path, hash_algo=self.metadata["hash_algo_gost"])
            f.write(xml_hash_algo_gost + ': ' + xml_hash_gost + '\n')
            xml_hash_algo, xml_hash = generate_file_checksum(self.save_path, hash_algo=self.metadata["hash_algo"])
            f.write(xml_hash_algo + ': ' + xml_hash)
            f.close()

    def _write_kamis_txt_video(self, f):
        f.write('## Расширенные свойства ##\n')
        f.write('_General\n')
        f.write(f'Формат: {self.metadata["file_format_general"]}\n')
        if self.metadata.get("file_duration"):
            f.write(f'Продолжительность: {self.metadata["file_duration"]}\n')
        if self.metadata.get("file_fps"):
            f.write(f'Частота кадров (FPS): {self.metadata["file_fps"]}\n\n')

        f.write('_Video\n')
        if self.metadata.get("file_format_video"):
            f.write(f'Формат: {self.metadata["file_format_video"]}\n')
        if self.metadata.get("file_format_info_video"):
            f.write(f'Формат/Информация: {self.metadata["file_format_info_video"]}\n')
        if self.metadata.get("file_enc_date"):
            f.write(f'Дата кодирования: {self.metadata["file_enc_date"]}\n')
        if self.metadata.get("file_bitrate_video"):
            f.write(f'Битрейт: {self.metadata["file_bitrate_video"]}\n')
        if self.metadata.get("file_width"):
            f.write('Разрешение: ' + self.metadata["file_width"] + ' x ' + self.metadata["file_height"] + '\n\n')

        f.write('_Audio\n')
        if self.metadata.get("file_format_audio"):
            f.write(f'Формат: {self.metadata["file_format_audio"]}\n')
        if self.metadata.get("file_format_info_audio"):
            f.write(f'Формат/Информация: {self.metadata["file_format_info_audio"]}\n')
        if self.metadata.get("file_bitrate_audio"):
            f.write(f'Битрейт: {self.metadata["file_bitrate_audio"]}\n')
        if self.metadata.get("file_chanel"):
            f.write(f'Канал(-ы): {self.metadata["file_chanel"]}\n')
        if self.metadata.get("file_chanel_num"):
            f.write(f'Расположение каналов: {self.metadata["file_chanel_num"]}\n')
        if self.metadata.get("file_hz"):
            f.write(f'Частота дискретизации: {self.metadata["file_hz"]}\n')
        if self.metadata.get("file_compression_audio"):
            f.write(f'Метод сжатия: {self.metadata["file_compression_audio"]}\n')

    def _write_kamis_txt_audio(self, f):
        f.write('## Расширенные свойства ##\n')
        f.write('_General\n')
        f.write(f'Формат: {self.metadata["file_format_general"]}\n')
        if self.metadata.get("file_duration"):
            f.write(f'Продолжительность: {self.metadata["file_duration"]}\n')

        f.write('_Audio\n')
        if self.metadata.get("file_format_audio"):
            f.write(f'Формат: {self.metadata["file_format_audio"]}\n')
        if self.metadata.get("file_format_info_audio"):
            f.write(f'Формат/Информация: {self.metadata["file_format_info_audio"]}\n')
        if self.metadata.get("file_bitrate_audio"):
            f.write(f'Битрейт: {self.metadata["file_bitrate_audio"]}\n')
        if self.metadata.get("file_chanel"):
            f.write(f'Канал(-ы): {self.metadata["file_chanel"]}\n')
        if self.metadata.get("file_chanel_num"):
            f.write(f'Расположение каналов: {self.metadata["file_chanel_num"]}\n')
        if self.metadata.get("file_hz"):
            f.write(f'Частота дискретизации: {self.metadata["file_hz"]}\n')
        if self.metadata.get("file_compression_audio"):
            f.write(f'Метод сжатия: {self.metadata["file_compression_audio"]}\n')

    def _write_kamis_txt_image(self, f):
        f.write('## Расширенные свойства ##\n')
        f.write('_General\n')
        f.write(f'Формат: {self.image_info['format']}\n\n')
        f.write('_Image\n')
        if self.metadata.get("file_width"):
            f.write('Разрешение: ' + self.metadata["file_width"] + ' x ' + self.metadata["file_height"] + '\n')
        if self.metadata.get("density"):
            f.write(f'Точек на дюйм: {self.metadata["density"]}\n')
        if self.metadata.get("print_size_cm"):
            f.write(f'Размер при печати (см): {self.metadata["print_size_cm"]}\n')
        if self.metadata.get("color_mode"):
            f.write(f'Цветовое пространство: {self.metadata["color_mode"]}\n')
        if self.metadata.get("file_bit_depth"):
            f.write(f'Глубина цвета (обычно на канал): {self.metadata["file_bit_depth"]}\n')
        if self.metadata.get("compression"):
            f.write(f'Метод сжатия: {self.metadata["compression"]}\n')


    def _write_kamis_txt_pdf(self, f):
        f.write('## Расширенные свойства ##\n')
        f.write('_General\n')
        f.write(f'Формат: {self.metadata["Type"]}\n\n')                     # Формат не определяется автоматически!
        f.write('_Document\n')
        f.write(f'Количество страниц: {self.metadata["total_pages"]}\n')

    def _write_kamis_txt_document(self, f):
        f.write('## Расширенные свойства ##\n')
        f.write('_General\n')
        f.write(f'Формат: {self.metadata["Type"]}\n\n')                     # Формат не определяется автоматически!
        f.write('_Document\n')
        if self.docdata.get('encoding'):
            f.write(f'Кодировка текста: {self.docdata["encoding"]}\n')
        if self.docdata.get('word_count'):
            f.write(f'Количество слов: {self.docdata["word_count"]}\n')
        if self.docdata.get('char_count'):
            f.write(f'Количество букв: {self.docdata["char_count"]}\n')

    def _write_kamis_txt(self):
        # Запись файла txt для ручного заполнения КАМИС
        kamis_file = self.metadata["File"] + '_KAMIS.txt'
        with open(os.path.dirname(self.save_path) + '\\' + kamis_file, "w+", encoding="utf-8") as f:
            f.write('Имя файла мастер-копии: ' + self.metadata["File"] + self.metadata["File_ext"] + '\n')
            f.write('Формат: ' + self.metadata["File_ext"] + '\n')
            f.write('Размер: ' + self.file_size.text + '\n')
            f.write('Дата: ' + self.file_date.text + '\n')
            f.write('Топография: ' + self.file_topo.text + '\n')
            f.write('Контрольная сумма ' + self.metadata["hash_algo_gost"] + ': ' + self.metadata["checksum_gost"] + '\n')
            f.write('Контрольная сумма ' + self.metadata["hash_algo"] + ': ' + self.metadata["checksum"] + '\n\n')
            if self.metadata.get("Type") == 'Video':
                self._write_kamis_txt_video(f)
            if self.metadata.get("Type") == 'Audio':
                self._write_kamis_txt_audio(f)
            if self.metadata.get("Type") == 'Image':
                self._write_kamis_txt_image(f)
            if self.metadata.get("Type") == 'PDF':
                self._write_kamis_txt_pdf(f)
            if self.metadata.get("Type") == 'Document':
                self._write_kamis_txt_document(f)
            f.close()


# Функции-обертки
def create_video_info_xml(file_path: str, save_path: str, topo: str) -> None:
    handler = VideoHandler(file_path, save_path, topo)
    handler.process()

def create_audio_info_xml(file_path: str, save_path: str, topo: str) -> None:
    handler = AudioHandler(file_path, save_path, topo)
    handler.process()

def create_image_info_xml(file_path: str, save_path: str, topo: str) -> None:
    handler = ImageHandler(file_path, save_path, topo)
    handler.process()

def create_pdf_info_xml(file_path: str, save_path: str, topo: str) -> None:
    handler = PDFHandler(file_path, save_path, topo)
    handler.process()

def create_document_info_xml(file_path: str, save_path: str, topo: str) -> None:
    handler = DocumentHandler(file_path, save_path, topo)
    handler.process()

def create_generic_info_xml(file_path: str, save_path: str, topo: str) -> None:
    handler = GenericHandler(file_path, save_path, topo)
    handler.process()