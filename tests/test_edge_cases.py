"""Сложные случаи: странные имена, права доступа, повреждённые файлы и т. п."""
import os
import shutil
import sys
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from mdfd import checksums, package, verify, xmlio
from mdfd.model import ItemInfo

DATA = Path(__file__).parent / "data"
POSIX = sys.platform != "win32"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def describe(folder, info=None, mode=package.MODE_FOLDER, **kw):
    plan = package.plan(folder, mode, info or ItemInfo())
    return [package.Describer(**kw).describe(i) for i in plan.items], plan


def statuses(folder, **kw):
    return {f.relpath: f.status for c in verify.verify_tree(folder, **kw) for f in c.files}


def item(tmp_path, name="Предмет", files=("image.png",)):
    folder = tmp_path / name
    folder.mkdir()
    for f in files:
        shutil.copy(DATA / f, folder / f)
    return folder


def test_control_characters_do_not_break_xml(tmp_path):
    folder = item(tmp_path)
    info = ItemInfo(title="Заголовок\x0bиз\x00Word & <тег> \"кавычки\"", description="строка1\x1fстрока2")
    reports, _ = describe(folder, info)
    assert reports[0].status == package.OK
    root = ET.parse(folder / "Предмет.xml").getroot()
    assert root.findtext("Item/Title") == "Заголовок�из�Word & <тег> \"кавычки\""
    assert verify.verify_tree(folder)[0].ok


def test_unusual_file_names(tmp_path):
    folder = item(tmp_path, files=())
    for name in ("a) = b.png", "#решётка.png", " пробелы .png", "a:b.png" if POSIX else "a;b.png",
                 # около 200 байт: ближе к пределу Linux (255 байт на имя), но не за ним
                 "очень " + "длинное " * 11 + "имя.png"):
        shutil.copy(DATA / "image.png", folder / name)
    reports, _ = describe(folder)
    assert reports[0].status == package.OK, reports[0].message
    result = statuses(folder)
    assert set(result.values()) == {verify.OK}, result
    assert len(result) == 6


@pytest.mark.skipif(not POSIX, reason="Windows не допускает перевод строки в имени")
def test_newline_in_file_name_is_refused(tmp_path):
    folder = item(tmp_path)
    shutil.copy(DATA / "image.png", folder / "две\nстроки.png")
    reports, _ = describe(folder)
    assert reports[0].status == package.ERROR
    assert "перевод строки" in reports[0].message
    assert not (folder / "Предмет.xml").exists()


def test_nfd_names_are_written_as_nfc_and_found(tmp_path):
    folder = item(tmp_path, files=())
    nfd = unicodedata.normalize("NFD", "йод.png")
    shutil.copy(DATA / "image.png", folder / nfd)
    describe(folder)
    text = (folder / "Предмет.checksums.txt").read_text(encoding="utf-8")
    assert unicodedata.is_normalized("NFC", text)
    assert "йод.png" in text
    assert set(statuses(folder).values()) == {verify.OK}

    # Копия, где файл назван в NFC (так бывает после копирования с macOS на Windows/Linux)
    copy = tmp_path / "копия"
    shutil.copytree(folder, copy)
    for p in list(copy.iterdir()):
        if p.name != unicodedata.normalize("NFC", p.name):
            p.rename(copy / unicodedata.normalize("NFC", p.name))
    assert set(statuses(copy).values()) == {verify.OK}


@pytest.mark.skipif(not POSIX or IS_ROOT, reason="права доступа POSIX")
def test_unreadable_file(tmp_path):
    folder = item(tmp_path, files=("image.png", "photo_jfif.jpg"))
    locked = folder / "photo_jfif.jpg"
    locked.chmod(0)
    try:
        reports, _ = describe(folder)
        assert reports[0].status == package.ERROR
        assert reports[0].message == "Нет доступа к файлу «photo_jfif.jpg» (недостаточно прав)."
        assert not (folder / "Предмет.xml").exists()

        locked.chmod(0o644)
        describe(folder)
        locked.chmod(0)
        check = {f.relpath: f for c in verify.verify_tree(folder) for f in c.files}
        assert check["photo_jfif.jpg"].status == verify.UNREADABLE
        assert "нет доступа" in check["photo_jfif.jpg"].details
    finally:
        locked.chmod(0o644)


@pytest.mark.skipif(not POSIX or IS_ROOT, reason="права доступа POSIX")
def test_read_only_folder_leaves_no_partial_files(tmp_path):
    folder = item(tmp_path)
    folder.chmod(0o555)
    try:
        reports, _ = describe(folder)
        assert reports[0].status == package.ERROR
        assert reports[0].message == "Нет прав на запись в папку «Предмет»."
        assert sorted(p.name for p in folder.iterdir()) == ["image.png"]
    finally:
        folder.chmod(0o755)


def test_failed_write_keeps_previous_description(tmp_path, monkeypatch):
    folder = item(tmp_path)
    describe(folder)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    real_replace = os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    reports, _ = describe(folder, overwrite=True)
    monkeypatch.undo()
    assert reports[0].status == package.ERROR
    # временных файлов не осталось
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]
    # файл контрольных сумм не заменён, значит описание по-прежнему сходится с ним
    assert (folder / "Предмет.checksums.txt").read_bytes() == before["Предмет.checksums.txt"]


