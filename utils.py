import re, os

# Вспомогательные функции
def convert_bytes(num: float) -> str:
    """Конвертирует байты в читаемый формат (KB, MB, GB) с точностью до сотых."""
    for unit in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0:
            return f"{num:.2f} {unit}"  # Точность до сотых
        num /= 1024.0
    return f"{num:.2f} PB"  # На случай, если число больше TB

def insert_spaces_from_end(s):
    """Добавляет пробелы каждые 3 символа с конца строки."""
    return ' '.join([s[::-1][i:i+3] for i in range(0, len(s), 3)])[::-1]

def file_size_calc(file_path: str) -> str:
    """Возвращает размер файла в красивом формате."""
    if os.path.isfile(file_path):
        file_size = os.stat(file_path).st_size
        return f"{convert_bytes(file_size)} ({insert_spaces_from_end(str(file_size))} bytes)"
    return "Файл не найден"

def round_to_nearest_bitrate(value: int) -> int:
    """Округляет битрейт до ближайшего стандартного значения."""
    bitrates = [8, 16, 24, 32, 48, 56, 64, 96, 112, 128, 144, 160, 192, 224, 256, 320]
    return min(bitrates, key=lambda x: abs(x - value))

def round_to_kb_or_mb(bits: int) -> str:
    """Преобразует биты в килобиты или мегабиты с точностью до десятых."""
    kb = bits / 1000
    mb = bits / 1_000_000

    if kb < 330:
        return f"{round_to_nearest_bitrate(kb)} кб/с"

    # Округляем до десятых
    kb_rounded = round(kb, 1)
    mb_rounded = round(mb, 1)

    return f"{mb_rounded:.1f} Мб/с" if kb > 1000 else f"{kb_rounded:.1f} кб/с"

# Функция замены
def replace_eng_with_rus(text):
    # Словарь для соответствия английских букв русским
    eng_to_rus = {
        'A': 'А', 'B': 'Б', 'C': 'Ц', 'D': 'Д', 'E': 'Е', 'F': 'Ф', 'G': 'Г',
        'H': 'Х', 'I': 'И', 'J': 'Й', 'K': 'К', 'L': 'Л', 'M': 'М', 'N': 'Н',
        'O': 'О', 'P': 'П', 'Q': 'К', 'R': 'Р', 'S': 'С', 'T': 'Т', 'U': 'У',
        'V': 'В', 'W': 'В', 'X': 'Кс', 'Y': 'Ы', 'Z': 'З',
        'a': 'а', 'b': 'б', 'c': 'ц', 'd': 'д', 'e': 'е', 'f': 'ф', 'g': 'г',
        'h': 'х', 'i': 'и', 'j': 'й', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н',
        'o': 'о', 'p': 'п', 'q': 'к', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у',
        'v': 'в', 'w': 'в', 'x': 'кс', 'y': 'ы', 'z': 'з'
    }

    def replace_match(match):
        return eng_to_rus.get(match.group(0), match.group(0))

    # Регулярное выражение для поиска английских букв
    pattern = re.compile(r'[A-Za-z]')
    return pattern.sub(replace_match, text)






