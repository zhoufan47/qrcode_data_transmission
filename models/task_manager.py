"""
任务管理器：管理传输任务的历史记录和状态
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class TaskRecord:
    """传输任务记录"""
    task_id: str
    transfer_id: str
    filename: str
    file_size: int          # 字节
    direction: str          # "send" 或 "receive"
    status: str             # "pending", "transferring", "completed", "failed"
    start_time: str = ""    # ISO格式
    end_time: str = ""      # ISO格式
    total_chunks: int = 0
    received_chunks: int = 0
    elapsed_seconds: float = 0.0
    transfer_rate: float = 0.0  # bytes/sec
    output_path: str = ""
    error_message: str = ""

    @property
    def file_size_display(self) -> str:
        """友好的文件大小显示"""
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    @property
    def transfer_rate_display(self) -> str:
        """友好的速率显示"""
        rate = self.transfer_rate
        if rate < 1024:
            return f"{rate:.0f} B/s"
        elif rate < 1024 * 1024:
            return f"{rate / 1024:.1f} KB/s"
        else:
            return f"{rate / (1024 * 1024):.2f} MB/s"

    @property
    def elapsed_display(self) -> str:
        """耗时显示"""
        seconds = self.elapsed_seconds
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

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "TaskRecord":
        return TaskRecord(**data)


class TaskManager:
    """任务管理器"""

    def __init__(self, storage_path: str = ""):
        if not storage_path:
            storage_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "task_history.json",
            )
        self.storage_path = storage_path
        self.tasks: Dict[str, TaskRecord] = {}
        self._load()

    def create_send_task(self, task_id: str, transfer_id: str, filename: str, file_size: int, total_chunks: int) -> TaskRecord:
        """创建发送任务"""
        record = TaskRecord(
            task_id=task_id,
            transfer_id=transfer_id,
            filename=filename,
            file_size=file_size,
            direction="send",
            status="pending",
            start_time=datetime.now().isoformat(),
            total_chunks=total_chunks,
        )
        self.tasks[task_id] = record
        self._save()
        return record

    def create_receive_task(
        self, task_id: str, transfer_id: str, filename: str, file_size: int, total_chunks: int
    ) -> TaskRecord:
        """创建接收任务"""
        record = TaskRecord(
            task_id=task_id,
            transfer_id=transfer_id,
            filename=filename,
            file_size=file_size,
            direction="receive",
            status="transferring",
            start_time=datetime.now().isoformat(),
            total_chunks=total_chunks,
        )
        self.tasks[task_id] = record
        self._save()
        return record

    def update_progress(self, task_id: str, received_chunks: int):
        """更新进度"""
        if task_id in self.tasks:
            self.tasks[task_id].received_chunks = received_chunks
            self.tasks[task_id].status = "transferring"

    def mark_send_started(self, task_id: str):
        """标记发送开始"""
        if task_id in self.tasks:
            self.tasks[task_id].status = "transferring"
            self.tasks[task_id].start_time = datetime.now().isoformat()

    def mark_completed(self, task_id: str, elapsed: float = 0, rate: float = 0, output_path: str = ""):
        """标记任务完成"""
        if task_id in self.tasks:
            record = self.tasks[task_id]
            record.status = "completed"
            record.end_time = datetime.now().isoformat()
            record.elapsed_seconds = elapsed
            record.transfer_rate = rate
            record.output_path = output_path
            record.received_chunks = record.total_chunks
            self._save()

    def mark_failed(self, task_id: str, error_message: str = ""):
        """标记任务失败"""
        if task_id in self.tasks:
            record = self.tasks[task_id]
            record.status = "failed"
            record.end_time = datetime.now().isoformat()
            record.error_message = error_message
            self._save()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[TaskRecord]:
        return sorted(
            self.tasks.values(),
            key=lambda t: t.start_time or "",
            reverse=True,
        )

    def get_completed_tasks(self) -> List[TaskRecord]:
        return [t for t in self.tasks.values() if t.status == "completed"]

    def get_tasks_by_direction(self, direction: str) -> List[TaskRecord]:
        return [t for t in self.tasks.values() if t.direction == direction]

    def delete_task(self, task_id: str):
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save()

    def clear_all(self):
        self.tasks.clear()
        self._save()

    def _save(self):
        try:
            data = [t.to_dict() for t in self.tasks.values()]
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存任务历史失败: {e}")

    def _load(self):
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                record = TaskRecord.from_dict(item)
                self.tasks[record.task_id] = record
        except Exception as e:
            print(f"加载任务历史失败: {e}")
