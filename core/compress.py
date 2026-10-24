from pathlib import Path
import zstandard as zstd
from typing import Optional
import threading


class CompressionManager:
    def __init__(self, dict_path: Optional[str] = None, level: int = 3):
        self.level = level
        self.dict_data = None
        
        if dict_path:
            with open(dict_path, 'rb') as f:
                self.dict_data = zstd.ZstdCompressionDict(f.read())
                self.dict_data.precompute_compress(level=level)
        
        # Thread-local storage для каждого потока
        # zstandart классы (Compressor и Decompressor) потоко небезопасные, поэтому важно иметь для каждого потока свой экземляр класса такого типа
        self._local = threading.local()
    
    def _get_compressor(self) -> zstd.ZstdCompressor:
        """Получить компрессор для текущего потока"""
        if not hasattr(self._local, 'compressor'):
            self._local.compressor = zstd.ZstdCompressor(
                level=self.level,
                dict_data=self.dict_data
            )
        return self._local.compressor
    
    def _get_decompressor(self) -> zstd.ZstdDecompressor:
        """Получить декомпрессор для текущего потока"""
        if not hasattr(self._local, 'decompressor'):
            self._local.decompressor = zstd.ZstdDecompressor(
                dict_data=self.dict_data
            )
        return self._local.decompressor
    
    def compress(self, payload: bytes) -> bytes:
        """Сжать данные"""
        compressor = self._get_compressor()
        return compressor.compress(payload)
    
    def decompress(self, payload: bytes, max_output_size: int = 10*1024*1024) -> bytes:
        """Распаковать данные"""
        decompressor = self._get_decompressor()
        return decompressor.decompress(payload, max_output_size=max_output_size)


# Использование
markdown_dict_path = Path(__file__).parent.parent / 'dicts' / 'markdown-response.dict'
compressor_manager = CompressionManager(str(markdown_dict_path), level=2)
compressor_manager_withut_dict = CompressionManager()

# print(compressor_manager_withut_dict.compress(b""))
