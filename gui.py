import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinterdnd2 import DND_FILES, TkinterDnD
from ttkthemes import ThemedStyle
from xml_generator import create_pdf_info_xml, create_generic_info_xml, create_video_info_xml, create_audio_info_xml, create_image_info_xml, create_document_info_xml
from utils import *
from pathlib import Path
from typing import Dict
import logging

logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# Заголовок в окне программы
TITLE = "Museum Digital File Descriptor v1.0.0 / faralex"

# Исключаем из обработки при обработке директорий
SKIP_EXT = ('.txt', '.xml')

# Конфигурация поддерживаемых форматов
FILE_TYPES: Dict[str, Dict[str, list]] = {
    "documents": {
        "extensions": [".docx", ".txt", ".rtf", ".odt"],
        "handler": create_document_info_xml  # Функция для документов
    },
    "pdf": {
        "extensions": [".pdf"],
        "handler": create_pdf_info_xml  # Функция для документов
    },
    "photos": {
        "extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".cr2", ".nef", ".rw2"],
        "handler": create_image_info_xml  # Функция для изображений
    },
    "audio": {
        "extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
        "handler": create_audio_info_xml  # Функция для аудио
    },
    "video": {
        "extensions": [".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".mpeg"],
        "handler": create_video_info_xml  # Функция для видео
    }
}


def select_source_file():
    """Выбор файла или папки в зависимости от режима."""
    file_path = filedialog.askdirectory() if folder_var.get() else filedialog.askopenfilename()
    if file_path:
        source_file_entry.delete(0, tk.END)
        source_file_entry.insert(0, file_path)
        save_path_entry.delete(0, tk.END)
        base_path = os.path.splitext(os.path.abspath(file_path))[0]
        save_path_entry.insert(0, base_path if folder_var.get() else f"{base_path}.xml")


def select_save_path():
    """Выбор пути сохранения XML-файла."""
    initial_file = os.path.splitext(os.path.basename(source_file_entry.get()))[0] if source_file_entry.get() else ""
    file_path = filedialog.asksaveasfilename(defaultextension=".xml", filetypes=[("XML files", "*.xml")], initialfile=initial_file)

    if file_path:
        save_path_entry.delete(0, tk.END)
        save_path_entry.insert(0, file_path)

def process_file(file_path: str, save_path: str, topo: str) -> None:
    """Определяет тип файла и вызывает соответствующую функцию обработки."""
    try:
        file_ext = Path(file_path).suffix.lower()
        file_type = detect_file_type(file_ext)

        if handler := FILE_TYPES.get(file_type, {}).get("handler"):
            handler(file_path, save_path, topo)
        else:
            handle_unknown_type(file_path, save_path, topo)

    except Exception as e:
        messagebox.showerror("Ошибка", f"Ошибка при обработке {file_path}: {e}")

def detect_file_type(extension: str) -> str:
    """Определяет категорию файла по расширению."""
    for file_type, config in FILE_TYPES.items():
        if extension in config["extensions"]:
            return file_type
    return "other"

def handle_unknown_type(file_path: str, save_path: str, topo: str) -> None:
    """Обработка файлов неизвестного типа."""
    # Реализация для других файлов
    create_generic_info_xml(file_path, save_path, topo)
    # Или можно генерировать ошибку:
    # raise ValueError(f"Unsupported file type: {Path(file_path).suffix}")


def count_files(folder_path):
    """Подсчет количества файлов в папке, исключая .txt и .xml."""
    return sum(
        1 for root, _, files in os.walk(folder_path)
        for file in files if not file.endswith(SKIP_EXT)
    )

def process_folder(folder_path, save_folder_path, topo):
    """Обрабатывает файлы в папке, создавая XML."""
    total_files = count_files(folder_path)
    current_files = 0

    for roots, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(SKIP_EXT):
                continue  # Пропуск ненужных файлов

            file_path = os.path.join(roots, file)
            save_path = os.path.splitext(file_path)[0] + ".xml"

            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            process_file(file_path, save_path, topo)

            current_files += 1
            progress = (current_files / total_files) * 100
            progress_bar['value'] = progress
            progress_label.config(text=f"Обработано: {current_files} / {total_files} файлов")
            root.update_idletasks()



def on_generate_click():
    """Запускает обработку файла или папки."""
    source_file = source_file_entry.get()
    save_path = save_path_entry.get()
    topo = topo_entry.get()

    if not source_file or not save_path:
        messagebox.showwarning("Предупреждение", "Выберите файл/папку и путь сохранения.")
        return

    progress_bar['value'] = 0
    if folder_var.get():
        process_folder(source_file, os.path.dirname(save_path), topo)
        messagebox.showinfo("Успешно", f"Сгенерированы XML для папки {save_path}.")
    else:
        process_file(source_file, save_path, topo)
        progress_bar['value'] = 100
        progress_label.config(text="Обработано: 1 файл")
        messagebox.showinfo("Успешно", f"Сгенерирован XML для файла {save_path}.")

def on_drop(event):
    """Обрабатывает перетаскивание файла в окно."""
    file_path = event.data.strip('{}')
    if os.path.isfile(file_path):
        source_file_entry.delete(0, tk.END)
        source_file_entry.insert(0, file_path)
        if not save_path_entry.get():
            save_path_entry.insert(0, os.path.splitext(os.path.abspath(file_path))[0] + '.xml')

def start_gui():
    """Запуск графического интерфейса."""
    global root, source_file_entry, save_path_entry, folder_var, progress_bar, progress_label, topo_entry

    root = TkinterDnD.Tk()
    root.title(TITLE)
    root.resizable(True, False)

    # Применение темы
    style = ThemedStyle(root)
    style.set_theme("arc")

    main_frame = ttk.Frame(root, padding="10")
    main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    ttk.Label(main_frame, text="Исходный файл / папка:").grid(row=0, column=0, sticky=tk.W)
    source_file_entry = ttk.Entry(main_frame, width=50)
    source_file_entry.grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
    ttk.Button(main_frame, text="Обзор...", command=select_source_file).grid(row=0, column=2)


    ttk.Label(main_frame, text="Пусть сохранения:").grid(row=1, column=0, sticky=tk.W)
    save_path_entry = ttk.Entry(main_frame, width=50)
    save_path_entry.grid(row=1, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
    ttk.Button(main_frame, text="Обзор...", command=select_save_path).grid(row=1, column=2)

    # Поле для топографии
    ttk.Label(main_frame, text="Топография:").grid(row=2, column=0, sticky=tk.W)
    topo_entry = ttk.Entry(main_frame, width=50)
    topo_entry.grid(row=2, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
    topo_entry.insert(0, "Цифровой репозиторий - Музей истории ГУЛАГа")

    # Добавление чекбокса для обработки папки
    folder_var = tk.BooleanVar()
    ttk.Checkbutton(main_frame, text="Обрабатывать файлы во всех подпапках", variable=folder_var).grid(row=3, column=0, columnspan=3, pady=5)

    # Создание метки для отображения прогресса
    progress_label = ttk.Label(main_frame, text="Обработано: 0 файлов")
    progress_label.grid(row=4, column=0, columnspan=3, pady=5)

    progress_bar = ttk.Progressbar(main_frame, orient="horizontal", length=400, mode="determinate")
    progress_bar.grid(row=5, column=0, columnspan=3, pady=10, sticky=(tk.W, tk.E))

    ttk.Button(main_frame, text="Создать XML", command=on_generate_click).grid(row=6, column=0, columnspan=3, pady=10)

    main_frame.grid_rowconfigure(0, weight=1)
    main_frame.grid_columnconfigure(1, weight=1)

    root.drop_target_register(DND_FILES)
    root.dnd_bind('<<Drop>>', on_drop)
    root.mainloop()