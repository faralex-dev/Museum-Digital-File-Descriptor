# Museum Digital File Descriptor

Программа для хранителей: создаёт описания цифровых музейных предметов и
проверяет их сохранность по главе 33 Единых правил (приём, учёт и хранение
цифровых музейных предметов).

Для каждого предмета создаются:

- **файл метаданных** — XML в UTF-8: учётный номер, формат, размер, даты,
  контрольные суммы и технические характеристики по п. 33.14
  (продолжительность, разрешение, битрейт, кодеки, каналы, частота; метод
  сжатия, размер и разрешение изображения; кодировка, язык, количество знаков
  и страниц текста);
- **файл контрольных сумм** мастер-копии и файла метаданных —
  **SHA-1** (так считает КАМИС — суммы совпадают с учётной базой) и
  **ГОСТ 34.11-2018** (п. 33.15);
- **памятка для КАМИС** (по желанию) и сводная таблица CSV.

Во вкладке **«Сверка»** программа пересчитывает контрольные суммы, пробует
открыть файлы, находит пропавшие и лишние файлы, проверяет резервную копию
и выдаёт отчёт с датой для поля «Сверка» в КАМИС (пп. 33.5–33.8).

Формат описания и отличия от версии 1.x: [docs/format-2.0.md](docs/format-2.0.md).

## Установка

### Готовая программа

Скачайте архив для своей системы на странице
[Releases](https://github.com/faralex-dev/Museum-Digital-File-Descriptor/releases),
распакуйте и запустите:

- Windows — `MuseumDigitalFileDescriptor.exe` (рядом лежит `mdfd.exe` для командной строки);
- macOS — `MuseumDigitalFileDescriptor.app`. Программа не подписана, поэтому
  при первом запуске откройте её через контекстное меню → «Открыть».

Python и другие программы устанавливать не нужно.

### Из исходников

Нужен Python 3.10 или новее.

```bash
git clone https://github.com/faralex-dev/Museum-Digital-File-Descriptor.git
cd Museum-Digital-File-Descriptor
python -m venv .venv
```

Активируйте окружение (Windows: `.venv\Scripts\activate`, macOS/Linux:
`source .venv/bin/activate`) и установите программу:

```bash
pip install -r requirements.txt
python setup.py build_ext --inplace
python main.py
```

Вторая команда собирает модуль ГОСТ на C. Если компилятора нет, программа всё
равно работает, но хеш ГОСТ считается примерно в сто раз медленнее
(на вкладке «О программе» это видно). На Linux дополнительно нужна системная
библиотека MediaInfo (`libmediainfo0v5`).

## Как пользоваться

### Описание

1. Выберите файл или папку (или перетащите в окно).
2. Укажите, что считать предметом:
   - **Папка — один предмет.** Все файлы папки, включая подпапки, — мастер-копии
     одного предмета. Описание называется по имени папки.
   - **Каждая подпапка — отдельный предмет.** Выберите папку репозитория: каждая
     её подпапка будет описана отдельно.
   - **Каждый файл — отдельный предмет.** Описание рядом с каждым файлом:
     `фото.jpg.xml`, `фото.jpg.checksums.txt`.
3. Заполните сведения о предмете. Учётный номер, если его не ввести, берётся из
   имени папки до первого «_» (п. 33.17): `ГМИГ КП ЭФ-55_Петров А.А._Соловки` →
   `ГМИГ КП ЭФ-55`.
4. Нажмите «Создать описание».

Уже описанные предметы пропускаются. Если включить «Пересоздавать
существующие описания», программа сначала сверит файлы со старым описанием и
откажется перезаписывать его, если файлы изменились.

### Сверка

Выберите папку предмета или всего репозитория, при необходимости — папку
резервной копии с той же структурой, и нажмите «Начать сверку». Отчёт
сохраняется в текст или CSV.

### Командная строка

```bash
mdfd describe "D:\Репозиторий" --mode subfolders --topography "Сервер 1" --csv kamis.csv
mdfd verify "D:\Репозиторий" --backup "E:\Копия" --report сверка.txt
mdfd info видео.mp4 --hash
```

Из исходников вместо `mdfd` пишите `python main.py`. Код возврата `verify`:
0 — всё в порядке, 3 — найдены проблемы.

## Поддерживаемые форматы

| Вид | Форматы |
|---|---|
| Видео | MP4, MOV, AVI, MKV, WebM, WMV, MPEG, TS/MTS, MXF, FLV и др. (через MediaInfo) |
| Аудио | WAV/BWF, FLAC, MP3, AAC, M4A, OGG/Opus, AIFF, WMA |
| Изображения | TIFF, JPEG, PNG, JPEG 2000, WebP, GIF, BMP, DNG и RAW камер (CR2, NEF, ARW…, нужен rawpy), HEIC |
| Текст | PDF (версия, PDF/A, страницы, текстовый слой), DOCX, DOC, ODT, RTF, TXT, CSV, HTML, XML, а также XLSX, PPTX, ODS, ODP |

Для остальных файлов записываются размер, даты и контрольные суммы.

## Разработка

```bash
pip install -r requirements-dev.txt
python setup.py build_ext --inplace
python -m pytest
pyinstaller packaging/mdfd.spec
```

Сборки для Windows и macOS делает GitHub Actions
([.github/workflows/build.yml](.github/workflows/build.yml)); при создании
тега `v*` архивы прикладываются к черновику релиза.

Устройство кода:

| Модуль | Что делает |
|---|---|
| `mdfd/hashing/` | контрольные суммы; `_streebog.c` — ГОСТ 34.11-2018 на C, `streebog.py` — запасная реализация на Python |
| `mdfd/probes/` | технические сведения: `media` (MediaInfo), `image` (Pillow, rawpy), `pdf` (pypdf), `office`, `text` |
| `mdfd/package.py` | поиск файлов мастер-копии, создание описания |
| `mdfd/xmlio.py`, `checksums.py`, `kamis.py` | запись XML, файла контрольных сумм, памятки и CSV |
| `mdfd/verify.py` | сверка |
| `mdfd/gui.py`, `cli.py` | интерфейс и командная строка |
| `mdfd/formats.py` | справочник форматов и идентификаторов PRONOM |

Обзор кода версии 1.x — [docs/review-1.x.md](docs/review-1.x.md),
история изменений — [CHANGELOG.md](CHANGELOG.md).

---

**English.** A tool for museums to describe digital museum objects according
to Russian regulations: it writes a UTF-8 XML metadata file and a checksum file
(SHA-1, as used by the KAMIS collection database, and GOST R 34.11-2012/34.11-2018 "Streebog") for each object folder,
extracts technical metadata (MediaInfo, Pillow, pypdf), adds PRONOM format
identifiers, and verifies fixity of the repository and its backups.
