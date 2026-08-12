"""
传输协议定义

帧格式:
    META|transfer_id|filename|file_size|total_chunks|chunk_size|file_md5
    DATA|transfer_id|chunk_index|total_chunks|data_base64|chunk_md5
    END|transfer_id|total_chunks|file_md5
"""

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FrameType(Enum):
    META = "META"
    DATA = "DATA"
    END = "END"


@dataclass
class MetaFrame:
    """文件元数据帧"""
    transfer_id: str
    filename: str
    file_size: int
    total_chunks: int
    chunk_size: int
    file_md5: str

    def encode(self) -> str:
        return f"META|{self.transfer_id}|{self.filename}|{self.file_size}|{self.total_chunks}|{self.chunk_size}|{self.file_md5}"

    @staticmethod
    def decode(data: str) -> Optional["MetaFrame"]:
        parts = data.split("|")
        if len(parts) != 7 or parts[0] != "META":
            return None
        try:
            return MetaFrame(
                transfer_id=parts[1],
                filename=parts[2],
                file_size=int(parts[3]),
                total_chunks=int(parts[4]),
                chunk_size=int(parts[5]),
                file_md5=parts[6],
            )
        except (ValueError, IndexError):
            return None


@dataclass
class DataFrame:
    """数据帧"""
    transfer_id: str
    chunk_index: int
    total_chunks: int
    data_base64: str
    chunk_md5: str

    def encode(self) -> str:
        return f"DATA|{self.transfer_id}|{self.chunk_index}|{self.total_chunks}|{self.data_base64}|{self.chunk_md5}"

    @staticmethod
    def decode(data: str) -> Optional["DataFrame"]:
        parts = data.split("|", 5)
        if len(parts) != 6 or parts[0] != "DATA":
            return None
        try:
            return DataFrame(
                transfer_id=parts[1],
                chunk_index=int(parts[2]),
                total_chunks=int(parts[3]),
                data_base64=parts[4],
                chunk_md5=parts[5],
            )
        except (ValueError, IndexError):
            return None


@dataclass
class EndFrame:
    """结束帧"""
    transfer_id: str
    total_chunks: int
    file_md5: str

    def encode(self) -> str:
        return f"END|{self.transfer_id}|{self.total_chunks}|{self.file_md5}"

    @staticmethod
    def decode(data: str) -> Optional["EndFrame"]:
        parts = data.split("|")
        if len(parts) != 4 or parts[0] != "END":
            return None
        try:
            return EndFrame(
                transfer_id=parts[1],
                total_chunks=int(parts[2]),
                file_md5=parts[3],
            )
        except (ValueError, IndexError):
            return None


@dataclass
class ParsedFrame:
    """解码后的帧（统一类型）"""
    frame_type: FrameType
    meta: Optional[MetaFrame] = None
    data: Optional[DataFrame] = None
    end: Optional[EndFrame] = None

    @staticmethod
    def parse(raw_text: str) -> Optional["ParsedFrame"]:
        raw_text = raw_text.strip()
        if raw_text.startswith("META|"):
            meta = MetaFrame.decode(raw_text)
            if meta:
                return ParsedFrame(frame_type=FrameType.META, meta=meta)
        elif raw_text.startswith("DATA|"):
            data = DataFrame.decode(raw_text)
            if data:
                return ParsedFrame(frame_type=FrameType.DATA, data=data)
        elif raw_text.startswith("END|"):
            end = EndFrame.decode(raw_text)
            if end:
                return ParsedFrame(frame_type=FrameType.END, end=end)
        return None


def compute_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def verify_chunk_md5(data: bytes, expected_md5: str) -> bool:
    return compute_md5(data) == expected_md5
