"""
QR码数据摆渡系统 - 入口文件

基于QR码的文件传输系统，支持：
- 文件分块编码为QR码序列
- 队列发送与手动确认
- 可配置QR帧率和尺寸
- 乱序发送提升传输速率
- 摄像头/屏幕捕获接收
- 完整任务历史管理
"""

import sys
import os

# 确保工作目录为项目根目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from gui.main_window import MainWindow


def main():
    # 启用高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("QR码数据摆渡系统")
    app.setOrganizationName("QRCodeTransfer")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
