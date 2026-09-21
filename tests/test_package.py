import hashlib
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from mdfd import checksums, cli, hashing, kamis, package, verify, xmlio
from mdfd.hashing import streebog
from mdfd.model import ItemInfo

DATA = Path(__file__).parent / "data"
ITEM = "ГМИГ КП ЭФ-55_Петров А.А._Соловки"


def make_item(root: Path, name: str = ITEM, files=("video_h264_aac.mp4", "photo_exif.jpg")) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    for f in files:
        shutil.copy(DATA / f, folder / f)
    return folder


def describe(source, mode=package.MODE_FOLDER, info=None, **kw):
    plan = package.plan(source, mode, info or ItemInfo(topography="Сервер 1"))
    d = package.Describer(**kw)
    return [d.describe(item) for item in plan.items], plan


def test_folder_item(tmp_path):
    folder = make_item(tmp_path)
    (folder / "sub").mkdir()
    shutil.copy(DATA / "letter_cp1251.txt", folder / "sub" / "письмо.txt")
    (folder / ".DS_Store").write_bytes(b"x")
    (reports, _) = describe(folder)
    assert [r.status for r in reports] == [package.OK]
    item = reports[0].item
    assert item.info.accession_number == "ГМИГ КП ЭФ-55"
    assert item.info.classifier == "Петров А.А._Соловки"
    # сначала файлы из корня папки, затем из подпапок
    assert [f.relpath for f in item.files] == ["photo_exif.jpg", "video_h264_aac.mp4", "sub/письмо.txt"]

    xml = folder / f"{ITEM}.xml"
    root = ET.parse(xml).getroot()
    assert root.tag == "DigitalMuseumItem"
    assert root.get("formatVersion") == "2.0"
    assert root.find("Generator").get("version")
    assert root.findtext("Item/AccessionNumber") == "ГМИГ КП ЭФ-55"
    assert root.findtext("Item/Topography") == "Сервер 1"
    assert root.find("Item/Title") is None  # пустые поля не пишутся
    files = root.findall("Files/File")
    assert len(files) == 3
    assert files[2].findtext("RelativePath") == "sub/письмо.txt"
    assert files[0].find("RelativePath") is None

    data = (folder / "video_h264_aac.mp4").read_bytes()
    sums = {cs.get("algorithm"): cs.text for cs in files[1].iterfind("Checksums/Checksum")}
    assert list(sums) == ["SHA1", "GOST34.11-2018-256"]  # SHA-1 первой, как в КАМИС
    assert sums["SHA1"] == hashlib.sha1(data).hexdigest().upper()
    assert sums["GOST34.11-2018-256"] == streebog.new(256, data).hexdigest().upper()
    assert xml.read_bytes().startswith(b'<?xml version="1.0" encoding="UTF-8"?>')

    parsed = checksums.parse(folder / f"{ITEM}.checksums.txt")
    listed = parsed.by_file()
    assert set(listed) == {"photo_exif.jpg", "sub/письмо.txt", "video_h264_aac.mp4", f"{ITEM}.xml"}
    assert listed[f"{ITEM}.xml"]["sha1"] == hashlib.sha1(xml.read_bytes()).hexdigest().upper()
    assert (folder / f"{ITEM}.kamis.txt").exists()


def test_text_master_is_never_overwritten(tmp_path):
    """Ошибка версии 1.x: файл контрольных сумм затирал исходный .txt."""
    src = tmp_path / "notes.txt"
    original = "Важный текст документа\n".encode("utf-8")
    src.write_bytes(original)
    reports, _ = describe(src)
    assert reports[0].status == package.OK
    assert src.read_bytes() == original
    assert (tmp_path / "notes.txt.xml").exists()
    assert (tmp_path / "notes.txt.checksums.txt").exists()


def test_same_stem_files_do_not_collide(tmp_path):
    """Ошибка версии 1.x: photo.jpg и photo.tif писали в один photo.xml."""
    shutil.copy(DATA / "photo_jfif.jpg", tmp_path / "photo.jpg")
    shutil.copy(DATA / "scan_lzw.tif", tmp_path / "photo.tif")
    reports, _ = describe(tmp_path, package.MODE_FILES)
    assert [r.status for r in reports] == [package.OK, package.OK]
    for name in ("photo.jpg", "photo.tif"):
        root = ET.parse(tmp_path / f"{name}.xml").getroot()
        assert root.findtext("Files/File/FileName") == name


