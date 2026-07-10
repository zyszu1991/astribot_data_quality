import h5py
import numpy as np
from typing import Union, List, Tuple, Iterator, Optional


class SafeHDF5Reader:
    """Safe reader for large HDF5 files with chunked reading support."""

    def __init__(self, file_path: str, chunk_size: int = 1000, size_limit: int = 10000):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.size_limit = size_limit
        self._file_handle = None
        self._dataset_info = {}
        self._current_dataset = None
        self._current_position = 0
        self._total_rows = 0
        self._use_chunked_read = False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        if self._file_handle is None:
            self._file_handle = h5py.File(self.file_path, "r")
            self._dataset_info = {}

            def visit_func(name, obj):
                if isinstance(obj, h5py.Dataset):
                    use_chunked = obj.size > self.size_limit
                    self._dataset_info[name] = {
                        "shape": obj.shape,
                        "dtype": obj.dtype,
                        "size": obj.size,
                        "use_chunked": use_chunked,
                        "chunks": obj.chunks,
                        "compression": obj.compression,
                    }

            self._file_handle.visititems(visit_func)
        return self._file_handle

    def close(self):
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None
            self._current_dataset = None
            self._dataset_info.clear()

    def select_dataset(self, dataset_path: str):
        if self._file_handle is None:
            raise ValueError("File not opened")
        if dataset_path not in self._dataset_info:
            raise ValueError(f"Dataset {dataset_path} not found")
        self._current_dataset = self._file_handle[dataset_path]
        self._total_rows = (
            self._current_dataset.shape[0]
            if self._current_dataset.ndim > 0
            else 1
        )
        self._current_position = 0
        self._use_chunked_read = self._dataset_info[dataset_path]["use_chunked"]

    def read_next(self) -> Optional[np.ndarray]:
        if self._current_dataset is None:
            raise ValueError("No dataset selected")
        if not self.has_next():
            return None
        if not self._use_chunked_read:
            data = self._current_dataset[:]
            self._current_position = self._total_rows
            return data
        start_row = self._current_position
        end_row = min(start_row + self.chunk_size, self._total_rows)
        chunk = self._current_dataset[start_row:end_row]
        self._current_position = end_row
        return chunk

    def has_next(self) -> bool:
        if self._current_dataset is None:
            raise ValueError("No dataset selected")
        return self._current_position < self._total_rows

    def reset(self):
        self._current_position = 0

    def get_dataset_info(self) -> dict:
        return self._dataset_info.copy()

    @property
    def progress(self) -> float:
        if self._current_dataset is None:
            raise ValueError("No dataset selected")
        if self._total_rows == 0:
            return 1.0
        return self._current_position / self._total_rows

    @property
    def total_rows(self) -> int:
        if self._current_dataset is None:
            raise ValueError("No dataset selected")
        return self._total_rows

    @property
    def current_position(self) -> int:
        if self._current_dataset is None:
            raise ValueError("No dataset selected")
        return self._current_position
