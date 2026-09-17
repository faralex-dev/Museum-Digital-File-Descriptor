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
    assert sums["SHA256"] == hashlib.sha256(data).hexdigest().upper()
    assert sums["GOST34.11-2018-256"] == streebog.new(256, data).hexdigest().upper()
    assert xml.read_bytes().startswith(b'<?xml version="1.0" encoding="UTF-8"?>')

    parsed = checksums.parse(folder / f"{ITEM}.checksums.txt")
    listed = parsed.by_file()
    assert set(listed) == {"photo_exif.jpg", "sub/письмо.txt", "video_h264_aac.mp4", f"{ITEM}.xml"}
    assert listed[f"{ITEM}.xml"]["sha256"] == hashlib.sha256(xml.read_bytes()).hexdigest().upper()
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
    sha_lines = [line for line in lines if line.startswith("SHA256 (")]
    assert sha_lines[0] == f"SHA256 (image.png) = {hashlib.sha256((folder / 'image.png').read_bytes()).hexdigest().upper()}"


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
    assert hashing.DEFAULT_ALGORITHMS == ("sha256", "gost256")