def test_files_mode_ignores_own_outputs(tmp_path):
    shutil.copy(DATA / "photo_jfif.jpg", tmp_path / "a.jpg")
    describe(tmp_path, package.MODE_FILES)
    reports, plan = describe(tmp_path, package.MODE_FILES)
    assert [i.base_name for i in plan.items] == ["a.jpg"]
    assert reports[0].status == package.SKIPPED


def test_subfolders_mode(tmp_path):
    make_item(tmp_path, "КП ЭФ-1_Иванов")
    make_item(tmp_path, "КП ЭФ-2", files=("audio.mp3",))
    (tmp_path / "лишний.jpg").write_bytes(b"x")
    reports, plan = describe(tmp_path, package.MODE_SUBFOLDERS)
    assert [r.item.info.accession_number for r in reports] == ["КП ЭФ-1", "КП ЭФ-2"]
    assert all(r.status == package.OK for r in reports)
    assert any("лишний.jpg" in w for w in plan.warnings)


def test_explicit_number_for_single_item(tmp_path):
    folder = make_item(tmp_path, "папка без номера")
    reports, _ = describe(folder, info=ItemInfo(accession_number="КП ЭФ-99", title="Интервью"))
    root = ET.parse(folder / "папка без номера.xml").getroot()
    assert root.findtext("Item/AccessionNumber") == "КП ЭФ-99"
    assert root.findtext("Item/Title") == "Интервью"


def test_overwrite_rules(tmp_path):
    folder = make_item(tmp_path)
    describe(folder)
    reports, _ = describe(folder)
    assert reports[0].status == package.SKIPPED

    reports, _ = describe(folder, overwrite=True)
    assert reports[0].status == package.OK

    with open(folder / "photo_exif.jpg", "ab") as f:
        f.write(b"changed")
    reports, _ = describe(folder, overwrite=True)
    assert reports[0].status == package.ERROR
    assert "photo_exif.jpg" in reports[0].message


def test_foreign_xml_is_not_overwritten(tmp_path):
    folder = make_item(tmp_path, "Предмет", files=("photo_jfif.jpg",))
    foreign = folder / "Предмет.xml"
    foreign.write_text("<data>чужой файл</data>", encoding="utf-8")
    reports, _ = describe(folder)
    assert reports[0].status == package.ERROR
    assert foreign.read_text(encoding="utf-8") == "<data>чужой файл</data>"


def test_empty_folder(tmp_path):
    (tmp_path / "Пусто").mkdir()
    reports, _ = describe(tmp_path / "Пусто")
    assert reports[0].status == package.ERROR


def test_cancel(tmp_path):
    folder = make_item(tmp_path)
    plan = package.plan(folder, package.MODE_FOLDER, ItemInfo())
    d = package.Describer()
    d.cancel.set()
    assert d.describe(plan.items[0]).status == package.CANCELLED
    assert not (folder / f"{ITEM}.xml").exists()


def test_kamis_csv(tmp_path):
    make_item(tmp_path, "КП 1")
    reports, _ = describe(tmp_path, package.MODE_SUBFOLDERS)
    out = kamis.write_csv([r.item for r in reports], tmp_path / "k.csv")
    text = out.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("Учётный номер;")
    assert ";SHA-1;ГОСТ 34.11-2018;" in text.splitlines()[0]
    assert "AVC/H.264" in text


# --- сверка ---

def test_verify_ok_and_problems(tmp_path):
    folder = make_item(tmp_path)
    describe(folder)
    [check] = verify.verify_tree(tmp_path)
    assert check.ok, check.files
    assert {f.status for f in check.files} == {verify.OK}

    (folder / "новый.txt").write_text("x", encoding="utf-8")
    with open(folder / "video_h264_aac.mp4", "ab") as f:
        f.write(b"!")
    (folder / "photo_exif.jpg").unlink()
    [check] = verify.verify_tree(tmp_path)
    status = {f.relpath: f.status for f in check.files}
    assert status["video_h264_aac.mp4"] == verify.MISMATCH
    assert status["photo_exif.jpg"] == verify.MISSING
    assert status["новый.txt"] == verify.EXTRA
    assert not check.ok


def test_verify_damaged_file(tmp_path):
    folder = make_item(tmp_path, "П", files=())
    (folder / "bad.png").write_bytes((DATA / "image.png").read_bytes()[:-20] + b"\x00" * 20)
    describe(folder)
    [check] = verify.verify_tree(folder)
    assert {f.relpath: f.status for f in check.files}["bad.png"] == verify.DAMAGED
    [check] = verify.verify_tree(folder, open_files=False)
    assert check.ok


