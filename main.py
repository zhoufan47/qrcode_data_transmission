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

    # 强制使用浅色配色方案：界面样式表使用浅色背景，
    # 若跟随系统深色模式会导致调色板文字为白色、与浅色背景叠加后标签文字不可见
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        # 旧版 Qt (<6.8) 无此 API，通过显式浅色调色板兜底
        from PySide6.QtGui import QPalette, QColor
        light_palette = QPalette()
        light_palette.setColor(QPalette.Window, QColor("#f5f5f5"))
        light_palette.setColor(QPalette.WindowText, QColor("#333333"))
        light_palette.setColor(QPalette.Base, QColor("#ffffff"))
        light_palette.setColor(QPalette.AlternateBase, QColor("#f7f7f7"))
        light_palette.setColor(QPalette.Text, QColor("#333333"))
        light_palette.setColor(QPalette.Button, QColor("#fafafa"))
        light_palette.setColor(QPalette.ButtonText, QColor("#333333"))
        light_palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
        light_palette.setColor(QPalette.ToolTipText, QColor("#333333"))
        light_palette.setColor(QPalette.Highlight, QColor("#2196F3"))
        light_palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        light_palette.setColor(QPalette.PlaceholderText, QColor("#999999"))
        app.setPalette(light_palette)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
