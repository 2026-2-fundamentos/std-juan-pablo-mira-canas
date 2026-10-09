import shutil
import string
from pathlib import Path

ACTIVITY_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ACTIVITY_DIR / "data"
INPUT_DIR = ACTIVITY_DIR / "temp" / "input"
OUTPUT_DIR = ACTIVITY_DIR / "temp" / "output"
SUBMISSION_DIR = ACTIVITY_DIR / "submission"


def reset_dir(directory):
    """Crea la carpeta si no existe y la deja vacía."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)


def copy_raw_files(n=1000):
    """Genera n copias de cada archivo de data/ en temp/input/."""
    reset_dir(INPUT_DIR)
    for file in sorted(DATA_DIR.glob("*")):
        text = file.read_text(encoding="utf-8")
        for i in range(1, n + 1):
            (INPUT_DIR / f"{file.stem}_{i:05d}.txt").write_text(text, encoding="utf-8")


def load_input():
    """Lee todas las líneas de los archivos de entrada como (archivo, línea)."""
    sequence = []
    for file in sorted(INPUT_DIR.glob("*")):
        with open(file, "r", encoding="utf-8") as f:
            for line in f:
                sequence.append((file.name, line))
    return sequence


def mapper(sequence):
    """Emite un par (palabra, 1) por cada palabra de cada línea."""
    table = str.maketrans("", "", string.punctuation)
    pairs = []
    for _, line in sequence:
        words = line.lower().translate(table).split()
        pairs.extend((word, 1) for word in words)
    return pairs


def shuffle_and_sort(pairs):
    """Ordena los pares para que las claves iguales queden juntas."""
    return sorted(pairs)


def reducer(pairs):
    """Suma los valores de cada clave consecutiva."""
    result = []
    for key, value in pairs:
        if result and result[-1][0] == key:
            result[-1] = (key, result[-1][1] + value)
        else:
            result.append((key, value))
    return result


def save_output(result):
    """Escribe part-00000 y el marcador _SUCCESS en temp/output/."""
    reset_dir(OUTPUT_DIR)
    with open(OUTPUT_DIR / "part-00000", "w", encoding="utf-8") as f:
        for key, value in result:
            f.write(f"{key}\t{value}\n")
    (OUTPUT_DIR / "_SUCCESS").write_text("", encoding="utf-8")


def copy_to_submission():
    """Copia el resultado de temp/output/ a submission/."""
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    for file in SUBMISSION_DIR.glob("*"):
        if file.name != ".gitkeep":
            file.unlink()
    for file in OUTPUT_DIR.glob("*"):
        shutil.copy2(file, SUBMISSION_DIR)


def main():

    copy_raw_files()
    sequence = load_input()
    pairs = mapper(sequence)
    pairs = shuffle_and_sort(pairs)
    result = reducer(pairs)
    save_output(result)
    copy_to_submission()


if __name__ == "__main__":
    main()
