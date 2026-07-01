"""
领星 ERP 自动化框架 - 桌面 GUI V12
====================================
基于 PyQt5 + qfluentwidgets，页面已拆分为 pages/ 目录。

工作流:
  浏览器管理 → 元素采集 → 数据清洗 → 动作配置 → 编排运行

使用方法:
    python main.py

V12 改进:
  1. GUI 分模块 — pages/ 目录，各页面独立文件
  2. Pyppeteer CDP 辅通道启用（session.py 传 browser 参数）
  3. OCR 路径配置化（vars.yaml → TESSERACT_PATH）
"""

import sys
import os
import webbrowser
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
)

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from pages import (
    HomePage, BrowserPage, CollectPage, CleanPage,
    ConfigurePage, OrchestratePage, FilesPage, HelpPage,
)


class MainWindow(FluentWindow):
    """主窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("领星 ERP 自动化框架 V12")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)

        # 创建页面
        self.home_page = HomePage(self)
        self.help_page = HelpPage(self)
        self.browser_page = BrowserPage(self)
        self.collect_page = CollectPage(self)
        self.clean_page = CleanPage(self)
        self.configure_page = ConfigurePage(self)
        self.orchestrate_page = OrchestratePage(self)
        self.files_page = FilesPage(self)

        # 导航
        self.addSubInterface(self.home_page, FluentIcon.HOME, "首页")
        self.addSubInterface(self.browser_page, FluentIcon.GLOBE, "浏览器")
        self.addSubInterface(self.collect_page, FluentIcon.CAMERA, "采集")
        self.addSubInterface(self.clean_page, FluentIcon.BROOM, "清洗")
        self.addSubInterface(self.configure_page, FluentIcon.SETTING, "配置")
        self.addSubInterface(self.orchestrate_page, FluentIcon.PLAY, "编排")
        self.addSubInterface(self.help_page, FluentIcon.HELP, "帮助",
                             position=NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.files_page, FluentIcon.FOLDER, "文件管理",
                             position=NavigationItemPosition.BOTTOM)

        # 首页快捷按钮 → 页面跳转
        hp = self.home_page
        hp.btn_browser.clicked.connect(lambda: self._nav_to(self.browser_page))
        hp.btn_collect.clicked.connect(lambda: self._nav_to(self.collect_page))
        hp.btn_clean.clicked.connect(lambda: self._nav_to(self.clean_page))
        hp.btn_configure.clicked.connect(lambda: self._nav_to(self.configure_page))
        hp.btn_flow.clicked.connect(lambda: self._nav_to(self.orchestrate_page))
        hp.btn_editor.clicked.connect(self.configure_page.open_editor)
        hp.btn_open_help.clicked.connect(lambda: self._nav_to(self.help_page))

        # 浏览器页面启动
        bp = self.browser_page
        bp.btn_start.clicked.connect(self._start_browser)
        bp.btn_stop.clicked.connect(self._stop_browser)

        # 采集页自动连接
        self.collect_page.btn_collect.clicked.connect(self.collect_page.start_collect)
        self.collect_page.btn_stop_collect.clicked.connect(
            lambda: self.collect_page.runner.stop())

        # 状态刷新
        self.status_bar = QLabel("就绪", self)
        self.status_bar.setStyleSheet("padding: 4px 16px; color: #888; font-size: 12px;")
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.home_page.refresh_stats)
        self._refresh_timer.start(10000)

    def _nav_to(self, page: QWidget):
        """安全切换到指定页面"""
        QTimer.singleShot(0, lambda: self.switchTo(page))

    def _start_browser(self):
        bp = self.browser_page
        bp.btn_start.setEnabled(False)
        bp.btn_stop.setEnabled(True)
        bp.status_label.setText("启动中...")
        bp.status_label.setStyleSheet("color: #f77f00; font-weight: bold;")
        bp.log_output.clear()
        bp.log_output.append("▶ 启动浏览器...\n" + f"{'─'*50}")
        args = ["--headless"] if bp.cb_headless.isChecked() else []
        bp.runner.run("python", ["start_browser.py"] + args, output_widget=bp.log_output)

    def _stop_browser(self):
        bp = self.browser_page
        bp.log_output.append("\n⏹ 关闭浏览器...")
        bp.runner.stop()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))

    # 确保 docs 目录
    from pages.utils import ensure_docs
    ensure_docs()

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
