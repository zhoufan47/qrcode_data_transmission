"""
QR码解码器：从视频帧中解码QR码并重组文件
"""

import base64
import io
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Set

from PIL import Image

from .protocol import ParsedFrame, FrameType, MetaFrame, DataFrame, EndFrame, compute_md5


@dataclass
class TransferProgress:
    """单个传输任务的进度"""
    transfer_id: str
    filename: str
    file_size: int
    total_chunks: int
    chunk_size: int
    file_md5: str
    received_chunks: Dict[int, bytes] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    is_complete: bool = False
    is_verified: bool = False
    meta_received: bool = False
    end_received: bool = False

    @property
    def received_count(self) -> int:
        return len(self.received_chunks)

    @property
    def progress_pct(self) -> float:
        if self.total_chunks == 0:
            return 0.0
        return len(self.received_chunks) / self.total_chunks * 100

    @property
    def missing_chunks(self) -> Set[int]:
        return set(range(self.total_chunks)) - set(self.received_chunks.keys())

    @property
    def elapsed_seconds(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def transfer_rate(self) -> float:
        """传输速率 (bytes/sec)"""
        elapsed = self.elapsed_seconds
        if elapsed == 0:
            return 0.0
        received_bytes = len(self.received_chunks) * self.chunk_size
        return received_bytes / elapsed


class QRDecoder:
    """
    QR码解码器

    负责:
    1. 从图像中提取QR码文本
    2. 解析帧协议
    3. 管理多个传输任务的状态
    4. 重组文件
    """

    def __init__(self, output_dir: str = "."):
        self.output_dir = output_dir
        self.transfers: Dict[str, TransferProgress] = {}
        self._lock = threading.Lock()

        # 孤儿DATA帧缓存：DATA早于META到达时暂存，META到达后重放
        self._orphan_data: Dict[str, list] = {}

        # 回调
        self.on_progress: Optional[Callable[[str, TransferProgress], None]] = None
        self.on_complete: Optional[Callable[[str, TransferProgress, str], None]] = None
        self.on_new_transfer: Optional[Callable[[str, TransferProgress], None]] = None
        self.on_error: Optional[Callable[[str, str], None]] = None

    def decode_image(self, image: Image.Image) -> Optional[str]:
        """从PIL图像解码QR码文本"""
        try:
            from pyzbar.pyzbar import decode as zbar_decode

            # 转换为numpy数组
            img_array = image.convert("L")  # 灰度

            results = zbar_decode(img_array)
            if results:
                for result in results:
                    text = result.data.decode("utf-8", errors="ignore").strip()
                    if text:
                        return text
        except Exception:
            pass
        return None

    def decode_opencv_frame(self, frame) -> Optional[str]:
        """从OpenCV帧(BGR numpy数组)解码QR码文本"""
        try:
            from pyzbar.pyzbar import decode as zbar_decode
            import numpy as np

            # 确保是灰度图
            if len(frame.shape) == 3:
                gray = frame  # pyzbar可以直接处理BGR
            else:
                gray = frame

            results = zbar_decode(gray)
            if results:
                for result in results:
                    text = result.data.decode("utf-8", errors="ignore").strip()
                    if text:
                        return text
        except Exception:
            pass
        return None

    def process_frame_data(self, raw_text: str) -> Optional[str]:
        """
        处理解码后的原始文本

        Returns:
            传输ID（如果成功处理），否则None
        """
        parsed = ParsedFrame.parse(raw_text)
        if parsed is None:
            return None

        if parsed.frame_type == FrameType.META and parsed.meta:
            return self._handle_meta(parsed.meta)
        elif parsed.frame_type == FrameType.DATA and parsed.data:
            return self._handle_data(parsed.data)
        elif parsed.frame_type == FrameType.END and parsed.end:
            return self._handle_end(parsed.end)

        return None

    def _handle_meta(self, meta: MetaFrame) -> str:
        """处理META帧"""
        with self._lock:
            if meta.transfer_id in self.transfers:
                # 已存在的传输，可能重复的META帧
                return meta.transfer_id
            
            progress = TransferProgress(
                transfer_id=meta.transfer_id,
                filename=meta.filename,
                file_size=meta.file_size,
                total_chunks=meta.total_chunks,
                chunk_size=meta.chunk_size,
                file_md5=meta.file_md5,
                meta_received=True,
                start_time=time.time(),
            )
            self.transfers[meta.transfer_id] = progress
            
            # 取出早于META到达的孤儿DATA帧，稍后重放
            orphans = self._orphan_data.pop(meta.transfer_id, [])

        if self.on_new_transfer:
            self.on_new_transfer(meta.transfer_id, progress)

        # 重放孤儿DATA帧
        for orphan in orphans:
            self._handle_data(orphan)

        return meta.transfer_id

    def _handle_data(self, data: DataFrame) -> Optional[str]:
        """处理DATA帧"""
        tid = data.transfer_id

        with self._lock:
            if tid not in self.transfers:
                # META尚未到达：暂存该DATA帧，等META到达后自动重放
                orphans = self._orphan_data.setdefault(tid, [])
                if len(orphans) < 2000:
                    orphans.append(data)
                return None

            progress = self.transfers[tid]

            # 跳过已接收的chunk
            if data.chunk_index in progress.received_chunks:
                return tid

            # 验证MD5
            try:
                chunk_data = base64.b64decode(data.data_base64)
            except Exception:
                if self.on_error:
                    self.on_error(tid, f"Base64解码失败: chunk {data.chunk_index}")
                return tid

            from .protocol import verify_chunk_md5
            if not verify_chunk_md5(chunk_data, data.chunk_md5):
                if self.on_error:
                    self.on_error(tid, f"MD5校验失败: chunk {data.chunk_index}")
                return tid

            progress.received_chunks[data.chunk_index] = chunk_data

        if self.on_progress:
            self.on_progress(tid, progress)

        # 检查是否所有chunk都已收到
        if progress.received_count == progress.total_chunks:
            self._try_complete_transfer(tid)

        return tid

    def _handle_end(self, end: EndFrame) -> Optional[str]:
        """处理END帧"""
        tid = end.transfer_id

        with self._lock:
            if tid not in self.transfers:
                return None

            progress = self.transfers[tid]
            progress.end_received = True

        # 尝试完成传输
        self._try_complete_transfer(tid)
        return tid

    def _try_complete_transfer(self, tid: str):
        """尝试完成传输（所有chunk已收到）"""
        with self._lock:
            progress = self.transfers.get(tid)
            if progress is None or progress.is_complete:
                return

            if progress.received_count < progress.total_chunks:
                return

            # 重组文件
            output_path = self._assemble_file(progress)
            if output_path:
                progress.is_complete = True
                progress.is_verified = True
                progress.end_time = time.time()

        if progress.is_complete and self.on_complete:
            self.on_complete(tid, progress, output_path)

    def _assemble_file(self, progress: TransferProgress) -> Optional[str]:
        """重组文件"""
        try:
            # 按chunk_index排序并拼接
            sorted_chunks = [
                progress.received_chunks[i]
                for i in range(progress.total_chunks)
            ]
            file_data = b"".join(sorted_chunks)

            # 验证整体文件MD5
            actual_md5 = compute_md5(file_data)
            if actual_md5 != progress.file_md5:
                if self.on_error:
                    self.on_error(
                        progress.transfer_id,
                        f"文件MD5校验失败: 期望={progress.file_md5}, 实际={actual_md5}",
                    )
                return None

            # 处理文件名冲突
            output_filename = progress.filename
            output_path = os.path.join(self.output_dir, output_filename)

            counter = 1
            while os.path.exists(output_path):
                name, ext = os.path.splitext(output_filename)
                output_path = os.path.join(self.output_dir, f"{name}_{counter}{ext}")
                counter += 1

            # 写入文件
            with open(output_path, "wb") as f:
                f.write(file_data)

            return output_path

        except Exception as e:
            if self.on_error:
                self.on_error(progress.transfer_id, f"文件组装失败: {str(e)}")
            return None

    def get_transfer(self, transfer_id: str) -> Optional[TransferProgress]:
        with self._lock:
            return self.transfers.get(transfer_id)

    def get_all_transfers(self) -> Dict[str, TransferProgress]:
        with self._lock:
            return dict(self.transfers)

    def reset(self):
        with self._lock:
            self.transfers.clear()
            self._orphan_data.clear()
