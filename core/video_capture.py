"""
视频采集模块：支持摄像头和屏幕捕获两种视频源

- 摄像头: 使用OpenCV读取摄像头
- 屏幕捕获: 使用PySide6的屏幕截图功能
"""

import threading
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image


class CaptureSource(Enum):
    CAMERA = "camera"
    SCREEN = "screen"


class VideoCaptureBase(ABC, threading.Thread):
    """视频采集基类"""

    def __init__(self):
        super().__init__(daemon=True)
        self._running = False
        self._paused = False
        self._frame_interval = 1.0 / 15  # 默认15fps
        self.on_frame: Optional[Callable[[np.ndarray], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    @abstractmethod
    def _grab_frame(self) -> Optional[np.ndarray]:
        """抓取一帧，返回BGR numpy数组"""
        ...

    @abstractmethod
    def get_available_sources(self) -> List[str]:
        """获取可用源列表"""
        ...

    def set_fps(self, fps: float):
        """设置采集帧率"""
        self._frame_interval = 1.0 / max(1, fps)

    def run(self):
        self._running = True
        while self._running:
            if self._paused:
                time.sleep(0.05)
                continue

            loop_start = time.time()
            try:
                frame = self._grab_frame()
                if frame is not None and self.on_frame:
                    self.on_frame(frame)
            except Exception as e:
                if self.on_error:
                    self.on_error(str(e))

            elapsed = time.time() - loop_start
            sleep_time = self._frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop(self):
        self._running = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    @property
    def is_running(self) -> bool:
        return self._running


class CameraCapture(VideoCaptureBase):
    """摄像头采集"""

    def __init__(self, camera_index: int = 0, width: int = 1280, height: int = 720, fps: float = 15):
        super().__init__()
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.set_fps(fps)
        self._cap: Optional[cv2.VideoCapture] = None

    def get_available_sources(self) -> List[str]:
        """扫描可用摄像头"""
        sources = []
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                sources.append(f"摄像头 {i}")
                cap.release()
            else:
                cap.release()
        return sources if sources else ["无可用摄像头"]

    def open(self) -> bool:
        """打开摄像头"""
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self._frame_interval)

        actual_w = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"摄像头已打开: {actual_w}x{actual_h}")
        return True

    def _grab_frame(self) -> Optional[np.ndarray]:
        if self._cap is None or not self._cap.isOpened():
            return None

        ret, frame = self._cap.read()
        if not ret:
            return None
        return frame

    def stop(self):
        super().stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def actual_resolution(self) -> Tuple[int, int]:
        if self._cap is not None:
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            return (w, h)
        return (self.width, self.height)


class ScreenCapture(VideoCaptureBase):
    """屏幕捕获"""

    def __init__(self, monitor_index: int = 0, fps: float = 10):
        super().__init__()
        self.monitor_index = monitor_index
        self.set_fps(fps)
        self._sct = None

    def get_available_sources(self) -> List[str]:
        """获取可用显示器列表"""
        try:
            import mss
            with mss.mss() as sct:
                monitors = sct.monitors
                sources = []
                for i, m in enumerate(monitors):
                    if i == 0:
                        sources.append(f"全部屏幕 ({m['width']}x{m['height']})")
                    else:
                        sources.append(f"显示器 {i} ({m['width']}x{m['height']})")
                return sources
        except ImportError:
            return ["主屏幕 (需要安装 mss 库)"]

    def open(self) -> bool:
        """初始化屏幕捕获"""
        try:
            import mss
            self._sct = mss.mss()
            return True
        except ImportError:
            if self.on_error:
                self.on_error("屏幕捕获需要安装 mss 库: pip install mss")
            return False
        except Exception as e:
            if self.on_error:
                self.on_error(f"屏幕捕获初始化失败: {e}")
            return False

    def _grab_frame(self) -> Optional[np.ndarray]:
        if self._sct is None:
            return None

        try:
            monitor = self._sct.monitors[self.monitor_index]
            screenshot = self._sct.grab(monitor)

            # 转换为numpy数组
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            frame = np.array(img)
            # BGRX -> BGR
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            return frame
        except Exception:
            return None

    def stop(self):
        super().stop()
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


def create_capture(
    source: CaptureSource,
    camera_index: int = 0,
    width: int = 1280,
    height: int = 720,
    fps: float = 15,
    monitor_index: int = 1,
) -> VideoCaptureBase:
    """创建视频采集器"""
    if source == CaptureSource.CAMERA:
        return CameraCapture(camera_index=camera_index, width=width, height=height, fps=fps)
    else:
        return ScreenCapture(monitor_index=monitor_index, fps=fps)