def test_verify_backup(tmp_path):
    master = tmp_path / "master"
    make_item(master, "A")
    make_item(master, "B", files=("audio.mp3",))
    describe(master, package.MODE_SUBFOLDERS)
    backup = tmp_path / "backup"
    shutil.copytree(master, backup)
    assert all(c.ok for c in verify.verify_tree(master, backup))

    with open(backup / "B" / "audio.mp3", "r+b") as f:
        f.write(b"\x00\x00")
    (backup / "A" / "A.checksums.txt").write_text("# испорчен", encoding="utf-8")
    results = {c.target_root.name: c for c in verify.verify_tree(master, backup)}
    assert {f.relpath: f.status for f in results["B"].files}["audio.mp3"] == verify.MISMATCH
    assert {f.relpath: f.status for f in results["A"].files}["A.checksums.txt"] == verify.MISMATCH


def test_verify_multiple_items_in_one_folder(tmp_path):
    shutil.copy(DATA / "photo_jfif.jpg", tmp_path / "a.jpg")
    shutil.copy(DATA / "image.png", tmp_path / "b.png")
    describe(tmp_path, package.MODE_FILES)
    results = verify.verify_tree(tmp_path)
    assert len(results) == 2
    assert all(c.ok for c in results)
    assert not any(f.status == verify.EXTRA for c in results for f in c.files)


def _legacy_description(folder: Path, master: Path) -> None:
    """Файлы в формате версии 1.x (как их писал xml_generator.py)."""
    stem = master.stem
    data = master.read_bytes()
    gost = streebog.new(256, data).hexdigest().upper()
    sha1 = hashlib.sha1(data).hexdigest().upper()
    xml = folder / f"{stem}.xml"
    xml.write_text(
        "<?xml version='1.0' encoding='utf-8'?>\n<GMIG><File name=\"%s\"><Сommon name=\"Общие свойства\">"
        "<fileName name=\"Имя файла мастер-копии\">%s</fileName>"
        "<Checksum name=\"Контрольная сумма\"><hash type=\"GR3411_2012_256\">%s</hash>"
        "<hash type=\"SHA1\">%s</hash></Checksum></Сommon></File></GMIG>" % (stem, master.name, gost, sha1),
        encoding="utf-8",
    )
    xml_data = xml.read_bytes()
    (folder / f"{stem}.txt").write_text(
        f"{master.name}\nКонтрольная сумма:\nGR3411_2012_256: {gost}\nSHA1: {sha1}\n\n"
        f"{xml.name}\nКонтрольная сумма:\n"
        f"GR3411_2012_256: {streebog.new(256, xml_data).hexdigest().upper()}\n"
        f"SHA1: {hashlib.sha1(xml_data).hexdigest().upper()}",
        encoding="utf-8",
    )
    (folder / f"{stem}_KAMIS.txt").write_text("Имя файла мастер-копии: ...", encoding="utf-8")


def test_legacy_v1_descriptions(tmp_path):
    shutil.copy(DATA / "photo_jfif.jpg", tmp_path / "фото.jpg")
    shutil.copy(DATA / "audio.mp3", tmp_path / "запись.mp3")
    _legacy_description(tmp_path, tmp_path / "фото.jpg")
    _legacy_description(tmp_path, tmp_path / "запись.mp3")

    # файлы 1.x распознаются как служебные и не попадают в мастер-копии
    assert [p.name for p in package.collect_files(tmp_path)] == ["запись.mp3", "фото.jpg"]
    assert xmlio.read_checksums(tmp_path / "фото.xml")["фото.jpg"]["gost256"]

    results = verify.verify_tree(tmp_path)
    assert len(results) == 2
    assert all(c.version == "1.x" for c in results)
    assert all(c.ok for c in results), [c.files for c in results]
    checked = {f.relpath for c in results for f in c.files}
    assert {"фото.jpg", "фото.xml", "запись.mp3", "запись.xml"} <= checked

    with open(tmp_path / "фото.jpg", "ab") as f:
        f.write(b"x")
    results = {c.checksum_file.name: c for c in verify.verify_tree(tmp_path)}
    assert not results["фото.txt"].ok
    assert results["запись.txt"].ok


def test_text_resembling_legacy_checksums_is_a_master(tmp_path):
    doc = tmp_path / "заметка.txt"
    doc.write_text("Отчёт\nКонтрольная сумма:\nSHA1: ABCDEF\nИ ещё немного текста.\n", encoding="utf-8")
    assert checksums.parse(doc) is None
    assert package.collect_files(tmp_path) == [doc]


