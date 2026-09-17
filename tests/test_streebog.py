import hashlib
import os
import random

import pytest

from mdfd import hashing
from mdfd.hashing import streebog

# Контрольные примеры ГОСТ Р 34.11-2012 (приложение А), в порядке байтов,
# который выдают pystribog, gostcrypto и OpenSSL gost-engine.
M1 = b"012345678901234567890123456789012345678901234567890123456789012"
M2 = "Се ветри, Стрибожи внуци, веютъ с моря стрелами на храбрыя плъкы Игоревы".encode("cp1251")
VECTORS = [
    (M1, 256, "9d151eefd8590b89daa6ba6cb74af9275dd051026bb149a452fd84e5e57b5500"),
    (M1, 512, "1b54d01a4af5b9d5cc3d86d68d285462b19abc2475222f35c085122be4ba1ffa"
              "00ad30f8767b3a82384c6574f024c311e2a481332b08ef7f41797891c1646f48"),
    (M2, 256, "9dd2fe4e90409e5da87f53976d7405b0c0cac628fc669a741d50063c557e8f50"),
    (M2, 512, "1e88e62226bfca6f9994f1f2d51569e0daf8475a3b0fe61a5300eee46d961376"
              "035fe83549ada2b8620fcd7c496ce5b33f0cb9dddc2b6460143b03dabac9fb28"),
    (b"", 256, "3f539a213e97c802cc229d474c6aa32a825a360b2a933a949fd925208d9ce1bb"),
]


@pytest.mark.parametrize("pure", [False, True])
@pytest.mark.parametrize("data,bits,expected", VECTORS)
def test_standard_vectors(data, bits, expected, pure):
    assert streebog.new(bits, data, pure_python=pure).hexdigest() == expected


def test_native_module_is_built():
    # В сборках программы модуль на C должен быть, иначе ГОСТ считается очень медленно.
    if os.environ.get("MDFD_REQUIRE_NATIVE"):
        assert streebog.BACKEND == "C"


@pytest.mark.parametrize("bits", [256, 512])
def test_chunked_updates_match_python(bits):
    rng = random.Random(bits)
    for size in (1, 63, 64, 65, 127, 128, 4095, 4096, 4097, 10_000):
        data = rng.randbytes(size)
        h = streebog.new(bits)
        pos = 0
        while pos < size:
            step = rng.randint(1, 300)
            h.update(data[pos:pos + step])
            pos += step
        clone = h.copy()
        assert h.hexdigest() == streebog.new(bits, data, pure_python=True).hexdigest()
        assert clone.hexdigest() == h.hexdigest()


def test_digest_does_not_change_state():
    h = streebog.new(256)
    h.update(b"abc")
    first = h.hexdigest()
    assert h.hexdigest() == first
    h.update(b"def")
    assert h.hexdigest() == streebog.new(256, b"abcdef").hexdigest()


def test_reference_implementation_if_available():
    gost = pytest.importorskip("gostcrypto.gosthash")
    data = os.urandom(100_003)
    for bits in (256, 512):
        assert streebog.new(bits, data).hexdigest() == gost.new(f"streebog{bits}", data=bytearray(data)).hexdigest()


def test_hash_file_single_pass(tmp_path):
    path = tmp_path / "f.bin"
    data = os.urandom(3 * hashing.CHUNK + 17)
    path.write_bytes(data)
    seen = []
    sums = hashing.hash_file(path, ("sha256", "gost256", "sha1"), progress=seen.append)
    assert sum(seen) == len(data)
    assert sums["sha256"] == hashlib.sha256(data).hexdigest().upper()
    assert sums["sha1"] == hashlib.sha1(data).hexdigest().upper()
    assert sums["gost256"] == streebog.new(256, data).hexdigest().upper()


def test_hash_file_cancel(tmp_path):
    import threading
    path = tmp_path / "f.bin"
    path.write_bytes(b"x" * 10)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(hashing.Cancelled):
        hashing.hash_file(path, cancel=cancel)


@pytest.mark.parametrize("tag,key", [
    ("GR3411_2012_256", "gost256"),      # версия 1.x
    ("GOST34.11-2018-256", "gost256"),
    ("SHA256", "sha256"),
    ("SHA-256", "sha256"),
    ("SHA1", "sha1"),
    ("unknown", None),
])
def test_algorithm_aliases(tag, key):
    algo = hashing.algorithm_by_tag(tag)
    assert (algo.key if algo else None) == key
