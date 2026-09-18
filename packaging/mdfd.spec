# Сборка программы: pyinstaller packaging/mdfd.spec
# Результат — одна папка dist/MuseumDigitalFileDescriptor со всем необходимым
# (MediaInfo, модуль ГОСТ на C, Tcl/Tk). Устанавливать Python не нужно.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
NAME = "MuseumDigitalFileDescriptor"

binaries = collect_dynamic_libs("pymediainfo")
datas = []
hiddenimports = ["mdfd.hashing._streebog", "PIL.ImageCms"]
try:
    import tkinterdnd2  # noqa: F401
    datas += collect_data_files("tkinterdnd2")
    hiddenimports.append("tkinterdnd2")
except ImportError:
    pass
try:
    import rawpy  # noqa: F401
    binaries += collect_dynamic_libs("rawpy")
    hiddenimports.append("rawpy")
except ImportError:
    pass

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["gostcrypto", "pytest", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        bundle_identifier="io.github.faralex-dev.mdfd",
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "2.0.0"},
    )

# Консольная версия (для пакетной обработки и планировщика заданий)
cli_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mdfd",
    console=True,
)
cli_coll = COLLECT(cli_exe, a.binaries, a.datas, name=f"{NAME}-cli")