def test_checksum_file_is_bsd_compatible(tmp_path):
    folder = make_item(tmp_path, "К", files=("image.png",))
    describe(folder)
    lines = (folder / "К.checksums.txt").read_text(encoding="utf-8").splitlines()
    sha_lines = [line for line in lines if line.startswith("SHA1 (")]
    assert sha_lines[0] == f"SHA1 (image.png) = {hashlib.sha1((folder / 'image.png').read_bytes()).hexdigest().upper()}"


def test_cli(tmp_path, capsys):
    folder = make_item(tmp_path, "КП 7", files=("image.png",))
    assert cli.main(["describe", str(folder), "--topography", "Т"]) == 0
    report = tmp_path / "report.csv"
    assert cli.main(["verify", str(tmp_path), "--report", str(report)]) == 0
    assert report.read_text(encoding="utf-8-sig").startswith("Дата сверки;")
    (folder / "image.png").write_bytes(b"changed")
    assert cli.main(["verify", str(tmp_path)]) == 3
    assert cli.main(["info", str(DATA / "audio.mp3"), "--hash"]) == 0
    out = capsys.readouterr().out
    assert "ГОСТ 34.11-2018" in out


def test_algorithms_in_new_descriptions():
    assert hashing.DEFAULT_ALGORITHMS == ("sha1", "gost256")


@pytest.mark.parametrize("name,sep,expected", [
    ("ГМИГ КП ЭФ-55_Петров А.А._Соловки", "_", ("ГМИГ КП ЭФ-55", "Петров А.А._Соловки")),
    ("ГМИГ КП ЭФ-55 Петров", " ", ("ГМИГ", "КП ЭФ-55 Петров")),
    ("КП ЭФ-55__Петров_А.А.", "__", ("КП ЭФ-55", "Петров_А.А.")),
    ("КП ЭФ-55_Петров", "", ("КП ЭФ-55_Петров", "")),
    ("без разделителя", "_", ("без разделителя", "")),
])
def test_split_name(name, sep, expected):
    assert package.split_name(name, sep) == expected


def test_plan_uses_separator(tmp_path):
    # без точки в конце: Windows отбрасывает её в имени папки
    make_item(tmp_path, "КП ЭФ-1__Иванов_И.И._Соловки", files=("image.png",))
    plan = package.plan(tmp_path, package.MODE_SUBFOLDERS, ItemInfo(), separator="__")
    assert plan.items[0].info.accession_number == "КП ЭФ-1"
    assert plan.items[0].info.classifier == "Иванов_И.И._Соловки"


def test_natural_order_duplicates_and_number_warning(tmp_path):
    folder = tmp_path / "ЦНАР_102"
    folder.mkdir()
    for n in (1, 2, 10, 100, 11):
        shutil.copy(DATA / "image.png", folder / f"ЦНАР_102_{n}.png")
        (folder / f"ЦНАР_102_{n}.png").write_bytes((DATA / "image.png").read_bytes() + bytes([n]))
    shutil.copy(folder / "ЦНАР_102_100.png", folder / "ЦНАР_102_5 (2).png")
    reports, _ = describe(folder)
    report = reports[0]
    assert [f.relpath for f in report.item.files] == [
        "ЦНАР_102_1.png", "ЦНАР_102_2.png", "ЦНАР_102_5 (2).png", "ЦНАР_102_10.png",
        "ЦНАР_102_11.png", "ЦНАР_102_100.png"]
    assert any("одинаковым содержимым" in w and "ЦНАР_102_5 (2).png" in w and "ЦНАР_102_100.png" in w
               for w in report.warnings)
    assert any("нет цифр" in w for w in report.warnings)  # «ЦНАР» — номер без цифр

    # с разделителем «нет» номер — всё имя, предупреждения о номере нет
    plan = package.plan(folder, package.MODE_FOLDER, ItemInfo(), separator="")
    assert plan.items[0].info.accession_number == "ЦНАР_102"


def test_single_file_item_ignores_neighbours(tmp_path):
    """Описание одного файла не должно считать соседние файлы и подпапки «лишними»."""
    shutil.copy(DATA / "audio.mp3", tmp_path / "запись.mp3")
    (tmp_path / "другое").mkdir()
    shutil.copy(DATA / "image.png", tmp_path / "другое" / "посторонний.png")
    shutil.copy(DATA / "image.png", tmp_path / "сосед.png")
    describe(tmp_path / "запись.mp3")
    [check] = verify.verify_tree(tmp_path / "запись.mp3.checksums.txt")
    assert check.ok
    assert {f.status for f in check.files} == {verify.OK}


