"""Запуск программы из исходников: python main.py (графический интерфейс)
или python main.py describe|verify|info ... (командная строка)."""
import sys

from mdfd.cli import main

if __name__ == "__main__":
    sys.exit(main())
