# Museum Digital File Descriptor

Is a tool for generating XML metadata files with detailed descriptions and hash sums for selected digital files. It is designed for museums to facilitate the inclusion of digital objects into museum collections. According to Russian Federation regulations, a digital museum object consists of both the object file itself and its accompanying metadata files.

This program ensures the integrity and proper documentation of digital assets by creating structured XML files containing:
- File metadata (format, size, resolution, etc.)
- Hash sums (GR3411_2012_256, SHA1) for verification
- Additional technical details (e.g., compression type, encoding)

**Key Features:**  
✔ Supports various file types: documents, images, audio, video  
✔ Computes hash sums for authenticity verification  
✔ Extracts technical metadata (DPI, bit depth, compression, etc.)  
✔ Processes single files and entire directories  
✔ Helps museums comply with Russian digital collection standards

This tool simplifies the workflow for digital file acquisition and management in museums, ensuring compliance with national regulations and long-term preservation standards.

---


Инструмент для создания XML-файлов с описанием и хеш-суммами выбранных цифровых файлов. Разработан для музеев, чтобы упростить включение цифровых объектов в музейные коллекции. Согласно инструкциям РФ, цифровой музейный предмет состоит из самого файла объекта и сопроводительных файлов описания.

Программа обеспечивает целостность и правильную документацию цифровых активов, создавая структурированные XML-файлы с:
- Метаданными файла (формат, размер, разрешение и т. д.)
- Хеш-суммами (GR3411_2012_256, SHA1) для проверки подлинности
- Дополнительными техническими данными (тип сжатия, кодировка и др.)

**Основные возможности:**  
✔ Поддержка различных типов файлов: документы, изображения, аудио, видео  
✔ Вычисление хеш-сумм для проверки подлинности  
✔ Извлечение технических метаданных (DPI, битовая глубина, сжатие и др.)  
✔ Обработка одиночных файлов и целых директорий  
✔ Соответствие российским стандартам учета цифровых коллекций

Этот инструмент упрощает процесс приема цифровых объектов в музейные коллекции, обеспечивая соответствие нормативным требованиям и стандартам долговременного хранения.

---

## Установка
1. Установите Python 3.10+
2. Установите ImageMagick https://imagemagick.org/script/download.php

3. Скачайте репозиторий
```bash
git clone https://github.com/faralex-dev/Museum-Digital-File-Descriptor.git
cd Museum-Digital-File-Descriptor
```

4. Создайте виртуальное окружение
```bash
python -m venv venv
venv\Scripts\activate
```

5. Установите зависимости:
```bash
pip install -r requirements.txt
```
6. Установите библиотеку pystribog
```bash
git clone --depth 1  https://github.com/ddulesov/pystribog.git
cd pystribog
# Требует наличия Microsoft C++ Build Tools
# https://aka.ms/vs/17/release/vs_BuildTools.exe
pip install setuptools
python setup.py build install
cd ..
```


## Использование
Запустите программу:
```bash
# Активируем виртуальное окружение и запускаем
venv\Scripts\activate.bat
python main.py
```

## Поддерживаемые форматы
- Видео	MP4, AVI, MOV, MKV, WMV, MPEG
- Аудио	MP3, WAV, FLAC, AAC, OGG, M4A
- Изображения	JPG, PNG, TIFF, RAW (CR2, NEF)
- Документы	PDF, DOCX, RTF, ODT

Для остальных форматов программа создает xml с базовой информацией: размер, хэш, имя

