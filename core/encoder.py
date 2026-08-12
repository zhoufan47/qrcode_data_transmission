"""
QR码编码器：将文件编码为QR码序列
"""

import base64
import hashlib
import os
import random
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import qrcode
from PIL import Image

from .protocol import MetaFrame, DataFrame, EndFrame, compute_md5


@dataclass
class QREntry:
    """单个QR码条目"""
    frame_data: str          # 编码后的帧字符串
    chunk_index: int         # 原始chunk序号（-1=META, -2=END）
    qr_image: Image.Image    # QR码图像


@dataclass
class EncodeResult:
    """编码结果"""
    transfer_id: str
    filename: str
    file_size: int
    total_chunks: int
    chunk_size: int
    file_md5: str
    meta_entry: QREntry
    data_entries: List[QREntry]     # 按原始顺序排列
    end_entry: QREntry
    # 乱序播放列表（包含所有帧）
    shuffled_entries: List[QREntry] = field(default_factory=list)


class FileEncoder:
    """
    文件编码器：将文件分块并生成QR码

    支持两种播放模式:
    1. 顺序模式: meta -> data[0] -> data[1] -> ... -> end
    2. 乱序模式: meta -> data[random] -> data[random] -> ... -> end (循环播放data部分)
    """

    def __init__(
        self,
        chunk_size: int = 1024,
        qr_size: int = 600,
        qr_border: int = 4,
        error_correction: int = qrcode.constants.ERROR_CORRECT_M,
        shuffle: bool = True,
    ):
        """
        Args:
            chunk_size: 每个数据块的原始字节数
            qr_size: QR码图像像素尺寸
            qr_border: QR码边框大小
            error_correction: 纠错级别 (L=7%, M=15%, Q=25%, H=30%)
            shuffle: 是否启用乱序播放
        """
        self.chunk_size = chunk_size
        self.qr_size = qr_size
        self.qr_border = qr_border
        self.error_correction = error_correction
        self.shuffle = shuffle

    def encode_file(self, filepath: str, transfer_id: Optional[str] = None) -> EncodeResult:
        """
        编码文件为QR码序列

        Args:
            filepath: 文件路径
            transfer_id: 传输ID（不指定则自动生成）

        Returns:
            EncodeResult 编码结果
        """
        if transfer_id is None:
            transfer_id = uuid.uuid4().hex[:12]

        # 读取文件
        with open(filepath, "rb") as f:
            file_data = f.read()

        file_size = len(file_data)
        filename = os.path.basename(filepath)
        file_md5 = compute_md5(file_data)

        # 分块
        chunks = []
        for i in range(0, file_size, self.chunk_size):
            chunks.append(file_data[i : i + self.chunk_size])

        total_chunks = len(chunks)

        # 生成META帧
        meta_frame = MetaFrame(
            transfer_id=transfer_id,
            filename=filename,
            file_size=file_size,
            total_chunks=total_chunks,
            chunk_size=self.chunk_size,
            file_md5=file_md5,
        )
        meta_entry = QREntry(
            frame_data=meta_frame.encode(),
            chunk_index=-1,
            qr_image=self._make_qr(meta_frame.encode()),
        )

        # 生成DATA帧
        data_entries = []
        for idx, chunk in enumerate(chunks):
            data_b64 = base64.b64encode(chunk).decode("ascii")
            chunk_md5 = compute_md5(chunk)
            data_frame = DataFrame(
                transfer_id=transfer_id,
                chunk_index=idx,
                total_chunks=total_chunks,
                data_base64=data_b64,
                chunk_md5=chunk_md5,
            )
            data_entries.append(
                QREntry(
                    frame_data=data_frame.encode(),
                    chunk_index=idx,
                    qr_image=self._make_qr(data_frame.encode()),
                )
            )

        # 生成END帧
        end_frame = EndFrame(
            transfer_id=transfer_id,
            total_chunks=total_chunks,
            file_md5=file_md5,
        )
        end_entry = QREntry(
            frame_data=end_frame.encode(),
            chunk_index=-2,
            qr_image=self._make_qr(end_frame.encode()),
        )

        # 生成乱序播放列表
        shuffled = self._build_shuffled_playlist(meta_entry, data_entries, end_entry)

        return EncodeResult(
            transfer_id=transfer_id,
            filename=filename,
            file_size=file_size,
            total_chunks=total_chunks,
            chunk_size=self.chunk_size,
            file_md5=file_md5,
            meta_entry=meta_entry,
            data_entries=data_entries,
            end_entry=end_entry,
            shuffled_entries=shuffled,
        )

    def _make_qr(self, data: str) -> Image.Image:
        """生成QR码图像"""
        qr = qrcode.QRCode(
            version=None,  # 自动检测
            error_correction=self.error_correction,
            box_size=10,
            border=self.qr_border,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img = img.convert("RGB")
        img = img.resize((self.qr_size, self.qr_size), Image.LANCZOS)
        return img

    def _build_shuffled_playlist(
        self,
        meta_entry: QREntry,
        data_entries: List[QREntry],
        end_entry: QREntry,
    ) -> List[QREntry]:
        """
        构建播放列表：META + 乱序DATA(循环) + END

        策略: META先播放，然后DATA按乱序循环播放，
        最后END帧在完成信号后播放。
        实际循环播放时，META也会周期性插入以确保新接收方能快速开始。
        """
        playlist = [meta_entry]

        if self.shuffle and len(data_entries) > 1:
            # 创建多个乱序副本，确保每轮顺序不同
            rounds = max(2, min(5, 50 // len(data_entries) + 1))
            for _ in range(rounds):
                shuffled = list(data_entries)
                random.shuffle(shuffled)
                playlist.extend(shuffled)
        else:
            playlist.extend(data_entries)

        playlist.append(end_entry)
        return playlist

    def get_shuffled_data_entries(self, data_entries: List[QREntry]) -> List[QREntry]:
        """获取当前轮次的乱序DATA帧"""
        shuffled = list(data_entries)
        random.shuffle(shuffled)
        return shuffled

    @staticmethod
    def estimate_chunks(filepath: str, chunk_size: int) -> Tuple[int, int]:
        """估算文件需要的chunk数"""
        file_size = os.path.getsize(filepath)
        num_chunks = (file_size + chunk_size - 1) // chunk_size
        return num_chunks, file_size
