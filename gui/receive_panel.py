"""
接收面板：视频源管理、QR码解码、传输进度监控
"""

import os
import time
import uuid
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QImage, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QSpinBox, QDoubleSpinBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QSplitter, QFrame, QSizePolicy, QMessageBox,
)

from core.decoder import QRDecoder, TransferProgress
from core.video_capture import (
    CameraCapture, ScreenCapture, VideoCaptureBase, CaptureSource,
)
from utils.config import ConfigManager


class ReceivePanel(QWidget):
    """文件接收面板"""

    # 信号
    receive_started = Signal(str, str)   # task_id, filename
    receive_completed = Signal(str, str, str, float, float)  # task_id, filename, output_path, elapsed, rate

    def __init__(self, config_manager: ConfigManager, task_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.config = config_manager.get()
        self.task_manager = task_manager

        # 采集设备
        self.capture: Optional[VideoCaptureBase] = None
        self.is_capturing: bool = False

        # 解码器
        self.output_dir = self.config.output_dir or os.path.expanduser("~/Downloads/qrcode_received")
        os.makedirs(self.output_dir, exist_ok=True)
        self.decoder = QRDecoder(output_dir=self.output_dir)

        # 当前任务
        self.current_task_id: Optional[str] = None

        # 帧缓存（去重用）
        self._last_decoded_texts: set = set()
        self._dedup_timer = 0

        # 显示帧率控制
        self.display_timer: Optional[QTimer] = None
        self.display_fps = 15

        self._init_ui()
        self._setup_decoder_callbacks()

    def _init_ui(self):
        layout = QHBoxLayout(self)

        # === 左侧控制面板 ===
        left_panel = QVBoxLayout()

        # 视频源设置
        source_group = QGroupBox("视频源设置")
        source_layout = QVBoxLayout()

        # 源类型选择
        row_src = QHBoxLayout()
        row_src.addWidget(QLabel("采集源:"))
        self.cmb_source = QComboBox()
        self.cmb_source.addItem("摄像头", "camera")
        self.cmb_source.addItem("屏幕捕获", "screen")
        self.cmb_source.setCurrentIndex(0 if self.config.capture_source == "camera" else 1)
        self.cmb_source.currentIndexChanged.connect(self._on_source_changed)
        row_src.addWidget(self.cmb_source)
        source_layout.addLayout(row_src)

        # 摄像头选择
        row_cam = QHBoxLayout()
        row_cam.addWidget(QLabel("摄像头:"))
        self.cmb_camera = QComboBox()
        self._scan_cameras()
        self.cmb_camera.setCurrentIndex(self.config.camera_index)
        row_cam.addWidget(self.cmb_camera)
        source_layout.addLayout(row_cam)

        # 分辨率设置
        row_res = QHBoxLayout()
        row_res.addWidget(QLabel("分辨率:"))
        self.spin_width = QSpinBox()
        self.spin_width.setRange(320, 3840)
        self.spin_width.setValue(self.config.camera_width)
        self.spin_width.setSingleStep(160)
        row_res.addWidget(self.spin_width)
        row_res.addWidget(QLabel("×"))
        self.spin_height = QSpinBox()
        self.spin_height.setRange(240, 2160)
        self.spin_height.setValue(self.config.camera_height)
        self.spin_height.setSingleStep(120)
        row_res.addWidget(self.spin_height)
        source_layout.addLayout(row_res)

        # 捕获帧率
        row_fps = QHBoxLayout()
        row_fps.addWidget(QLabel("捕获帧率:"))
        self.spin_capture_fps = QDoubleSpinBox()
        self.spin_capture_fps.setRange(1, 60)
        self.spin_capture_fps.setValue(self.config.capture_fps)
        self.spin_capture_fps.setSingleStep(5)
        row_fps.addWidget(self.spin_capture_fps)
        row_fps.addWidget(QLabel("fps"))
        source_layout.addLayout(row_fps)

        # 显示器选择(屏幕模式)
        row_mon = QHBoxLayout()
        row_mon.addWidget(QLabel("显示器:"))
        self.cmb_monitor = QComboBox()
        self.cmb_monitor.addItem("主显示器")
        self.cmb_monitor.setCurrentIndex(0)
        row_mon.addWidget(self.cmb_monitor)
        self._monitor_row = row_mon
        self._set_monitor_visible(False)
        source_layout.addLayout(row_mon)

        # 刷新按钮
        self.btn_refresh = QPushButton("刷新设备列表")
        self.btn_refresh.clicked.connect(self._refresh_devices)
        source_layout.addWidget(self.btn_refresh)

        # 采集控制按钮
        btn_capture_row = QHBoxLayout()
        self.btn_start_capture = QPushButton("▶ 开始采集")
        self.btn_start_capture.clicked.connect(self._start_capture)
        self.btn_start_capture.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }"
        )
        self.btn_stop_capture = QPushButton("■ 停止采集")
        self.btn_stop_capture.clicked.connect(self._stop_capture)
        self.btn_stop_capture.setEnabled(False)
        self.btn_stop_capture.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 8px; }"
        )
        btn_capture_row.addWidget(self.btn_start_capture)
        btn_capture_row.addWidget(self.btn_stop_capture)
        source_layout.addLayout(btn_capture_row)

        source_group.setLayout(source_layout)
        left_panel.addWidget(source_group)

        # 传输状态组
        status_group = QGroupBox("传输状态")
        status_layout = QVBoxLayout()

        self.lbl_current_file = QLabel("当前文件: 等待接收...")
        self.lbl_current_file.setWordWrap(True)
        status_layout.addWidget(self.lbl_current_file)

        self.lbl_file_size = QLabel("文件大小: -")
        status_layout.addWidget(self.lbl_file_size)

        self.lbl_chunks = QLabel("分块: 0 / 0")
        status_layout.addWidget(self.lbl_chunks)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        status_layout.addWidget(self.progress_bar)

        self.lbl_rate = QLabel("速率: -")
        status_layout.addWidget(self.lbl_rate)

        self.lbl_elapsed = QLabel("已用时间: -")
        status_layout.addWidget(self.lbl_elapsed)

        self.lbl_status = QLabel("状态: 等待开始")
        status_layout.addWidget(self.lbl_status)

        status_group.setLayout(status_layout)
        left_panel.addWidget(status_group)

        # 输出目录设置
        output_group = QGroupBox("输出设置")
        output_layout = QHBoxLayout()
        self.lbl_output_dir = QLabel(self.output_dir)
        self.lbl_output_dir.setWordWrap(True)
        output_layout.addWidget(self.lbl_output_dir)
        self.btn_output_dir = QPushButton("更改")
        self.btn_output_dir.clicked.connect(self._change_output_dir)
        output_layout.addWidget(self.btn_output_dir)
        output_group.setLayout(output_layout)
        left_panel.addWidget(output_group)

        left_panel.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setMaximumWidth(380)

        # === 右侧视频预览 ===
        right_panel = QVBoxLayout()

        preview_group = QGroupBox("视频预览")
        preview_layout = QVBoxLayout()

        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(480, 360)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_label.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333; border-radius: 4px;")
        self.video_label.setText("等待启动采集...")
        preview_layout.addWidget(self.video_label)

        preview_group.setLayout(preview_layout)
        right_panel.addWidget(preview_group)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)

        # 分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    # ========== 设备管理 ==========

    def _scan_cameras(self):
        """扫描可用摄像头"""
        self.cmb_camera.clear()
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                self.cmb_camera.addItem(f"摄像头 {i}", i)
                cap.release()
            else:
                cap.release()
        if self.cmb_camera.count() == 0:
            self.cmb_camera.addItem("无可用摄像头", -1)

    def _refresh_devices(self):
        self._scan_cameras()

    def _on_source_changed(self, index):
        source = self.cmb_source.currentData()
        is_camera = source == "camera"
        self._set_monitor_visible(not is_camera)
        self.config_manager.update(capture_source=source)

    def _set_monitor_visible(self, visible: bool):
        """设置显示器选择行可见性"""
        # 隐藏/显示monitor行的所有widget
        for i in range(self._monitor_row.count()):
            w = self._monitor_row.itemAt(i).widget()
            if w:
                w.setVisible(visible)

    # ========== 采集控制 ==========

    def _start_capture(self):
        """开始采集"""
        source = self.cmb_source.currentData()

        if source == "camera":
            camera_idx = self.cmb_camera.currentData()
            if camera_idx is None or camera_idx < 0:
                QMessageBox.warning(self, "错误", "没有可用的摄像头")
                return

            self.capture = CameraCapture(
                camera_index=camera_idx,
                width=self.spin_width.value(),
                height=self.spin_height.value(),
                fps=self.spin_capture_fps.value(),
            )
        else:
            self.capture = ScreenCapture(
                monitor_index=self.cmb_monitor.currentIndex() + 1,
                fps=self.spin_capture_fps.value(),
            )

        self.capture.on_frame = self._on_frame_received
        self.capture.on_error = self._on_capture_error

        if not self.capture.open():
            QMessageBox.warning(self, "错误", f"无法打开 {'摄像头' if source == 'camera' else '屏幕捕获'}")
            self.capture = None
            return

        self.capture.start()
        self.is_capturing = True

        # 更新UI
        self.btn_start_capture.setEnabled(False)
        self.btn_stop_capture.setEnabled(True)
        self.cmb_source.setEnabled(False)
        self.cmb_camera.setEnabled(False)

        # 启动显示定时器
        self.display_timer = QTimer(self)
        self.display_timer.timeout.connect(self._update_display)
        self.display_timer.start(int(1000 / self.display_fps))

        self.lbl_status.setText("状态: 采集中...")

        # 重置分辨率显示标记
        self._frame_res_shown = False

        # 重置解码器
        self.decoder.reset()
        self._last_decoded_texts.clear()

    def _stop_capture(self):
        """停止采集"""
        self.is_capturing = False

        if self.capture:
            self.capture.stop()
            self.capture = None

        if self.display_timer:
            self.display_timer.stop()
            self.display_timer = None

        # 更新UI
        self.btn_start_capture.setEnabled(True)
        self.btn_stop_capture.setEnabled(False)
        self.cmb_source.setEnabled(True)
        self.cmb_camera.setEnabled(True)

        self.video_label.clear()
        self.video_label.setText("等待启动采集...")
        self.lbl_status.setText("状态: 已停止")
        self.lbl_current_file.setText("当前文件: 等待接收...")

        # 保存配置
        self.config_manager.update(
            camera_index=self.cmb_camera.currentData() or 0,
            camera_width=self.spin_width.value(),
            camera_height=self.spin_height.value(),
            capture_fps=self.spin_capture_fps.value(),
        )

    def _change_output_dir(self):
        from PySide6.QtWidgets import QFileDialog
        new_dir = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir)
        if new_dir:
            self.output_dir = new_dir
            self.lbl_output_dir.setText(new_dir)
            self.decoder.output_dir = new_dir
            self.config_manager.update(output_dir=new_dir)

    # ========== 帧处理 ==========

    # 缓存最近一帧用于显示
    _latest_frame: Optional[np.ndarray] = None

    def _on_frame_received(self, frame: np.ndarray):
        """收到新帧"""
        self._latest_frame = frame

        # 解码QR码
        text = self.decoder.decode_opencv_frame(frame)
        if text:
            # 去重：同一文本短时间内不重复处理
            if text in self._last_decoded_texts:
                return
            self._last_decoded_texts.add(text)
            if len(self._last_decoded_texts) > 50:
                self._last_decoded_texts.clear()

            tid = self.decoder.process_frame_data(text)
            if tid is None and text.startswith("DATA|"):
                # DATA先于META到达，已暂存等待META重放
                print(f"[接收] DATA帧已解出但META未到达，已暂存: {text[:40]}...")

    def _on_capture_error(self, error_msg: str):
        print(f"采集错误: {error_msg}")

    def _update_display(self):
        """更新视频预览显示"""
        if self._latest_frame is None:
            return

        frame = self._latest_frame.copy()

        # 首帧时记录实际接收分辨率（解码用原图，仅预览缩放）
        if not getattr(self, "_frame_res_shown", False):
            self._frame_res_shown = True
            src_h, src_w = frame.shape[:2]
            print(f"实际接收帧分辨率: {src_w}x{src_h}（预览按比例缩放显示，解码使用原图）")
            self.lbl_status.setText(f"状态: 采集中... (实际采集 {src_w}x{src_h})")

        # 绘制QR码检测框（如果有）
        try:
            from pyzbar.pyzbar import decode as zbar_decode
            results = zbar_decode(frame)
            for result in results:
                x, y, w, h = result.rect
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        except Exception:
            pass

        # 缩放以适应显示
        h, w = frame.shape[:2]
        display_w = self.video_label.width()
        display_h = self.video_label.height()
        scale = min(display_w / w, display_h / h, 1.0)
        new_w, new_h = int(w * scale), int(h * scale)
        # 缩小时用INTER_AREA重采样，预览更清晰
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        frame = cv2.resize(frame, (new_w, new_h), interpolation=interp)

        # 转换为QPixmap
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimage = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage)
        self.video_label.setPixmap(pixmap)

    # ========== 解码器回调 ==========

    def _setup_decoder_callbacks(self):
        self.decoder.on_new_transfer = self._on_new_transfer
        self.decoder.on_progress = self._on_progress
        self.decoder.on_complete = self._on_complete
        self.decoder.on_error = self._on_decode_error

    def _on_new_transfer(self, transfer_id: str, progress: TransferProgress):
        """新传输开始"""
        self.current_task_id = uuid.uuid4().hex[:12]

        # 创建任务记录
        if self.task_manager:
            self.task_manager.create_receive_task(
                task_id=self.current_task_id,
                transfer_id=transfer_id,
                filename=progress.filename,
                file_size=progress.file_size,
                total_chunks=progress.total_chunks,
            )

        self.lbl_current_file.setText(f"当前文件: {progress.filename}")
        self.lbl_file_size.setText(f"文件大小: {self._format_size(progress.file_size)}")
        self.lbl_chunks.setText(f"分块: 0 / {progress.total_chunks}")
        self.progress_bar.setRange(0, progress.total_chunks)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("状态: 接收中...")

        self.receive_started.emit(self.current_task_id, progress.filename)

    def _on_progress(self, transfer_id: str, progress: TransferProgress):
        """进度更新"""
        self.progress_bar.setValue(progress.received_count)
        self.lbl_chunks.setText(f"分块: {progress.received_count} / {progress.total_chunks}")
        self.lbl_rate.setText(f"速率: {self._format_rate(progress.transfer_rate)}")
        self.lbl_elapsed.setText(f"已用时间: {self._format_elapsed(progress.elapsed_seconds)}")
        self.lbl_status.setText(
            f"状态: 接收中... ({progress.received_count}/{progress.total_chunks})"
        )

        # 更新任务管理器
        if self.task_manager and self.current_task_id:
            self.task_manager.update_progress(self.current_task_id, progress.received_count)

    def _on_complete(self, transfer_id: str, progress: TransferProgress, output_path: str):
        """传输完成"""
        elapsed = progress.elapsed_seconds
        rate = progress.transfer_rate

        self.lbl_status.setText(f"状态: 接收完成 ✓")
        self.lbl_rate.setText(f"速率: {self._format_rate(rate)}")
        self.lbl_elapsed.setText(f"总耗时: {self._format_elapsed(elapsed)}")

        # 更新任务管理器
        if self.task_manager and self.current_task_id:
            self.task_manager.mark_completed(
                task_id=self.current_task_id,
                elapsed=elapsed,
                rate=rate,
                output_path=output_path,
            )

        self.receive_completed.emit(
            self.current_task_id or "",
            progress.filename,
            output_path,
            elapsed,
            rate,
        )

        QMessageBox.information(
            self,
            "接收完成",
            f"文件接收完成！\n\n"
            f"文件名: {progress.filename}\n"
            f"大小: {self._format_size(progress.file_size)}\n"
            f"耗时: {self._format_elapsed(elapsed)}\n"
            f"速率: {self._format_rate(rate)}\n"
            f"保存至: {output_path}",
        )

        # 准备接收下一个文件
        self.lbl_current_file.setText("当前文件: 等待下一个...")

    def _on_decode_error(self, transfer_id: str, error_msg: str):
        """解码错误"""
        print(f"[解码错误] {transfer_id}: {error_msg}")

        if self.task_manager and self.current_task_id:
            self.task_manager.mark_failed(self.current_task_id, error_msg)

    # ========== 辅助方法 ==========

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _format_rate(rate: float) -> str:
        if rate < 1024:
            return f"{rate:.0f} B/s"
        elif rate < 1024 * 1024:
            return f"{rate / 1024:.1f} KB/s"
        else:
            return f"{rate / (1024 * 1024):.2f} MB/s"

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"