def test_file_changing_while_hashing(tmp_path, monkeypatch):
    folder = item(tmp_path)
    from mdfd import hashing
    real = hashing.hash_file

    def growing(path, *a, **kw):
        result = real(path, *a, **kw)
        with open(path, "ab") as f:
            f.write(b"more")
        return result

    monkeypatch.setattr(hashing, "hash_file", growing)
    reports, _ = describe(folder)
    assert reports[0].status == package.ERROR
    assert "изменялся во время чтения" in reports[0].message


def test_bad_file_dates(tmp_path):
    folder = item(tmp_path, files=("image.png", "photo_jfif.jpg"))
    try:
        os.utime(folder / "image.png", (-100_000_000, -100_000_000))
    except OSError:
        pytest.skip("файловая система не допускает дат до 1970 года")
    reports, _ = describe(folder)
    assert reports[0].status == package.OK


def test_damaged_and_unusual_content(tmp_path):
    folder = item(tmp_path, files=())
    (folder / "empty.pdf").write_bytes(b"")
    (folder / "cut.mp4").write_bytes((DATA / "video_h264_aac.mp4").read_bytes()[:3000])
    (folder / "trunc.pdf").write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\n")
    shutil.copy(DATA / "photo_jfif.jpg", folder / "UPPER.JPG")
    shutil.copy(DATA / "audio.mp3", folder / "без_расширения")
    reports, _ = describe(folder)
    assert reports[0].status == package.OK
    files = {f.relpath: f for f in reports[0].item.files}
    assert files["UPPER.JPG"].probe.category == "image"
    assert files["без_расширения"].probe.category == "audio"
    assert any("пустой" in w for w in reports[0].warnings)
    ET.parse(folder / "Предмет.xml")


def test_nested_item_is_not_swallowed(tmp_path):
    parent = item(tmp_path, "Родитель")
    child = parent / "Вложенный"
    child.mkdir()
    shutil.copy(DATA / "photo_jfif.jpg", child / "c.jpg")
    describe(child)
    reports, plan = describe(parent)
    assert any("Вложенный" in w for w in plan.warnings)
    listed = checksums.parse(parent / "Родитель.checksums.txt").by_file()
    assert "Вложенный/c.jpg" not in listed
    results = verify.verify_tree(parent)
    assert len(results) == 2 and all(r.ok for r in results)
    assert not any(f.status == verify.EXTRA for r in results for f in r.files)


@pytest.mark.skipif(not POSIX, reason="символические ссылки на Windows требуют прав")
def test_symlinks_are_skipped(tmp_path):
    folder = item(tmp_path)
    shutil.copy(DATA / "photo_jfif.jpg", tmp_path / "outside.jpg")
    (folder / "link.jpg").symlink_to(tmp_path / "outside.jpg")
    reports, plan = describe(folder)
    assert [f.relpath for f in reports[0].item.files] == ["image.png"]
    assert any("ссылка" in w for w in plan.warnings)


def test_path_escaping_the_item_folder_is_rejected(tmp_path):
    folder = item(tmp_path, files=())
    (tmp_path / "secret.txt").write_bytes(b"")
    (folder / "x.checksums.txt").write_text(
        "# Контрольные суммы цифрового музейного предмета\n"
        "SHA1 (../secret.txt) = DA39A3EE5E6B4B0D3255BFEF95601890AFD80709\n"
        "SHA1 (/etc/hosts) = DA39A3EE5E6B4B0D3255BFEF95601890AFD80709\n", encoding="utf-8")
    result = statuses(folder)
    assert result["../secret.txt"] == verify.INVALID
    assert result["/etc/hosts"] == verify.INVALID


def test_checksum_file_resaved_in_notepad(tmp_path):
    """Файл контрольных сумм открыли в Блокноте и сохранили в «ANSI» с CRLF."""
    folder = item(tmp_path, files=())
    shutil.copy(DATA / "image.png", folder / "картинка.png")
    describe(folder)
    cf = folder / "Предмет.checksums.txt"
    cf.write_bytes(cf.read_text(encoding="utf-8").replace("\n", "\r\n").encode("cp1251"))
    [check] = verify.verify_tree(folder)
    assert not check.error
    assert {f.relpath: f.status for f in check.files}["картинка.png"] == verify.OK


def test_checksum_file_with_bom(tmp_path):
    folder = item(tmp_path)
    describe(folder)
    cf = folder / "Предмет.checksums.txt"
    cf.write_bytes(b"\xef\xbb\xbf" + cf.read_bytes())
    assert verify.verify_tree(folder)[0].ok


def test_long_path(tmp_path):
    """Длинные пути (на Windows больше 260 знаков)."""
    deep = tmp_path
    for i in range(6):
        deep = deep / ("вложенная_папка_с_длинным_названием_" + str(i))
    try:
        deep.mkdir(parents=True)
        shutil.copy(DATA / "image.png", deep / "файл.png")
    except OSError:
        pytest.skip("система не поддерживает такие длинные пути")
    reports, _ = describe(deep)
    assert reports[0].status == package.OK, reports[0].message
    assert verify.verify_tree(deep)[0].ok


def test_xml_clean_text_keeps_normal_text():
    assert xmlio.clean_text("Обычный текст\tс табуляцией\nи строками") == "Обычный текст\tс табуляцией\nи строками"
    assert xmlio.clean_text("a\x00b\udcc3c") == "a�b�c"
