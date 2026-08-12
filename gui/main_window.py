"""
主窗口：整合发送、接收、任务历史三个面板
"""

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont, QAction
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel,
    QApplication, QMessageBox,
)

from gui.send_panel import SendPanel
from gui.receive_panel import ReceivePanel
from gui.task_history_panel import TaskHistoryPanel
from models.task_manager import TaskManager
from utils.config import ConfigManager


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()

        # 配置和任务管理
        self.config_manager = ConfigManager()
        self.task_manager = TaskManager()

        # 窗口设置
        self.setWindowTitle("QR码数据摆渡系统")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        # 创建标签页
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # 创建面板
        self.send_panel = SendPanel(self.config_manager, task_manager=self.task_manager)
        self.receive_panel = ReceivePanel(self.config_manager, task_manager=self.task_manager)
        self.task_history_panel = TaskHistoryPanel(self.task_manager)

        # 添加到标签页
        self.tab_widget.addTab(self.send_panel, "📤 文件发送")
        self.tab_widget.addTab(self.receive_panel, "📥 文件接收")
        self.tab_widget.addTab(self.task_history_panel, "📋 任务历史")

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._status_label = QLabel("就绪")
        self.status_bar.addWidget(self._status_label)

        # 连接信号
        self._connect_signals()

        # 设置样式
        self._apply_style()

        self._status("系统就绪")

    def _connect_signals(self):
        """连接信号"""
        self.send_panel.send_completed.connect(self._on_send_completed)
        self.receive_panel.receive_started.connect(self._on_receive_started)
        self.receive_panel.receive_completed.connect(self._on_receive_completed)

        # 当接收端完成时，通知发送端自动跳转下一个
        # （实际使用时用户手动点击"确认接收完成"按钮来触发下一个文件）

    def _on_send_completed(self, task_id: str, filename: str):
        """发送完成"""
        # 更新任务记录
        if task_id:
            self.task_manager.mark_completed(task_id)
        self._status(f"发送完成: {filename}")
        # 刷新任务历史
        self.task_history_panel.refresh_table()

    def _on_receive_started(self, task_id: str, filename: str):
        """接收开始"""
        self._status(f"开始接收: {filename}")

    def _on_receive_completed(self, task_id: str, filename: str, output_path: str, elapsed: float, rate: float):
        """接收完成"""
        # 任务记录已在receive_panel中更新
        self._status(f"接收完成: {filename} (耗时: {elapsed:.1f}s, 速率: {rate/1024:.1f} KB/s)")
        # 刷新任务历史
        self.task_history_panel.refresh_table()

    def _status(self, message: str):
        """更新状态栏"""
        self._status_label.setText(message)

    def _apply_style(self):
        """应用全局样式"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QTabWidget::pane {
                border: 1px solid #ccc;
                background-color: #ffffff;
            }
            QTabBar::tab {
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #ccc;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                background-color: #e0e0e0;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                border-bottom: 2px solid #2196F3;
            }
            QTabBar::tab:hover:!selected {
                background-color: #d0d0d0;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QPushButton {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 6px 14px;
                background-color: #fafafa;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
            QPushButton:disabled {
                color: #999;
                background-color: #f0f0f0;
            }
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            QTableWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                gridline-color: #eee;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 3px 6px;
            }
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)

    def closeEvent(self, event):
        """关闭窗口时停止所有采集"""
        if self.receive_panel.is_capturing:
            self.receive_panel._stop_capture()
        if self.send_panel.is_sending:
            self.send_panel._stop_sending()
        event.accept()
