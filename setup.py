"""Сборка модуля «Стрибог» на C.

Метаданные пакета — в pyproject.toml. Если компилятора нет, установка
не прерывается: программа будет использовать реализацию на Python.
"""
import sys

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class OptionalBuildExt(build_ext):
    def run(self):
        try:
            super().run()
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)

    def build_extension(self, ext):
        try:
            super().build_extension(ext)
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)

    @staticmethod
    def _warn(exc):
        print(
            "ВНИМАНИЕ: модуль _streebog на C не собран "
            f"({exc}). Хеш ГОСТ будет считаться медленной реализацией на Python.",
            file=sys.stderr,
        )


setup(
    ext_modules=[
        Extension(
            "mdfd.hashing._streebog",
            sources=["mdfd/hashing/_streebog.c"],
            depends=["mdfd/hashing/_streebog_tables.h"],
            extra_compile_args=["/O2"] if sys.platform == "win32" else ["-O3"],
        )
    ],
    cmdclass={"build_ext": OptionalBuildExt},
)
