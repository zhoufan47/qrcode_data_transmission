"""
任务历史面板：查看已完成/进行中的传输任务
"""

import os
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QComboBox, QMessageBox, QAbstractItemView,
)

from models.task_manager import TaskManager, TaskRecord


class TaskHistoryPanel(QWidget):
    """任务历史面板"""

    # 信号
    task_selected = Signal(str)  # task_id

    def __init__(self, task_manager: TaskManager, parent=None):
        super().__init__(parent)
        self.task_manager = task_manager

        # 自动刷新定时器
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_table)
        self.refresh_timer.start(2000)  # 每2秒刷新

        self._init_ui()
        self.refresh_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 顶部控制栏
        control_row = QHBoxLayout()

        control_row.addWidget(QLabel("筛选:"))
        self.cmb_filter = QComboBox()
        self.cmb_filter.addItem("全部任务", "all")
        self.cmb_filter.addItem("发送任务", "send")
        self.cmb_filter.addItem("接收任务", "receive")
        self.cmb_filter.addItem("已完成", "completed")
        self.cmb_filter.addItem("失败", "failed")
        self.cmb_filter.currentIndexChanged.connect(self.refresh_table)
        control_row.addWidget(self.cmb_filter)

        control_row.addStretch()

        self.btn_delete_selected = QPushButton("删除选中")
        self.btn_delete_selected.clicked.connect(self._delete_selected)
        control_row.addWidget(self.btn_delete_selected)

        self.btn_clear_all = QPushButton("清空全部")
        self.btn_clear_all.clicked.connect(self._clear_all)
        control_row.addWidget(self.btn_clear_all)

        self.btn_export = QPushButton("导出CSV")
        self.btn_export.clicked.connect(self._export_csv)
        control_row.addWidget(self.btn_export)

        self.btn_open_file = QPushButton("打开文件位置")
        self.btn_open_file.clicked.connect(self._open_file_location)
        control_row.addWidget(self.btn_open_file)

        layout.addLayout(control_row)

        # 任务表格
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "文件名", "方向", "文件大小", "开始时间", "结束时间",
            "总耗时", "速率", "状态", "输出路径",
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 200)  # 文件名
        self.table.setColumnWidth(1, 50)   # 方向
        self.table.setColumnWidth(2, 80)   # 大小
        self.table.setColumnWidth(3, 140)  # 开始时间
        self.table.setColumnWidth(4, 140)  # 结束时间
        self.table.setColumnWidth(5, 80)   # 耗时
        self.table.setColumnWidth(6, 80)   # 速率
        self.table.setColumnWidth(7, 60)   # 状态

        layout.addWidget(self.table)

        # 底部统计
        stats_row = QHBoxLayout()
        self.lbl_stats = QLabel("共 0 个任务")
        stats_row.addWidget(self.lbl_stats)
        stats_row.addStretch()
        layout.addLayout(stats_row)

    # ========== 刷新 ==========

    def refresh_table(self):
        """刷新任务表格"""
        filter_type = self.cmb_filter.currentData()
        tasks = self.task_manager.get_all_tasks()

        # 筛选
        if filter_type == "send":
            tasks = [t for t in tasks if t.direction == "send"]
        elif filter_type == "receive":
            tasks = [t for t in tasks if t.direction == "receive"]
        elif filter_type == "completed":
            tasks = [t for t in tasks if t.status == "completed"]
        elif filter_type == "failed":
            tasks = [t for t in tasks if t.status == "failed"]

        self.table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            self._set_row(row, task)

        self.lbl_stats.setText(
            f"共 {len(tasks)} 个任务  |  "
            f"已完成: {sum(1 for t in tasks if t.status == 'completed')}  |  "
            f"失败: {sum(1 for t in tasks if t.status == 'failed')}"
        )

    def _set_row(self, row: int, task: TaskRecord):
        """设置表格行数据"""
        items = [
            (task.filename, None),
            ("发送" if task.direction == "send" else "接收", None),
            (task.file_size_display, task.file_size),
            (self._format_time(task.start_time), None),
            (self._format_time(task.end_time), None),
            (task.elapsed_display, task.elapsed_seconds),
            (task.transfer_rate_display, task.transfer_rate),
            (self._status_text(task.status), None),
            (task.output_path, None),
        ]

        for col, (text, sort_data) in enumerate(items):
            item = QTableWidgetItem(text)
            if sort_data is not None:
                item.setData(Qt.UserRole, sort_data)
            item.setToolTip(text)

            # 状态列着色
            if col == 7:
                if task.status == "completed":
                    item.setForeground(Qt.green)
                elif task.status == "failed":
                    item.setForeground(Qt.red)
                elif task.status == "transferring":
                    item.setForeground(Qt.blue)

            item.setData(Qt.UserRole + 1, task.task_id)  # 存储task_id
            self.table.setItem(row, col, item)

    # ========== 操作 ==========

    def _delete_selected(self):
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要删除的任务")
            return

        reply = QMessageBox.question(
            self, "确认删除", f"确定删除选中的 {len(selected_rows)} 个任务记录吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for row in sorted(selected_rows, reverse=True):
            item = self.table.item(row, 0)
            if item:
                task_id = item.data(Qt.UserRole + 1)
                self.task_manager.delete_task(task_id)

        self.refresh_table()

    def _clear_all(self):
        reply = QMessageBox.question(
            self, "确认清空", "确定清空所有任务历史记录吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.task_manager.clear_all()
        self.refresh_table()

    def _export_csv(self):
        """导出为CSV文件"""
        from PySide6.QtWidgets import QFileDialog
        import csv

        path, _ = QFileDialog.getSaveFileName(
            self, "导出任务历史", "task_history.csv", "CSV文件 (*.csv)"
        )
        if not path:
            return

        tasks = self.task_manager.get_all_tasks()
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "文件名", "方向", "文件大小(字节)", "开始时间", "结束时间",
                    "总耗时(秒)", "速率(B/s)", "状态", "输出路径",
                ])
                for task in tasks:
                    writer.writerow([
                        task.filename,
                        task.direction,
                        task.file_size,
                        task.start_time,
                        task.end_time,
                        task.elapsed_seconds,
                        task.transfer_rate,
                        task.status,
                        task.output_path,
                    ])
            QMessageBox.information(self, "导出成功", f"已导出 {len(tasks)} 条记录到:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _open_file_location(self):
        """打开选中任务的文件位置"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择一个已完成的接收任务")
            return

        for row in selected_rows:
            item = self.table.item(row, 8)  # 输出路径列
            if item and item.text():
                path = item.text()
                if os.path.exists(path):
                    # macOS: open -R
                    import subprocess
                    subprocess.run(["open", "-R", path])
                elif os.path.exists(os.path.dirname(path)):
                    import subprocess
                    subprocess.run(["open", os.path.dirname(path)])
                return

    # ========== 辅助方法 ==========

    @staticmethod
    def _format_time(iso_str: str) -> str:
        if not iso_str:
            return "-"
        try:
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return iso_str

    @staticmethod
    def _status_text(status: str) -> str:
        mapping = {
            "pending": "等待中",
            "transferring": "传输中",
            "completed": "已完成",
            "failed": "失败",
        }
        return mapping.get(status, status)
