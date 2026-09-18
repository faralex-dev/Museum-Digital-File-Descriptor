"""Графический интерфейс (Tkinter).

Долгая работа (хеширование, сверка) идёт в фоновом потоке; поток передаёт
события в очередь, окно забирает их по таймеру — интерфейс не зависает.
"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, FORMAT_VERSION, __version__, hashing, kamis, package, textfmt, verify
from .model import ItemInfo
from .settings import Settings, config_dir, log_path

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # перетаскивание файлов — необязательная возможность
    TkinterDnD = None
    DND_FILES = None

log = logging.getLogger("mdfd")

PAD = 6


def setup_logging() -> None:
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path(), encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def open_in_file_manager(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        messagebox.showerror("Ошибка", f"Не удалось открыть {path}: {exc}")


class Worker:
    """Фоновая задача с отменой и очередью событий."""

    def __init__(self, app: "App"):
        self.app = app
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, target, *args) -> None:
        self.cancel.clear()
        self.thread = threading.Thread(target=self._run, args=(target, *args), daemon=True)
        self.thread.start()

    def _run(self, target, *args) -> None:
        try:
            target(*args)
        except hashing.Cancelled:
            self.events.put(("cancelled",))
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка фоновой задачи")
            self.events.put(("fatal", f"{type(exc).__name__}: {exc}"))

    def emit(self, *event) -> None:
        self.events.put(event)


class Progress:
    """Индикатор: полоса по байтам + подпись."""

    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self.label = ttk.Label(self.frame, text="")
        self.label.pack(fill="x")
        self.bar = ttk.Progressbar(self.frame, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", pady=(2, 0))
        self.total = 0
        self.done = 0

    def reset(self, total: int = 0, text: str = "") -> None:
        self.total, self.done = total, 0
        self.bar["value"] = 0
        self.label["text"] = text

    def advance(self, label: str, n: int) -> None:
        self.done += n
        if self.total:
            self.bar["value"] = min(1000, int(self.done * 1000 / self.total))
        self.label["text"] = f"{label} — {textfmt.size(self.done).split(' (')[0]} из {textfmt.size(self.total).split(' (')[0]}"

    def finish(self, text: str) -> None:
        self.bar["value"] = 1000
        self.label["text"] = text


class Tooltip:
    """Всплывающая подсказка при наведении мыши."""

    DELAY_MS = 500

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        self.job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self.job = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self) -> None:
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self) -> None:
        if self.window is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, justify="left", wraplength=420, background="#ffffe8",
                 foreground="#202020", relief="solid", borderwidth=1, padx=8, pady=5).pack()

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.window is not None:
            self.window.destroy()
            self.window = None


def tip(widget, text: str):
    Tooltip(widget, text)
    return widget


MODE_TIPS = {
    package.MODE_FOLDER: (
        "Выбранная папка — это один предмет. Все файлы в ней, включая подпапки, — его мастер-копии; "
        "контрольные суммы считаются для каждого файла отдельно и записываются в один файл сумм.\n"
        "Описание кладётся в эту же папку и называется по её имени."),
    package.MODE_SUBFOLDERS: (
        "Выбрана папка репозитория. Каждая её подпапка описывается как отдельный предмет, "
        "учётный номер берётся из имени подпапки.\nУже описанные предметы пропускаются — удобно "
        "запускать на весь репозиторий после новых поступлений. Файлы, лежащие прямо в выбранной "
        "папке, пропускаются."),
    package.MODE_FILES: (
        "Каждый файл в папке (и в подпапках) — отдельный предмет. Описание кладётся рядом с файлом: "
        "«фото.jpg.xml», «фото.jpg.checksums.txt».\nДля случая, когда номера присвоены файлам, "
        "а отдельных папок у предметов нет."),
}
CARRIER_TIP = (
    "Физический носитель, на котором предмет поступил или дополнительно хранится, — если он есть: "
    "диск M-Disc (DVD, BD), внешний жёсткий диск, кассета LTO и т. п. На носитель наносится "
    "учётный номер.\nЕсли предмет хранится только в цифровом репозитории, оставьте поле пустым — "
    "место в репозитории указывается в «Топографии».")
TOPOGRAPHY_TIP = "Где хранится мастер-копия: сервер, раздел и папка цифрового репозитория."
KAMIS_TIP = (
    "Рядом с описанием создаётся «….kamis.txt» — текст для переноса в карточку КАМИС: "
    "формат, размер, дата, контрольные суммы и характеристики файла. Файл вспомогательный, "
    "в единицу хранения не входит.")
OVERWRITE_TIP = (
    "Если описание уже есть, создать его заново. Перед этим программа сверит файлы со старым "
    "описанием и откажется перезаписывать, если какой-то файл изменился.")
CSV_TIP = (
    "Сохранить таблицу (CSV, открывается в Excel) по всем предметам, описанным в этом запуске: "
    "одна строка на файл — учётный номер, формат, размер, дата, контрольные суммы, характеристики "
    "и замечания. Удобно для заполнения КАМИС при описании многих предметов сразу.")


def entry_row(parent, row: int, label: str, var: tk.Variable, width: int = 60, hint: str = "",
              tooltip: str = "") -> ttk.Entry:
    lbl = ttk.Label(parent, text=label)
    lbl.grid(row=row, column=0, sticky="w", padx=PAD, pady=2)
    entry = ttk.Entry(parent, textvariable=var, width=width)
    entry.grid(row=row, column=1, sticky="ew", padx=PAD, pady=2)
    if hint:
        ttk.Label(parent, text=hint, foreground="gray").grid(row=row + 1, column=1, sticky="w", padx=PAD)
    if tooltip:
        tip(lbl, tooltip)
        tip(entry, tooltip)
    return entry


class DescribeTab(ttk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, padding=PAD)
        self.app = app
        s = app.settings
        self.worker = Worker(app)
        self.reports: list[package.Report] = []

        self.source = tk.StringVar(value=s.last_source)
        self.mode = tk.StringVar(value=s.mode)
        self.number = tk.StringVar()
        self.title_var = tk.StringVar()
        self.topography = tk.StringVar(value=s.topography)
        self.carrier = tk.StringVar(value=s.carrier)
        self.normalization = tk.StringVar()
        self.write_kamis = tk.BooleanVar(value=s.write_kamis)
        self.overwrite = tk.BooleanVar(value=False)

        self.columnconfigure(0, weight=1)
        src = ttk.LabelFrame(self, text="Что описать", padding=PAD)
        src.grid(row=0, column=0, sticky="ew")
        src.columnconfigure(1, weight=1)
        ttk.Label(src, text="Файл или папка:").grid(row=0, column=0, sticky="w", padx=PAD)
        ttk.Entry(src, textvariable=self.source).grid(row=0, column=1, sticky="ew", padx=PAD)
        ttk.Button(src, text="Файл…", command=self.choose_file).grid(row=0, column=2)
        ttk.Button(src, text="Папка…", command=self.choose_folder).grid(row=0, column=3, padx=(PAD, 0))
        modes = ttk.Frame(src)
        modes.grid(row=1, column=0, columnspan=4, sticky="w", pady=(PAD, 0))
        self.mode_buttons = []
        for value, label in package.MODE_LABELS.items():
            b = ttk.Radiobutton(modes, text=label, value=value, variable=self.mode, command=self.update_state)
            b.pack(side="left", padx=(0, 12))
            tip(b, MODE_TIPS[value])
            self.mode_buttons.append(b)
        if TkinterDnD is not None:
            ttk.Label(src, text="Файл или папку можно перетащить в окно.", foreground="gray").grid(
                row=2, column=0, columnspan=4, sticky="w", padx=PAD)

        info = ttk.LabelFrame(self, text="Сведения о предмете (пп. 33.13–33.14 Единых правил)", padding=PAD)
        info.grid(row=1, column=0, sticky="ew", pady=PAD)
        info.columnconfigure(1, weight=1)
        self.number_entry = entry_row(info, 0, "Учётный номер (КП):", self.number)
        self.number_hint = ttk.Label(info, foreground="gray")
        self.number_hint.grid(row=1, column=1, sticky="w", padx=PAD)
        self.update_number_hint()
        self.title_entry = entry_row(info, 2, "Наименование:", self.title_var)
        ttk.Label(info, text="Описание:").grid(row=3, column=0, sticky="nw", padx=PAD, pady=2)
        self.description = tk.Text(info, height=3, width=60, wrap="word")
        self.description.grid(row=3, column=1, sticky="ew", padx=PAD, pady=2)
        entry_row(info, 4, "Место хранения (топография):", self.topography, tooltip=TOPOGRAPHY_TIP)
        entry_row(info, 5, "Носитель (если есть):", self.carrier, tooltip=CARRIER_TIP)
        entry_row(info, 6, "Сведения о нормализации:", self.normalization,
                  hint="Исходный формат и программы, которыми файл приведён к формату хранения (п. 33.13 Единых правил).")
        self.batch_hint = ttk.Label(info, foreground="gray", text="")
        self.batch_hint.grid(row=8, column=0, columnspan=2, sticky="w", padx=PAD)

        opts = ttk.Frame(self)
        opts.grid(row=2, column=0, sticky="ew")
        tip(ttk.Checkbutton(opts, text="Создавать памятку для КАМИС", variable=self.write_kamis),
            KAMIS_TIP).pack(side="left")
        tip(ttk.Checkbutton(opts, text="Пересоздавать существующие описания", variable=self.overwrite),
            OVERWRITE_TIP).pack(side="left", padx=12)

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="ew", pady=PAD)
        self.run_button = ttk.Button(buttons, text="Создать описание", command=self.run)
        self.run_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="Отмена", command=self.worker.cancel.set, state="disabled")
        self.cancel_button.pack(side="left", padx=PAD)
        self.csv_button = ttk.Button(buttons, text="Сводная таблица для КАМИС…", command=self.save_csv,
                                     state="disabled")
        self.csv_button.pack(side="right")
        tip(self.csv_button, CSV_TIP)

        self.progress = Progress(self)
        self.progress.frame.grid(row=4, column=0, sticky="ew")

        self.rowconfigure(5, weight=1)
        self.tree = ttk.Treeview(self, columns=("status", "message"), height=8)
        self.tree.heading("#0", text="Предмет")
        self.tree.heading("status", text="Результат")
        self.tree.heading("message", text="Подробности")
        self.tree.column("#0", width=320)
        self.tree.column("status", width=100, stretch=False)
        self.tree.column("message", width=380)
        self.tree.grid(row=5, column=0, sticky="nsew", pady=(PAD, 0))
        self.tree.bind("<Double-1>", self.open_selected)
        self.paths: dict[str, Path] = {}
        self.update_state()

    # --- выбор источника ---

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(title="Файл мастер-копии", initialdir=self._initial_dir())
        if path:
            self.set_source(Path(path))

    def choose_folder(self) -> None:
        path = filedialog.askdirectory(title="Папка предмета или репозитория", initialdir=self._initial_dir())
        if path:
            self.set_source(Path(path))

    def _initial_dir(self) -> str:
        current = Path(self.source.get()) if self.source.get() else None
        if current and current.exists():
            return str(current if current.is_dir() else current.parent)
        return str(Path.home())

    def update_number_hint(self) -> None:
        sep = self.app.settings.number_separator
        example = f"ГМИГ КП ЭФ-55{sep}Петров А.А." if sep else "ГМИГ КП ЭФ-55"
        number = package.split_name(example, sep)[0]
        rule = f"часть имени папки до первого «{sep}»" if sep else "всё имя папки"
        self.number_hint["text"] = f"Если не заполнено — {rule}: «{example}» → «{number}». Разделитель — в настройках."

    def set_source(self, path: Path) -> None:
        self.source.set(str(path))
        self.number.set("")
        self.update_state()

    def update_state(self) -> None:
        path = Path(self.source.get()) if self.source.get() else None
        is_file = bool(path and path.is_file())
        for b in self.mode_buttons:
            b.state(["disabled"] if is_file else ["!disabled"])
        batch = not is_file and self.mode.get() != package.MODE_FOLDER
        state = "disabled" if batch else "normal"
        self.number_entry["state"] = state
        self.title_entry["state"] = state
        self.description["state"] = state
        self.batch_hint["text"] = (
            "В пакетном режиме учётный номер берётся из имени каждой папки (файла); "
            "топография, носитель и сведения о нормализации записываются во все описания."
            if batch else ""
        )

    # --- запуск ---

    def run(self) -> None:
        if self.worker.busy:
            return
        source = Path(self.source.get().strip())
        if not self.source.get().strip() or not source.exists():
            messagebox.showwarning(APP_NAME, "Выберите существующий файл или папку.")
            return
        batch = source.is_dir() and self.mode.get() != package.MODE_FOLDER
        template = ItemInfo(
            accession_number="" if batch else self.number.get().strip(),
            title="" if batch else self.title_var.get().strip(),
            description="" if batch else self.description.get("1.0", "end").strip(),
            topography=self.topography.get().strip(),
            carrier=self.carrier.get().strip(),
            normalization=self.normalization.get().strip(),
            museum=self.app.settings.museum,
        )
        s = self.app.settings
        s.last_source, s.mode, s.write_kamis = str(source), self.mode.get(), self.write_kamis.get()
        s.save()

        self.tree.delete(*self.tree.get_children())
        self.paths.clear()
        self.reports = []
        self.csv_button["state"] = "disabled"
        self.run_button["state"] = "disabled"
        self.cancel_button["state"] = "normal"
        self.progress.reset(0, "Подготовка…")
        describer = package.Describer(
            overwrite=self.overwrite.get(),
            write_kamis=self.write_kamis.get(),
            progress=lambda label, n: self.worker.emit("progress", label, n),
            cancel=self.worker.cancel,
        )
        self.worker.start(self._work, source, self.mode.get(), template, describer,
                          self.app.settings.number_separator)
        self.app.poll(self.worker, self.handle)

    def _work(self, source: Path, mode: str, template: ItemInfo, describer: package.Describer,
              separator: str) -> None:
        plan = package.plan(source, mode, template, separator)
        self.worker.emit("plan", plan, package.total_bytes(plan.items))
        for item in plan.items:
            if self.worker.cancel.is_set():
                break
            self.worker.emit("item", item)
            self.worker.emit("report", describer.describe(item))
        self.worker.emit("done")

    def handle(self, event) -> None:
        kind = event[0]
        if kind == "plan":
            plan, total = event[1], event[2]
            self.progress.reset(total, f"Предметов: {len(plan.items)}")
            for w in plan.warnings:
                self.tree.insert("", "end", text=w, values=("Внимание", ""))
            if not plan.items:
                self.tree.insert("", "end", text="Нечего описывать", values=("", ""))
        elif kind == "item":
            self.progress.label["text"] = f"{event[1].root.name}…"
        elif kind == "progress":
            self.progress.advance(event[1], event[2])
        elif kind == "report":
            report: package.Report = event[1]
            self.reports.append(report)
            item = report.item
            node = self.tree.insert("", "end", text=f"{item.base_name}",
                                    values=(package.STATUS_LABELS[report.status], report.message))
            self.paths[node] = item.root
            for w in report.warnings:
                self.tree.insert(node, "end", text="  предупреждение", values=("", w))
            notes = {n for r in item.files for n in r.probe.notes}
            for n in sorted(notes):
                self.tree.insert(node, "end", text="  замечание", values=("", n))
            if report.status != package.OK or report.warnings:
                self.tree.item(node, open=True)
            self.tree.see(node)
        elif kind in ("done", "cancelled", "fatal"):
            self.run_button["state"] = "normal"
            self.cancel_button["state"] = "disabled"
            counts = {s: sum(1 for r in self.reports if r.status == s) for s in package.STATUS_LABELS}
            summary = ", ".join(f"{package.STATUS_LABELS[s].lower()}: {n}" for s, n in counts.items() if n)
            if kind == "fatal":
                self.progress.finish("Ошибка")
                messagebox.showerror(APP_NAME, event[1])
            elif kind == "cancelled" or self.worker.cancel.is_set():
                self.progress.finish(f"Отменено. {summary}")
            else:
                self.progress.finish(f"Завершено. {summary or 'нет предметов'}")
            if counts[package.OK]:
                self.csv_button["state"] = "normal"
            if counts[package.ERROR]:
                messagebox.showwarning(APP_NAME, f"Не удалось описать предметов: {counts[package.ERROR]}. "
                                                 "Подробности — в таблице.")

    def open_selected(self, _event=None) -> None:
        node = self.tree.focus()
        while node and node not in self.paths:
            node = self.tree.parent(node)
        if node:
            open_in_file_manager(self.paths[node])

    def save_csv(self) -> None:
        items = [r.item for r in self.reports if r.status == package.OK]
        if not items:
            return
        stamp = datetime.now().strftime("%Y-%m-%d")
        path = filedialog.asksaveasfilename(
            title="Сводная таблица для КАМИС", defaultextension=".csv",
            initialfile=f"КАМИС_{stamp}.csv", filetypes=[("Таблица CSV", "*.csv")])
        if path:
            kamis.write_csv(items, Path(path))
            messagebox.showinfo(APP_NAME, f"Таблица сохранена:\n{path}")


class VerifyTab(ttk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, padding=PAD)
        self.app = app
        self.worker = Worker(app)
        self.results: list[verify.ItemCheck] = []
        self.started: datetime | None = None
        self.master_path = tk.StringVar(value=app.settings.last_verify)
        self.backup = tk.StringVar()
        self.open_files = tk.BooleanVar(value=app.settings.verify_open_files)

        self.columnconfigure(0, weight=1)
        box = ttk.LabelFrame(self, text="Что проверить (пп. 33.5–33.8 Единых правил)", padding=PAD)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Папка предмета или репозитория:").grid(row=0, column=0, sticky="w", padx=PAD)
        ttk.Entry(box, textvariable=self.master_path).grid(row=0, column=1, sticky="ew", padx=PAD)
        ttk.Button(box, text="Обзор…", command=lambda: self.choose(self.master_path)).grid(row=0, column=2)
        ttk.Label(box, text="Резервная копия (необязательно):").grid(row=1, column=0, sticky="w", padx=PAD, pady=(PAD, 0))
        ttk.Entry(box, textvariable=self.backup).grid(row=1, column=1, sticky="ew", padx=PAD, pady=(PAD, 0))
        ttk.Button(box, text="Обзор…", command=lambda: self.choose(self.backup)).grid(row=1, column=2, pady=(PAD, 0))
        ttk.Label(box, foreground="gray", text=(
            "Если указана резервная копия, проверяются файлы копии по контрольным суммам мастер-копии. "
            "Структура папок копии должна совпадать."), wraplength=640).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=PAD)
        tip(ttk.Checkbutton(box, text="Проверять, что файлы открываются (изображения, PDF, документы, контейнеры видео)",
                            variable=self.open_files),
            "Кроме контрольных сумм программа пробует открыть каждый файл: изображения декодируются, "
            "у PDF читаются все страницы, у DOCX/ODT проверяется архив, у видео и аудио — структура "
            "контейнера. Воспроизведение видео и звука нужно проверять плеером (п. 33.8)."
            ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(PAD, 0))

        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, sticky="ew", pady=PAD)
        self.run_button = ttk.Button(buttons, text="Начать сверку", command=self.run)
        self.run_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="Отмена", command=self.worker.cancel.set, state="disabled")
        self.cancel_button.pack(side="left", padx=PAD)
        self.report_button = ttk.Button(buttons, text="Сохранить отчёт…", command=self.save_report,
                                        state="disabled")
        self.report_button.pack(side="right")

        self.progress = Progress(self)
        self.progress.frame.grid(row=2, column=0, sticky="ew")
        self.date_label = ttk.Label(self, text="", font=("TkDefaultFont", 11, "bold"))
        self.date_label.grid(row=3, column=0, sticky="w", pady=(PAD, 0))

        self.rowconfigure(4, weight=1)
        self.tree = ttk.Treeview(self, columns=("status",), height=10)
        self.tree.heading("#0", text="Предмет / файл")
        self.tree.heading("status", text="Результат")
        self.tree.column("#0", width=420)
        self.tree.column("status", width=380)
        self.tree.tag_configure("bad", foreground="#b00020")
        self.tree.grid(row=4, column=0, sticky="nsew", pady=(PAD, 0))

    def choose(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if path:
            var.set(path)

    def run(self) -> None:
        if self.worker.busy:
            return
        master = Path(self.master_path.get().strip())
        backup = Path(self.backup.get().strip()) if self.backup.get().strip() else None
        if not self.master_path.get().strip() or not master.exists():
            messagebox.showwarning(APP_NAME, "Выберите папку для сверки.")
            return
        if backup is not None and not backup.is_dir():
            messagebox.showwarning(APP_NAME, "Папка резервной копии не найдена.")
            return
        s = self.app.settings
        s.last_verify, s.verify_open_files = str(master), self.open_files.get()
        s.save()
        self.tree.delete(*self.tree.get_children())
        self.results = []
        self.started = textfmt.local_datetime(datetime.now().timestamp())
        self.date_label["text"] = ""
        self.report_button["state"] = "disabled"
        self.run_button["state"] = "disabled"
        self.cancel_button["state"] = "normal"
        self.progress.reset(0, "Поиск файлов контрольных сумм…")
        self.worker.start(self._work, master, backup, self.open_files.get())
        self.app.poll(self.worker, self.handle)

    def _work(self, master: Path, backup: Path | None, open_files: bool) -> None:
        self.worker.emit("total", verify.planned_bytes(master, backup))
        verify.verify_tree(
            master, backup, open_files,
            progress=lambda label, n: self.worker.emit("progress", label, n),
            cancel=self.worker.cancel,
            on_item=lambda check: self.worker.emit("item", check),
        )
        self.worker.emit("done")

    def handle(self, event) -> None:
        kind = event[0]
        if kind == "total":
            self.progress.reset(event[1], "Сверка…")
        elif kind == "progress":
            self.progress.advance(event[1], event[2])
        elif kind == "item":
            check: verify.ItemCheck = event[1]
            self.results.append(check)
            tags = () if check.ok else ("bad",)
            node = self.tree.insert("", "end", text=str(check.target_root), values=(check.status_text,), tags=tags)
            for fc in check.files:
                if fc.status != verify.OK:
                    detail = f" — {fc.details}" if fc.details else ""
                    self.tree.insert(node, "end", text=f"  {fc.relpath}",
                                     values=(verify.LABELS[fc.status] + detail,),
                                     tags=("bad",) if fc.status in verify.PROBLEMS else ())
            if not check.ok:
                self.tree.item(node, open=True)
            self.tree.see(node)
        elif kind in ("done", "cancelled", "fatal"):
            self.run_button["state"] = "normal"
            self.cancel_button["state"] = "disabled"
            bad = sum(1 for r in self.results if not r.ok)
            if kind == "fatal":
                self.progress.finish("Ошибка")
                messagebox.showerror(APP_NAME, event[1])
                return
            if kind == "cancelled":
                self.progress.finish("Сверка отменена — результаты неполные.")
            elif not self.results:
                self.progress.finish("Файлы контрольных сумм не найдены.")
            else:
                self.progress.finish(f"Проверено предметов: {len(self.results)}, с проблемами: {bad}.")
            if self.results:
                self.report_button["state"] = "normal"
            if kind == "done" and self.results:
                verdict = "без замечаний" if bad == 0 else f"есть проблемы ({bad})"
                self.date_label["text"] = (f"Дата для поля «Сверка» в КАМИС: {textfmt.date_only(self.started)} — "
                                           f"{verdict}")

    def save_report(self) -> None:
        if not self.results or self.started is None:
            return
        name = f"Сверка_{self.started.strftime('%Y-%m-%d')}"
        path = filedialog.asksaveasfilename(
            title="Отчёт о сверке", defaultextension=".txt", initialfile=f"{name}.txt",
            filetypes=[("Текстовый отчёт", "*.txt"), ("Таблица CSV", "*.csv")])
        if path:
            backup = Path(self.backup.get()) if self.backup.get().strip() else None
            verify.write_report(self.results, Path(path), Path(self.master_path.get()), backup, self.started)
            messagebox.showinfo(APP_NAME, f"Отчёт сохранён:\n{path}")


class SettingsTab(ttk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, padding=PAD)
        self.app = app
        s = app.settings
        self.museum = tk.StringVar(value=s.museum)
        self.topography = tk.StringVar(value=s.topography)
        self.carrier = tk.StringVar(value=s.carrier)
        self.separator = tk.StringVar(value=self._separator_label(s.number_separator))
        self.columnconfigure(1, weight=1)
        entry_row(self, 0, "Название музея:", self.museum, hint="Записывается в каждое описание.")
        entry_row(self, 2, "Топография по умолчанию:", self.topography, tooltip=TOPOGRAPHY_TIP)
        entry_row(self, 3, "Носитель по умолчанию:", self.carrier, tooltip=CARRIER_TIP)

        sep_label = ttk.Label(self, text="Разделитель учётного номера:")
        sep_label.grid(row=4, column=0, sticky="w", padx=PAD, pady=(PAD, 2))
        combo = ttk.Combobox(self, textvariable=self.separator, width=24, values=list(self.SEPARATORS))
        combo.grid(row=4, column=1, sticky="w", padx=PAD, pady=(PAD, 2))
        sep_tip = ("Учётный номер берётся из имени папки (или файла) — часть до первого разделителя. "
                   "Остальное записывается как классификатор (ФИО, место и т. п.).\n"
                   "Можно выбрать из списка или ввести свой разделитель. Не выбирайте символ, который "
                   "встречается в самом номере, — пробел или дефис: в «ГМИГ КП ЭФ-55» есть оба. "
                   "Проверьте результат по примеру под полем.")
        tip(sep_label, sep_tip)
        tip(combo, sep_tip)
        self.preview = ttk.Label(self, foreground="gray")
        self.preview.grid(row=5, column=1, sticky="w", padx=PAD)
        self.separator.trace_add("write", lambda *_: self.update_preview())
        self.update_preview()

        ttk.Button(self, text="Сохранить", command=self.save).grid(row=6, column=1, sticky="w", padx=PAD, pady=PAD)
        ttk.Label(self, text=f"Настройки и журнал: {config_dir()}", foreground="gray").grid(
            row=7, column=0, columnspan=2, sticky="w", padx=PAD, pady=(PAD * 2, 0))
        ttk.Button(self, text="Открыть папку настроек",
                   command=lambda: (config_dir().mkdir(parents=True, exist_ok=True),
                                    open_in_file_manager(config_dir()))).grid(
            row=8, column=0, sticky="w", padx=PAD)

    # Подписи в списке -> сам разделитель
    SEPARATORS = {
        "_ (подчёркивание)": "_",
        "__ (два подчёркивания)": "__",
        ", (запятая)": ",",
        "нет — номер = всё имя": "",
    }

    @classmethod
    def _separator_label(cls, value: str) -> str:
        return next((label for label, sep in cls.SEPARATORS.items() if sep == value), value)

    def separator_value(self) -> str:
        text = self.separator.get()
        return self.SEPARATORS.get(text, text)

    def update_preview(self) -> None:
        sep = self.separator_value()
        example = f"ГМИГ КП ЭФ-55{sep}Петров А.А.{sep}Соловки" if sep else "ГМИГ КП ЭФ-55"
        number, classifier = package.split_name(example, sep)
        text = f"Пример: «{example}» → номер «{number}»"
        if classifier:
            text += f", классификатор «{classifier}»"
        self.preview["text"] = text

    def save(self) -> None:
        s = self.app.settings
        s.museum, s.topography, s.carrier = self.museum.get().strip(), self.topography.get().strip(), self.carrier.get().strip()
        s.number_separator = self.separator_value()
        s.save()
        describe = self.app.describe_tab
        describe.update_number_hint()
        if not describe.topography.get():
            describe.topography.set(s.topography)
        if not describe.carrier.get():
            describe.carrier.set(s.carrier)
        messagebox.showinfo(APP_NAME, "Настройки сохранены.")


class AboutTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=PAD * 2)
        from .probes import image, media
        lines = [
            (f"{APP_NAME} {__version__}", ("TkDefaultFont", 13, "bold")),
            ("Описания цифровых музейных предметов по разделу XXXIII Единых правил (приказ Минкультуры № 827):", None),
            ("файл метаданных (XML, UTF-8), файл контрольных сумм (SHA-1 и ГОСТ 34.11-2018), сверка.", None),
            ("", None),
            (f"Формат описания: {FORMAT_VERSION}", None),
            (f"Хеш ГОСТ 34.11-2018: реализация на {hashing.BACKEND}"
             + ("" if hashing.BACKEND == "C" else " — медленно, модуль на C не собран"), None),
            ("MediaInfo (видео, аудио): " + ("доступен" if media.available() else "НЕ ДОСТУПЕН"), None),
            ("Pillow (изображения): " + ("доступен" if image.Image is not None else "НЕ ДОСТУПЕН"), None),
            ("rawpy (RAW-файлы камер): " + ("доступен" if image.rawpy is not None else "не установлен"), None),
            ("Перетаскивание файлов: " + ("доступно" if TkinterDnD is not None else "не установлено (tkinterdnd2)"), None),
            ("", None),
            ("https://github.com/faralex-dev/Museum-Digital-File-Descriptor", None),
        ]
        for text, font in lines:
            label = ttk.Label(self, text=text)
            if font:
                label.configure(font=font)
            label.pack(anchor="w")


class App:
    def __init__(self):
        self.settings = Settings.load()
        self.root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.minsize(760, 600)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.describe_tab = DescribeTab(notebook, self)
        self.verify_tab = VerifyTab(notebook, self)
        notebook.add(self.describe_tab, text="Описание")
        notebook.add(self.verify_tab, text="Сверка")
        notebook.add(SettingsTab(notebook, self), text="Настройки")
        notebook.add(AboutTab(notebook), text="О программе")
        self.notebook = notebook
        if TkinterDnD is not None:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self.on_drop)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def poll(self, worker: Worker, handler) -> None:
        try:
            for _ in range(500):
                event = worker.events.get_nowait()
                handler(event)
                if event[0] in ("done", "cancelled", "fatal"):
                    return
        except queue.Empty:
            pass
        self.root.after(80, self.poll, worker, handler)

    def on_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        path = Path(paths[0])
        if self.notebook.select() == str(self.verify_tab):
            self.verify_tab.master_path.set(str(path if path.is_dir() else path.parent))
        else:
            self.notebook.select(self.describe_tab)
            self.describe_tab.set_source(path)

    def on_close(self) -> None:
        busy = self.describe_tab.worker.busy or self.verify_tab.worker.busy
        if busy and not messagebox.askyesno(APP_NAME, "Работа ещё не закончена. Прервать и выйти?"):
            return
        self.describe_tab.worker.cancel.set()
        self.verify_tab.worker.cancel.set()
        self.root.destroy()

    def bring_to_front(self) -> None:
        """На macOS окно, запущенное из терминала, открывается позади других окон."""
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def run(self) -> None:
        self.root.after(100, self.bring_to_front)
        self.root.mainloop()


def _windows_dpi_awareness() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main() -> int:
    setup_logging()
    _windows_dpi_awareness()
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
