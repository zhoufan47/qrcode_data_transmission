"""
QR码编码器：将文件编码为QR码序列
"""

import base64
import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

import qrcode
from PIL import Image

from .protocol import MetaFrame, DataFrame, EndFrame, compute_md5


@dataclass
class QREntry:
    """单个QR码条目（仅存帧数据，QR图像在展示时实时生成，避免大量图像驻留内存）"""
    frame_data: str          # 编码后的帧字符串
    chunk_index: int         # 原始chunk序号（-1=META, -2=END）


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
        # 缓存DATA帧的QR版本：数据帧长度一致，避免每次fit试探，提速实时生成
        self._cached_version: Optional[int] = None

    def encode_file(self, filepath: str, transfer_id: Optional[str] = None) -> EncodeResult:
        """
        编码文件为QR帧序列（仅切片+预编码帧数据，不生成QR图像）

        图像在展示时通过 make_qr() 实时生成，避免大量QR图像
        驻留内存导致的大文件发送卡顿。

        Args:
            filepath: 文件路径
            transfer_id: 传输ID（不指定则自动生成）

        Returns:
            EncodeResult 编码结果
        """
        if transfer_id is None:
            transfer_id = uuid.uuid4().hex[:12]

        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size

        # 流式读取 + 分块 + 预编码（边读边算MD5，chunk原始字节用完即弃）
        md5_hasher = hashlib.md5()
        data_entries: List[QREntry] = []

        with open(filepath, "rb") as f:
            idx = 0
            while True:
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break
                md5_hasher.update(chunk)
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
                    QREntry(frame_data=data_frame.encode(), chunk_index=idx)
                )
                idx += 1

        file_md5 = md5_hasher.hexdigest()

        # 生成META帧
        meta_frame = MetaFrame(
            transfer_id=transfer_id,
            filename=filename,
            file_size=file_size,
            total_chunks=total_chunks,
            chunk_size=self.chunk_size,
            file_md5=file_md5,
        )
        meta_entry = QREntry(frame_data=meta_frame.encode(), chunk_index=-1)

        # 生成END帧
        end_frame = EndFrame(
            transfer_id=transfer_id,
            total_chunks=total_chunks,
            file_md5=file_md5,
        )
        end_entry = QREntry(frame_data=end_frame.encode(), chunk_index=-2)

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
        )

    def make_qr(self, frame_data: str) -> Image.Image:
        """按需生成QR码图像（发送展示时实时调用）"""
        return self._make_qr(frame_data)

    def _make_qr(self, data: str) -> Image.Image:
        """生成QR码图像

        性能优化：
        1. 缓存DATA帧的QR版本（数据帧长度一致），避免每次fit试探；
        2. 复用版本时固定mask_pattern=0，跳过惩罚分搜索（QR标准
           允许任意mask，解码器会从格式信息读取mask编号），
           每张生成耗时从~100ms降至~15ms。
        """
        use_cached = self._cached_version is not None and data.startswith("DATA|")
        qr = qrcode.QRCode(
            version=self._cached_version if use_cached else None,
            error_correction=self.error_correction,
            box_size=10,
            border=self.qr_border,
        )
        qr.add_data(data)
        try:
            if use_cached:
                qr.makeImpl(False, 0)
            else:
                qr.make(fit=True)
        except qrcode.exceptions.DataOverflowError:
            # 数据长度超过缓存版本容量时回退自动适配
            qr = qrcode.QRCode(
                version=None,
                error_correction=self.error_correction,
                box_size=10,
                border=self.qr_border,
            )
            qr.add_data(data)
            qr.make(fit=True)
            self._cached_version = qr.version
        else:
            if data.startswith("DATA|") and not use_cached:
                self._cached_version = qr.version

        img = qr.make_image(fill_color="black", back_color="white")
        img = img.convert("RGB")
        # NEAREST缩放：二维码为黑白块状图形，速度最快且保持锐利
        img = img.resize((self.qr_size, self.qr_size), Image.NEAREST)
        return img

    @staticmethod
    def estimate_chunks(filepath: str, chunk_size: int) -> Tuple[int, int]:
        """估算文件需要的chunk数"""
        file_size = os.path.getsize(filepath)
        num_chunks = (file_size + chunk_size - 1) // chunk_size
        return num_chunks, file_size
