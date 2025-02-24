# Функции для подсчета контрольных сумм
# Алгоритм РФ Гост 2012 - GR3411_2012_256
# Алгоритм SHA-1

# Использование быстрой библиотеки pystribog
#
# git clone --depth 1  https://github.com/ddulesov/pystribog.git
# cd pystribog
# python3 setup.py build install

import hashlib
import os
from functools import partial
from tqdm import tqdm

def generate_file_checksum(file_path: str, hash_algo: str = 'GR3411_2012_256') -> tuple:
    """Генерация контрольной суммы для файла."""
    try:
        if not os.path.isfile(file_path):
            return hash_algo, "***** file_not_found ******"

        # Выбираем алгоритм хеширования
        if hash_algo == 'GR3411_2012_256':
            import _pystribog
            import binascii
            try:
                hasher = _pystribog.StribogHash(_pystribog.Hash256)
                block_size = 128 * 1024 * 1024  # 128MB блоки для GOST
            except ImportError:
                return hash_algo, "***** install_cryptography ******"
        elif hash_algo == 'SHA1':
            hasher = hashlib.sha1()
            block_size = 64 * 1024  # 64KB блоки для SHA1
        else:
            return hash_algo, "***** unsupported_algorithm ******"


        file_size = os.path.getsize(file_path)
        with tqdm(total=file_size, unit='B', unit_scale=True, desc='Хеширование "' + os.path.basename(file_path) + '" Алгоритм: ' + hash_algo) as pbar:
            # Чтение файла блоками по 64KB
            with open(file_path, 'rb') as f:
                for chunk in iter(partial(f.read, block_size), b''):
                    hasher.update(chunk)
                    pbar.update(len(chunk))

        # Получение хеша
        digest = hasher.hexdigest().upper()
        return hash_algo, digest

    except Exception as e:
        return hash_algo, f"***** error: {str(e)} ******"