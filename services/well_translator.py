from typing import Tuple, Union

"""
services/well_translator.py

Small helper functions to translate between plate well labels (row letter(s), column 1-based)
and zero-based integer indices.
"""



def row_label_to_index(row_label: str) -> int:
    """Convert row label like 'A' or 'AA' (case-insensitive) to zero-based index."""
    if not isinstance(row_label, str) or not row_label.strip():
        raise ValueError("row_label must be a non-empty string")
    s = row_label.strip().upper()
    idx = 0
    for ch in s:
        if not ('A' <= ch <= 'Z'):
            raise ValueError(f"invalid row character: {ch!r}")
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1  # convert 1-based base-26 to zero-based


def column_to_index(column: Union[int, str]) -> int:
    """Convert column (1-based) to zero-based index. Accepts int or numeric string."""
    try:
        c = int(column)
    except Exception:
        raise ValueError("column must be an integer or string representing an integer")
    if c < 1:
        raise ValueError("column must be >= 1")
    return c - 1


def well_to_indices(row: str, column: Union[int, str]) -> Tuple[int, int]:
    """
    Convert (row label, column) -> (row_index, col_index) both zero-based.
    Example: well_to_indices('A', 1) -> (0, 0)
    """
    return row_label_to_index(row), column_to_index(column)


def index_to_row_label(row_index: int) -> str:
    """Convert zero-based row_index to row label like 'A', 'Z', 'AA'."""
    if not isinstance(row_index, int) or row_index < 0:
        raise ValueError("row_index must be a non-negative integer")
    n = row_index + 1
    letters = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord('A') + rem))
    return ''.join(reversed(letters))


def index_to_column(column_index: int) -> int:
    """Convert zero-based column_index to 1-based column integer."""
    if not isinstance(column_index, int) or column_index < 0:
        raise ValueError("column_index must be a non-negative integer")
    return column_index + 1


def indices_to_well(row_index: int, column_index: int) -> Tuple[str, int]:
    """Convert zero-based indices -> (row_label, 1-based column)."""
    return index_to_row_label(row_index), index_to_column(column_index)


def indices_to_well_str(row_index: int, column_index: int) -> str:
    """Convert zero-based indices -> well string like 'A1'."""
    row_label, col = indices_to_well(row_index, column_index)
    return f"{row_label}{col}"


