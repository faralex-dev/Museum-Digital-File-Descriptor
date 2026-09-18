"""Генерирует таблицы алгоритма «Стрибог» (ГОСТ 34.11-2018 / ГОСТ Р 34.11-2012).

Источник констант — пакет gostcrypto (MIT), где они уже сведены в таблицы
LPS-преобразования. Скрипт нужен только разработчику: результат
(`mdfd/hashing/_streebog_tables.h` и `_streebog_tables.py`) лежит в репозитории.

    pip install gostcrypto
    python tools/gen_streebog_tables.py

Правильность таблиц проверяется тестами tests/test_streebog.py
(контрольные примеры из стандарта).
"""
from pathlib import Path

from gostcrypto.gosthash import gost_34_11_2012 as ref

ROOT = Path(__file__).resolve().parent.parent / "mdfd" / "hashing"
HEADER = "Сгенерировано tools/gen_streebog_tables.py — не редактировать вручную."


def c_words(block) -> list[int]:
    """Константа C_i: 64 байта -> 8 слов uint64 (little-endian)."""
    data = bytes(block)
    return [int.from_bytes(data[i:i + 8], "little") for i in range(0, 64, 8)]


def main() -> None:
    tables = [list(t) for t in ref._T]
    consts = [c_words(c) for c in ref._C]
    assert len(tables) == 8 and all(len(t) == 256 for t in tables)
    assert len(consts) == 12

    lines = [f"/* {HEADER} */", "#include <stdint.h>", "",
             "static const uint64_t STREEBOG_T[8][256] = {"]
    for t in tables:
        lines.append("  {")
        for i in range(0, 256, 4):
            lines.append("    " + " ".join(f"0x{v:016x}ULL," for v in t[i:i + 4]))
        lines.append("  },")
    lines += ["};", "", "static const uint64_t STREEBOG_C[12][8] = {"]
    for c in consts:
        lines.append("  {" + " ".join(f"0x{v:016x}ULL," for v in c) + "},")
    lines += ["};", ""]
    (ROOT / "_streebog_tables.h").write_text("\n".join(lines), encoding="utf-8")

    py = [f"# {HEADER}", "", "T = ("]
    for t in tables:
        py.append("    (")
        for i in range(0, 256, 4):
            py.append("        " + " ".join(f"0x{v:016x}," for v in t[i:i + 4]))
        py.append("    ),")
    py += [")", "", "C = ("]
    for c in consts:
        py.append("    (" + " ".join(f"0x{v:016x}," for v in c) + "),")
    py += [")", ""]
    (ROOT / "_streebog_tables.py").write_text("\n".join(py), encoding="utf-8")


if __name__ == "__main__":
    main()
