"""Командная строка.

    mdfd describe ПУТЬ [--mode folder|subfolders|files] [--number ...] [--topography ...]
    mdfd verify ПУТЬ [--backup ПАПКА] [--report отчёт.txt|.csv]
    mdfd info ФАЙЛ
    mdfd gui

Без аргументов запускается графический интерфейс.
"""
from __future__ import annotations

import argparse
import sys
import threading
from datetime import datetime
from pathlib import Path

from . import APP_NAME, __version__, hashing, kamis, package, textfmt, verify
from .model import ItemInfo


def _stdout_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def cmd_describe(args) -> int:
    template = ItemInfo(
        accession_number=args.number or "",
        title=args.title or "",
        description=args.description or "",
        topography=args.topography or "",
        carrier=args.carrier or "",
        normalization=args.normalization or "",
        museum=args.museum or "",
    )
    plan = package.plan(Path(args.path), args.mode, template)
    for w in plan.warnings:
        print(f"! {w}")
    if not plan.items:
        print("Нечего описывать.")
        return 1
    if args.number and len(plan.items) > 1:
        print("! Учётный номер из --number применяется только к одному предмету; "
              "для остальных он берётся из имени папки/файла.")

    describer = package.Describer(overwrite=args.overwrite, write_kamis=not args.no_kamis)
    reports = []
    exit_code = 0
    for item in plan.items:
        report = describer.describe(item)
        reports.append(report)
        label = package.STATUS_LABELS[report.status]
        print(f"[{label}] {item.root / item.base_name}: {report.message}")
        for w in report.warnings:
            print(f"    ! {w}")
        if report.status == package.ERROR:
            exit_code = 2
    if args.csv:
        done = [r.item for r in reports if r.status == package.OK]
        kamis.write_csv(done, Path(args.csv))
        print(f"Сводная таблица: {args.csv}")
    return exit_code


def cmd_verify(args) -> int:
    started = textfmt.local_datetime(datetime.now().timestamp())
    master = Path(args.path)
    backup = Path(args.backup) if args.backup else None

    def on_item(check: verify.ItemCheck) -> None:
        print(f"[{check.status_text}] {check.target_root} ({check.checksum_file.name})")
        for fc in check.files:
            if fc.status != verify.OK:
                detail = f" — {fc.details}" if fc.details else ""
                print(f"    {verify.LABELS[fc.status]}: {fc.relpath}{detail}")

    results = verify.verify_tree(master, backup, open_files=not args.no_open, on_item=on_item)
    if not results:
        print("Файлы контрольных сумм не найдены.")
        return 1
    bad = sum(1 for r in results if not r.ok)
    print(f"\nДата сверки для КАМИС: {textfmt.date_only(started)}. Предметов: {len(results)}, с проблемами: {bad}.")
    if args.report:
        verify.write_report(results, Path(args.report), master, backup, started)
        print(f"Отчёт: {args.report}")
    return 0 if bad == 0 else 3


def cmd_info(args) -> int:
    from .probes import probe_file
    path = Path(args.path)
    result = probe_file(path)
    print(f"{path.name}: {result.format_name} ({result.category})")
    if result.puid:
        print(f"  PRONOM: {result.puid} {result.pronom_name}")
    for p in result.props:
        print(f"  {p.label}: {p.text}")
    for t in result.tracks:
        print(f"  {t.label}:")
        for p in t.props:
            print(f"    {p.label}: {p.text}")
    for n in result.notes:
        print(f"  Замечание: {n}")
    for w in result.warnings:
        print(f"  Предупреждение: {w}")
    if args.hash:
        sums = hashing.hash_file(path)
        for key, value in sums.items():
            print(f"  {hashing.ALGORITHMS[key].label}: {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdfd", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__} "
                        f"(хеш ГОСТ: реализация на {hashing.BACKEND})")
    sub = parser.add_subparsers(dest="command")

    d = sub.add_parser("describe", help="создать описание предмета")
    d.add_argument("path", help="файл или папка")
    d.add_argument("--mode", choices=list(package.MODE_LABELS), default=package.MODE_FOLDER,
                   help="folder — папка это один предмет; subfolders — каждая подпапка отдельный предмет; "
                        "files — каждый файл отдельный предмет")
    d.add_argument("--number", help="учётный номер (по умолчанию — часть имени папки до «_»)")
    d.add_argument("--title", help="наименование")
    d.add_argument("--description", help="описание")
    d.add_argument("--topography", help="место хранения (топография)")
    d.add_argument("--carrier", help="носитель")
    d.add_argument("--normalization", help="сведения о нормализации")
    d.add_argument("--museum", help="название музея")
    d.add_argument("--overwrite", action="store_true", help="пересоздать существующие описания")
    d.add_argument("--no-kamis", action="store_true", help="не создавать памятку для КАМИС")
    d.add_argument("--csv", help="сохранить сводную таблицу для КАМИС")
    d.set_defaults(func=cmd_describe)

    v = sub.add_parser("verify", help="сверка (проверка контрольных сумм)")
    v.add_argument("path", help="папка предмета, папка репозитория или файл контрольных сумм")
    v.add_argument("--backup", help="папка резервной копии с той же структурой")
    v.add_argument("--no-open", action="store_true", help="не пробовать открывать файлы")
    v.add_argument("--report", help="сохранить отчёт (.txt или .csv)")
    v.set_defaults(func=cmd_verify)

    i = sub.add_parser("info", help="показать сведения о файле")
    i.add_argument("path")
    i.add_argument("--hash", action="store_true", help="посчитать контрольные суммы")
    i.set_defaults(func=cmd_info)

    g = sub.add_parser("gui", help="графический интерфейс")
    g.set_defaults(func=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    _stdout_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "gui"):
        from .gui import main as gui_main
        return gui_main()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Прервано.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
