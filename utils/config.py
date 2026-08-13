"""
应用配置
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class AppConfig:
    """应用配置"""

    # 发送设置
    chunk_size: int = 1024
    qr_size: int = 600
    qr_border: int = 4
    shuffle_enabled: bool = True
    send_fps: float = 5.0  # 发送端QR码切换帧率
    qr_display_count: int = 1  # 同屏显示的QR码数量 (1/2/4/6)

    # 接收设置
    capture_source: str = "camera"  # "camera" 或 "screen"
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    capture_fps: float = 15.0
    monitor_index: int = 1

    # 通用设置
    output_dir: str = ""
    language: str = "zh_CN"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "AppConfig":
        defaults = AppConfig()
        for key, value in data.items():
            if hasattr(defaults, key):
                setattr(defaults, key, value)
        return defaults


class ConfigManager:
    """配置管理器"""

    def __init__(self):
        self.config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config.json",
        )
        self.config = AppConfig()
        self._load()

    def get(self) -> AppConfig:
        return self.config

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._save()

    def _save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def _load(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.config = AppConfig.from_dict(data)
        except Exception as e:
            print(f"加载配置失败: {e}")