# --- обновление описаний версии 1.x ---

def _v1_folder(tmp_path, name="ГМИГ ЭФ-21 Фотография", master="ГМИГ ЭФ-21 Фотография.tif", source="scan_lzw.tif"):
    folder = tmp_path / name
    folder.mkdir()
    shutil.copy(DATA / source, folder / master)
    _legacy_description(folder, folder / master)
    return folder


def test_v1_description_is_verified_and_archived(tmp_path):
    folder = _v1_folder(tmp_path)  # XML 1.x называется так же, как будущий XML 2.0
    reports, _ = describe(folder)
    assert reports[0].status == package.OK, reports[0].message
    assert "перенесено" in reports[0].message
    archive = folder / package.LEGACY_ARCHIVE_DIR
    assert sorted(p.name for p in archive.iterdir()) == [
        "ГМИГ ЭФ-21 Фотография.txt", "ГМИГ ЭФ-21 Фотография.xml", "ГМИГ ЭФ-21 Фотография_KAMIS.txt"]
    assert ET.parse(folder / "ГМИГ ЭФ-21 Фотография.xml").getroot().tag == "DigitalMuseumItem"
    [check] = verify.verify_tree(tmp_path)  # архив не проверяется и не мешает
    assert check.ok and check.version == "2.0"
    # повторный запуск: описание 2.0 уже есть
    reports, _ = describe(folder)
    assert reports[0].status == package.SKIPPED


def test_v1_description_of_another_file_is_not_touched(tmp_path):
    """Ошибка 1.x: описание файла ЭФ-18 оказалось в папке ЭФ-17."""
    folder = _v1_folder(tmp_path, "ЭФ-17", "ЭФ-17.tif")
    other = tmp_path / "ЭФ-18.tif"
    shutil.copy(DATA / "photo_jfif.jpg", other)
    (folder / "ЭФ-17.txt").unlink()
    (folder / "ЭФ-17.xml").unlink()
    (folder / "ЭФ-17_KAMIS.txt").unlink()
    _legacy_description(folder, other)  # описание ЭФ-18 в папке ЭФ-17
    before = sorted(p.name for p in folder.iterdir())
    reports, _ = describe(folder)
    assert reports[0].status == package.ERROR
    assert "ЭФ-18.tif" in reports[0].message and "не в ту папку" in reports[0].message
    assert sorted(p.name for p in folder.iterdir()) == before


def test_v1_changed_file_is_not_upgraded(tmp_path):
    folder = _v1_folder(tmp_path)
    with open(folder / "ГМИГ ЭФ-21 Фотография.tif", "ab") as f:
        f.write(b"x")
    reports, _ = describe(folder)
    assert reports[0].status == package.ERROR
    assert "изменился со времени описания 1.x" in reports[0].message
    assert not (folder / package.LEGACY_ARCHIVE_DIR).exists()


def test_v1_upgrade_in_files_mode_only_takes_own_description(tmp_path):
    shutil.copy(DATA / "photo_jfif.jpg", tmp_path / "a.jpg")
    shutil.copy(DATA / "image.png", tmp_path / "b.png")
    _legacy_description(tmp_path, tmp_path / "a.jpg")
    _legacy_description(tmp_path, tmp_path / "b.png")
    reports, _ = describe(tmp_path / "a.jpg")
    assert reports[0].status == package.OK
    archived = sorted(p.name for p in (tmp_path / package.LEGACY_ARCHIVE_DIR).iterdir())
    assert archived == ["a.txt", "a.xml", "a_KAMIS.txt"]
    assert (tmp_path / "b.xml").exists() and (tmp_path / "b.txt").exists()


def test_v1_files_restored_if_writing_fails(tmp_path, monkeypatch):
    folder = _v1_folder(tmp_path)
    monkeypatch.setattr(xmlio, "write_all", lambda files: (_ for _ in ()).throw(OSError(28, "No space left")))
    reports, _ = describe(folder)
    assert reports[0].status == package.ERROR
    assert (folder / "ГМИГ ЭФ-21 Фотография.txt").exists()
    assert ET.parse(folder / "ГМИГ ЭФ-21 Фотография.xml").getroot().tag == "GMIG"
    assert not list((folder / package.LEGACY_ARCHIVE_DIR).iterdir())
