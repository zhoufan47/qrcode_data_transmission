"""
发送面板：文件选择、队列管理、QR码显示与设置
"""

import os
import queue
import random
import threading
import time
import uuid
from typing import List, Optional, Set

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QPixmap, QImage, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QGroupBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QFileDialog, QProgressBar, QSplitter, QFrame,
    QMessageBox, QSizePolicy, QComboBox,
)

from PIL import Image

from core.encoder import FileEncoder, EncodeResult, QREntry
from utils.config import ConfigManager


class SendPanel(QWidget):
    """文件发送面板"""

    # 信号：通知主窗口文件发送完成
    send_completed = Signal(str, str)  # task_id, filename

    def __init__(self, config_manager: ConfigManager, task_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.config = config_manager.get()
        self.task_manager = task_manager

        # 发送队列
        self.queue: List[EncodeResult] = []
        self.current_encode: Optional[EncodeResult] = None
        self.current_encoder: Optional[FileEncoder] = None
        self.current_qr_index: int = 0
        self.shuffled_playlist: List[QREntry] = []
        self.shown_chunks: Set[int] = set()
        self.is_sending: bool = False
        self.send_timer: Optional[QTimer] = None
        self.send_thread: Optional[threading.Thread] = None

        # QR图像后台实时生成
        self.qr_gen_thread: Optional[threading.Thread] = None
        self._gen_running: bool = False
        self.gen_queue: Optional[queue.Queue] = None    # 待生成批次
        self.ready_queue: Optional[queue.Queue] = None  # 已生成批次
        self.batch_counter: int = 0

        # 任务跟踪
        self.current_task_id: Optional[str] = None
        self.current_transfer_id: Optional[str] = None

        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)

        # === 左侧控制面板 ===
        left_panel = QVBoxLayout()

        # 文件队列组
        queue_group = QGroupBox("发送队列")
        queue_layout = QVBoxLayout()

        # 队列列表
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(150)
        self.queue_list.setAlternatingRowColors(True)
        queue_layout.addWidget(self.queue_list)

        # 队列操作按钮
        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加文件")
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_remove_file = QPushButton("移除选中")
        self.btn_remove_file.clicked.connect(self._remove_selected)
        self.btn_clear_queue = QPushButton("清空队列")
        self.btn_clear_queue.clicked.connect(self._clear_queue)
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_remove_file)
        btn_row.addWidget(self.btn_clear_queue)
        queue_layout.addLayout(btn_row)

        queue_group.setLayout(queue_layout)
        left_panel.addWidget(queue_group)

        # 发送控制组
        send_group = QGroupBox("发送控制")
        send_layout = QVBoxLayout()

        # 当前文件信息
        self.lbl_current_file = QLabel("当前文件: 无")
        self.lbl_current_file.setWordWrap(True)
        send_layout.addWidget(self.lbl_current_file)

        # 进度
        progress_row = QHBoxLayout()
        progress_row.addWidget(QLabel("进度:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_row.addWidget(self.progress_bar)
        send_layout.addLayout(progress_row)

        self.lbl_progress_detail = QLabel("0 / 0 帧已发送")
        send_layout.addWidget(self.lbl_progress_detail)

        # 发送按钮
        btn_send_row = QHBoxLayout()
        self.btn_start_send = QPushButton("▶ 开始发送")
        self.btn_start_send.clicked.connect(self._start_sending)
        self.btn_start_send.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }"
        )
        self.btn_next_file = QPushButton("✓ 确认接收完成，发下一个")
        self.btn_next_file.clicked.connect(self._confirm_next)
        self.btn_next_file.setEnabled(False)
        self.btn_next_file.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 8px; }"
        )
        self.btn_stop_send = QPushButton("■ 停止发送")
        self.btn_stop_send.clicked.connect(self._stop_sending)
        self.btn_stop_send.setEnabled(False)
        self.btn_stop_send.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 8px; }"
        )
        btn_send_row.addWidget(self.btn_start_send)
        btn_send_row.addWidget(self.btn_next_file)
        btn_send_row.addWidget(self.btn_stop_send)
        send_layout.addLayout(btn_send_row)

        send_group.setLayout(send_layout)
        left_panel.addWidget(send_group)

        # 发送设置组
        settings_group = QGroupBox("发送设置")
        settings_layout = QVBoxLayout()

        # 帧率设置
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("QR帧率 (fps):"))
        self.spin_fps = QDoubleSpinBox()
        self.spin_fps.setRange(1, 30)
        self.spin_fps.setValue(self.config.send_fps)
        self.spin_fps.setSingleStep(1)
        self.spin_fps.valueChanged.connect(self._on_fps_changed)
        row1.addWidget(self.spin_fps)
        settings_layout.addLayout(row1)

        # QR尺寸设置
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("QR尺寸 (px):"))
        self.spin_qr_size = QSpinBox()
        self.spin_qr_size.setRange(200, 1200)
        self.spin_qr_size.setValue(self.config.qr_size)
        self.spin_qr_size.setSingleStep(50)
        self.spin_qr_size.valueChanged.connect(self._on_qr_size_changed)
        row2.addWidget(self.spin_qr_size)
        settings_layout.addLayout(row2)

        # 块大小设置
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("数据块大小 (bytes):"))
        self.spin_chunk_size = QSpinBox()
        self.spin_chunk_size.setRange(256, 4096)
        self.spin_chunk_size.setValue(self.config.chunk_size)
        self.spin_chunk_size.setSingleStep(256)
        self.spin_chunk_size.valueChanged.connect(self._on_chunk_size_changed)
        row3.addWidget(self.spin_chunk_size)
        settings_layout.addLayout(row3)

        # 乱序发送
        self.chk_shuffle = QCheckBox("乱序发送 (提升传输速率)")
        self.chk_shuffle.setChecked(self.config.shuffle_enabled)
        self.chk_shuffle.toggled.connect(self._on_shuffle_changed)
        settings_layout.addWidget(self.chk_shuffle)

        # 同显QR数量设置
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("同显QR数量:"))
        self.combo_qr_count = QComboBox()
        self.combo_qr_count.addItems(["1", "2", "4", "6"])
        self.combo_qr_count.setCurrentText(str(self.config.qr_display_count))
        self.combo_qr_count.currentTextChanged.connect(self._on_display_count_changed)
        row4.addWidget(self.combo_qr_count)
        row4.addWidget(QLabel("张"))
        row4.addStretch()
        settings_layout.addLayout(row4)

        settings_group.setLayout(settings_layout)
        left_panel.addWidget(settings_group)

        left_panel.addStretch()

        # 左侧容器
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setMaximumWidth(380)

        # === 右侧QR码显示 ===
        right_panel = QVBoxLayout()

        qr_display_group = QGroupBox("QR码预览")
        qr_display_layout = QVBoxLayout()

        # 网格布局：支持 1/2/4/6 张QR码同时显示
        self.qr_grid = QGridLayout()
        self.qr_grid.setSpacing(6)
        self.qr_labels: List[QLabel] = []
        for i in range(6):
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumSize(180, 180)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            label.setStyleSheet(
                "background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 4px;"
            )
            label.setText("等待发送文件...")
            self.qr_labels.append(label)
            row, col = divmod(i, 2)
            self.qr_grid.addWidget(label, row, col)
        for c in range(2):
            self.qr_grid.setColumnStretch(c, 1)
        for r in range(3):
            self.qr_grid.setRowStretch(r, 1)
        qr_display_layout.addLayout(self.qr_grid)
        self._update_qr_grid(self.config.qr_display_count)

        self.lbl_qr_info = QLabel("")
        self.lbl_qr_info.setAlignment(Qt.AlignCenter)
        qr_display_layout.addWidget(self.lbl_qr_info)

        qr_display_group.setLayout(qr_display_layout)
        right_panel.addWidget(qr_display_group)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)

        # 分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    # ========== 事件处理 ==========

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要发送的文件", "", "所有文件 (*.*)"
        )
        if not files:
            return

        for filepath in files:
            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath)

            # 添加到列表
            item_text = f"{filename}  ({self._format_size(file_size)})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, filepath)
            self.queue_list.addItem(item)

    def _remove_selected(self):
        for item in self.queue_list.selectedItems():
            row = self.queue_list.row(item)
            self.queue_list.takeItem(row)

    def _clear_queue(self):
        if self.is_sending:
            self._stop_sending()
        self.queue_list.clear()
        self.queue.clear()

    def _on_fps_changed(self, value):
        self.config_manager.update(send_fps=value)
        if self.send_timer:
            self.send_timer.setInterval(int(1000 / value))

    def _on_qr_size_changed(self, value):
        self.config_manager.update(qr_size=value)

    def _on_chunk_size_changed(self, value):
        self.config_manager.update(chunk_size=value)

    def _on_shuffle_changed(self, checked):
        self.config_manager.update(shuffle_enabled=checked)

    def _on_display_count_changed(self, text: str):
        """同显QR数量变更"""
        count = int(text)
        self.config_manager.update(qr_display_count=count)
        self._update_qr_grid(count)

    def _update_qr_grid(self, count: int):
        """更新网格显示数量"""
        for i, label in enumerate(self.qr_labels):
            label.setVisible(i < count)

    def _clear_qr_labels(self, text: str = "等待发送文件..."):
        """清空所有QR显示label"""
        for label in self.qr_labels:
            label.clear()
            label.setText(text)
        self._update_qr_grid(self.config.qr_display_count)

    # ========== 发送逻辑 ==========

    def _encode_queue_files(self) -> bool:
        """编码队列中的所有文件（仅切片+预编码帧数据，不生成QR图像）"""
        self.queue.clear()
        self.current_encoder = FileEncoder(
            chunk_size=self.config.chunk_size,
            qr_size=self.config.qr_size,
            qr_border=self.config.qr_border,
            shuffle=self.config.shuffle_enabled,
        )

        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            filepath = item.data(Qt.UserRole)
            transfer_id = uuid.uuid4().hex[:12]

            try:
                result = self.current_encoder.encode_file(filepath, transfer_id=transfer_id)
                self.queue.append(result)
            except Exception as e:
                QMessageBox.warning(self, "编码失败", f"文件 {os.path.basename(filepath)} 编码失败:\n{str(e)}")
                return False

        return len(self.queue) > 0

    def _start_sending(self):
        """开始发送队列"""
        if self.queue_list.count() == 0:
            QMessageBox.information(self, "提示", "请先添加文件到发送队列")
            return

        # 编码文件
        if not self._encode_queue_files():
            return

        # 禁用文件操作
        self.btn_add_files.setEnabled(False)
        self.btn_remove_file.setEnabled(False)
        self.btn_clear_queue.setEnabled(False)
        self.btn_start_send.setEnabled(False)
        self.btn_stop_send.setEnabled(True)

        # 开始发送第一个文件
        self.is_sending = True
        self._send_next_file()

    def _send_next_file(self):
        """发送队列中的下一个文件"""
        if not self.queue:
            self._on_queue_complete()
            return

        self.current_encode = self.queue.pop(0)
        self.current_qr_index = 0
        self.shown_chunks.clear()
        self.current_transfer_id = self.current_encode.transfer_id
        self.current_task_id = uuid.uuid4().hex[:12]

        # 更新UI
        self.lbl_current_file.setText(
            f"当前文件: {self.current_encode.filename}\n"
            f"大小: {self._format_size(self.current_encode.file_size)}, "
            f"分块: {self.current_encode.total_chunks}"
        )
        self.progress_bar.setRange(0, self.current_encode.total_chunks)
        self.progress_bar.setValue(0)

        # 构建乱序播放列表
        if self.config.shuffle_enabled:
            self.shuffled_playlist = self._build_dynamic_shuffled_playlist()
        else:
            # 顺序模式同样周期性重发META，避免接收方漏掉首个META后永远卡住
            playlist: List[QREntry] = []
            data_entries = list(self.current_encode.data_entries)
            rounds = max(3, min(8, 200 // max(len(data_entries), 1) + 2))
            for _ in range(rounds):
                playlist.append(self.current_encode.meta_entry)
                playlist.extend(data_entries)
            playlist.append(self.current_encode.end_entry)
            self.shuffled_playlist = playlist

        # 移除队列列表中的第一项
        if self.queue_list.count() > 0:
            self.queue_list.takeItem(0)

        # 从任务管理创建
        if self.task_manager:
            self.task_manager.create_send_task(
                task_id=self.current_task_id,
                transfer_id=self.current_transfer_id,
                filename=self.current_encode.filename,
                file_size=self.current_encode.file_size,
                total_chunks=self.current_encode.total_chunks,
            )

        # 启动发送定时器
        self.btn_next_file.setEnabled(True)
        self._start_qr_gen_thread()
        self._start_qr_timer()

    def _start_qr_timer(self):
        """启动QR码切换定时器"""
        if self.send_timer is not None:
            self.send_timer.stop()

        interval = int(1000 / self.config.send_fps)
        self.send_timer = QTimer(self)
        self.send_timer.timeout.connect(self._show_next_batch)
        self.send_timer.start(interval)

        # 预请求两批供后台生成，并同步生成第一批立即显示
        self._request_next_batch()
        self._request_next_batch()
        self._show_next_batch(sync_fallback=True)

    # ========== QR实时生成与批次显示 ==========

    def _start_qr_gen_thread(self):
        """启动后台QR图像生成线程"""
        self._stop_qr_gen_thread()
        self._gen_running = True
        self.gen_queue = queue.Queue(maxsize=4)
        self.ready_queue = queue.Queue()
        self.qr_gen_thread = threading.Thread(target=self._qr_gen_worker, daemon=True)
        self.qr_gen_thread.start()

    def _qr_gen_worker(self):
        """后台线程：将帧数据实时生成为QR图像"""
        # 使用局部引用避免停止时主线程置None造成竞态
        gen_queue = self.gen_queue
        ready_queue = self.ready_queue
        encoder = self.current_encoder
        while self._gen_running:
            try:
                entries = gen_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if entries is None:
                break
            if encoder is None:
                continue
            try:
                images = [encoder.make_qr(e.frame_data) for e in entries]
            except Exception:
                continue
            if not self._gen_running:
                break
            try:
                ready_queue.put((entries, images))
            except Exception:
                pass

    def _stop_qr_gen_thread(self):
        """停止后台QR图像生成线程"""
        self._gen_running = False
        if self.qr_gen_thread is not None and self.qr_gen_thread.is_alive():
            try:
                if self.gen_queue is not None:
                    self.gen_queue.put_nowait(None)
            except queue.Full:
                pass
            self.qr_gen_thread.join(timeout=1.0)
        self.qr_gen_thread = None
        self.gen_queue = None
        self.ready_queue = None

    def _take_entries(self) -> List[QREntry]:
        """从播放列表取下一批帧（循环播放）"""
        entries: List[QREntry] = []
        count = self.config.qr_display_count
        for _ in range(count):
            if not self.shuffled_playlist:
                break
            if self.current_qr_index >= len(self.shuffled_playlist):
                self.current_qr_index = 0
            entries.append(self.shuffled_playlist[self.current_qr_index])
            self.current_qr_index += 1
        return entries

    def _request_next_batch(self):
        """将下一批帧交给后台线程生成QR图像"""
        if not self._gen_running or self.gen_queue is None:
            return
        entries = self._take_entries()
        if not entries:
            return
        try:
            self.gen_queue.put_nowait(entries)
        except queue.Full:
            pass

    def _show_next_batch(self, sync_fallback: bool = False):
        """显示最新一批就绪的QR码，并请求后台生成下一批"""
        if not self.is_sending or self.current_encode is None:
            return
        if not self.shuffled_playlist:
            return

        # 取最新的就绪批次
        latest = None
        while True:
            try:
                latest = self.ready_queue.get_nowait()
            except queue.Empty:
                break

        if latest is not None:
            self._display_batch(latest)
        elif sync_fallback:
            # 启动瞬间同步生成第一批，保证立即有画面
            entries = self._take_entries()
            if entries and self.current_encoder is not None:
                images = [self.current_encoder.make_qr(e.frame_data) for e in entries]
                self._display_batch((entries, images))

        # 请求后台生成下一批
        self._request_next_batch()

    def _display_batch(self, batch):
        """显示一批QR码图像"""
        entries, images = batch
        count = len(images)

        for i, label in enumerate(self.qr_labels):
            label.setVisible(i < count)

        for i, (entry, img) in enumerate(zip(entries, images)):
            if i >= len(self.qr_labels):
                break
            self._set_label_pixmap(self.qr_labels[i], img)
            if entry.chunk_index >= 0:
                self.shown_chunks.add(entry.chunk_index)

        # 更新进度（按已覆盖的唯一chunk数）
        covered = len(self.shown_chunks)
        self.progress_bar.setValue(min(covered, self.current_encode.total_chunks))
        self.lbl_progress_detail.setText(
            f"已覆盖 {covered}/{self.current_encode.total_chunks} chunks · "
            f"播放位置 {self.current_qr_index}/{len(self.shuffled_playlist)}"
        )

        # 帧类型信息
        types = []
        for entry in entries:
            if entry.chunk_index == -1:
                types.append("META")
            elif entry.chunk_index == -2:
                types.append("END")
            else:
                types.append(f"#{entry.chunk_index + 1}")
        self.lbl_qr_info.setText(f"同显 {count} 张: {' | '.join(types)}")

    def _set_label_pixmap(self, label: QLabel, img: Image.Image):
        """将PIL图像显示到label（缩放适配）"""
        avail = label.size()
        w = max(120, avail.width() - 10)
        h = max(120, avail.height() - 10)

        data = img.tobytes("raw", "RGB")
        qimage = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage).scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        label.setPixmap(pixmap)

    def _build_dynamic_shuffled_playlist(self) -> List[QREntry]:
        """构建动态乱序播放列表（每轮乱序DATA前都插入META + 末尾END）

        META帧周期性重发，确保中途开始接收或漏掉首帧META的
        接收方仍能建立传输会话，避免卡在"等待接收"状态。
        """
        if self.current_encode is None:
            return []

        playlist: List[QREntry] = []

        # 多轮乱序：保证每轮都是完整的，覆盖所有chunk
        data_entries = list(self.current_encode.data_entries)
        rounds = max(3, min(8, 200 // max(len(data_entries), 1) + 2))
        for _ in range(rounds):
            playlist.append(self.current_encode.meta_entry)
            shuffled = list(data_entries)
            random.shuffle(shuffled)
            playlist.extend(shuffled)

        playlist.append(self.current_encode.end_entry)
        return playlist

    def _confirm_next(self):
        """确认当前文件接收完成，发送下一个"""
        if not self.is_sending or self.current_encode is None:
            return

        # 停止当前发送计时器
        if self.send_timer:
            self.send_timer.stop()

        # 停止QR生成线程
        self._stop_qr_gen_thread()

        # 记录完成任务
        task_id = self.current_task_id
        filename = self.current_encode.filename
        transfer_id = self.current_transfer_id

        self.send_completed.emit(task_id or "", filename or "")

        self.btn_next_file.setEnabled(False)

        if self.queue:
            # 还有下一个文件
            self._send_next_file()
        else:
            self._on_queue_complete()

    def _stop_sending(self):
        """停止发送"""
        self.is_sending = False
        if self.send_timer:
            self.send_timer.stop()
            self.send_timer = None

        # 停止QR生成线程
        self._stop_qr_gen_thread()

        self.btn_add_files.setEnabled(True)
        self.btn_remove_file.setEnabled(True)
        self.btn_clear_queue.setEnabled(True)
        self.btn_start_send.setEnabled(True)
        self.btn_stop_send.setEnabled(False)
        self.btn_next_file.setEnabled(False)

        self.lbl_current_file.setText("当前文件: 无")
        self.progress_bar.setValue(0)
        self.lbl_progress_detail.setText("")
        self._clear_qr_labels("等待发送文件...")
        self.lbl_qr_info.setText("")

        self.current_encode = None
        self.current_encoder = None
        self.shuffled_playlist.clear()
        self.shown_chunks.clear()

    def _on_queue_complete(self):
        """队列发送完成"""
        self.is_sending = False
        if self.send_timer:
            self.send_timer.stop()
            self.send_timer = None

        # 停止QR生成线程
        self._stop_qr_gen_thread()

        self.btn_add_files.setEnabled(True)
        self.btn_remove_file.setEnabled(True)
        self.btn_clear_queue.setEnabled(True)
        self.btn_start_send.setEnabled(True)
        self.btn_stop_send.setEnabled(False)
        self.btn_next_file.setEnabled(False)

        self.lbl_current_file.setText("当前文件: 全部发送完成 ✓")
        self.lbl_progress_detail.setText("队列已发完")
        self._clear_qr_labels("全部发送完成！")
        self.lbl_qr_info.setText("")
        self.shown_chunks.clear()

        QMessageBox.information(self, "完成", "队列中所有文件已发送完成！")

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
