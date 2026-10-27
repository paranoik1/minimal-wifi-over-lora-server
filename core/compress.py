import threading
from pathlib import Path

import zstandard as zstd


class CompressionManager:
    def __init__(self, dict_path: str | None = None, level: int = 3):
        self.level = level
        self.dict_data = None

        if dict_path:
            with open(dict_path, "rb") as f:
                self.dict_data = zstd.ZstdCompressionDict(f.read())
                self.dict_data.precompute_compress(level=level)

        # Thread-local storage для каждого потока
        # zstandart классы (Compressor и Decompressor) потоко небезопасные, поэтому важно иметь для каждого потока свой экземляр класса такого типа
        self._local = threading.local()

    def _get_compressor(self) -> zstd.ZstdCompressor:
        """Получить компрессор для текущего потока"""
        if not hasattr(self._local, "compressor"):
            self._local.compressor = zstd.ZstdCompressor(
                level=self.level, 
                dict_data=self.dict_data, 
                write_dict_id=False, 
                write_checksum=False,
                write_content_size=False
            )
        return self._local.compressor

    def _get_decompressor(self) -> zstd.ZstdDecompressor:
        """Получить декомпрессор для текущего потока"""
        if not hasattr(self._local, "decompressor"):
            self._local.decompressor = zstd.ZstdDecompressor(dict_data=self.dict_data)
        return self._local.decompressor

    def compress(self, payload: bytes) -> bytes:
        """Сжать данные"""
        compressor = self._get_compressor()
        return compressor.compress(payload)

    def decompress_frames(
        self,
        payload: bytes,
        max_output_size: int = 10 * 1024 * 1024,
    ) -> bytes:
        decompressor = self._get_decompressor()

        with decompressor.stream_reader(
            payload,
            read_across_frames=True,
        ) as reader:
            result = reader.read(max_output_size + 1)

        if len(result) > max_output_size:
            raise ValueError("Decompressed payload exceeds size limit")

        return result

    def decompress(
        self, payload: bytes, max_output_size: int = 10 * 1024 * 1024
    ) -> bytes:
        """Распаковать данные"""
        decompressor = self._get_decompressor()
        return decompressor.decompress(payload, max_output_size=max_output_size)


# Использование
markdown_dict_path = Path(__file__).parent.parent / "dicts" / "markdown-response.dict"

default_compressor = CompressionManager()
markdown_compressor = CompressionManager(str(markdown_dict_path))
