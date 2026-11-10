from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
from numpy.typing import ArrayLike


def validate_index(fragment_ids: list[str], vectors: np.ndarray) -> None:
    if vectors.ndim != 2 or vectors.shape[0] != len(fragment_ids):
        raise ValueError("Число строк матрицы должно совпадать с числом ID фрагментов")
    if vectors.dtype.kind not in "fiu":
        raise ValueError("Векторы должны содержать числа")
    if len(set(fragment_ids)) != len(fragment_ids):
        raise ValueError("ID фрагментов в индексе должны быть уникальными")


def save_index(
    path: Path, fragment_ids: list[str], vectors: ArrayLike, *, fingerprint: str
) -> None:
    vectors = np.asarray(vectors)
    validate_index(fragment_ids, vectors)
    temporary_file = NamedTemporaryFile(dir=path.parent, delete=False)
    temporary_path = Path(temporary_file.name)
    try:
        with temporary_file:
            np.savez(
                temporary_file,
                vectors=vectors,
                fragment_ids=np.asarray(fragment_ids, dtype=str),
                fingerprint=fingerprint,
            )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_index(
    path: Path, *, expected_fingerprint: str | None = None
) -> tuple[list[str], np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        if expected_fingerprint is not None and (
            "fingerprint" not in data or data["fingerprint"].item() != expected_fingerprint
        ):
            raise ValueError("Индекс построен для другой модели или других фрагментов")
        stored_ids = data["fragment_ids"]
        if stored_ids.ndim != 1 or stored_ids.dtype.kind != "U":
            raise ValueError("В индексе ожидается одномерный массив строковых ID")
        fragment_ids = stored_ids.tolist()
        vectors = data["vectors"]
    validate_index(fragment_ids, vectors)
    return fragment_ids, vectors
