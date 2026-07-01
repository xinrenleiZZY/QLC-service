"""
浏览器管理页面
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt5.QtGui import QTextCursor
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, CheckBox, QTextEdit,
)
from .utils import QProcessRunner


class BrowserPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("browserPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("🌐 浏览器管理", self))

        ctrl = CardWidget(self)
        cl = QVBoxLayout(ctrl); cl.setSpacing(12)
        r1 = QHBoxLayout()
        self.btn_start = PrimaryPushButton("🚀 启动浏览器", self)
        self.btn_stop = PushButton("⏹ 关闭浏览器", self)
        self.btn_stop.setEnabled(False)
        r1.addWidget(self.btn_start); r1.addWidget(self.btn_stop); r1.addStretch()
        cl.addLayout(r1)

        sr = QHBoxLayout()
        sr.addWidget(BodyLabel("状态:", self))
        self.status_label = BodyLabel("未启动", self)
        self.status_label.setStyleSheet("color: #888; font-weight: bold;")
        sr.addWidget(self.status_label)
        sr.addSpacing(20)
        sr.addWidget(BodyLabel("端口:", self))
        self.port_label = BodyLabel("18800", self)
        sr.addWidget(self.port_label); sr.addStretch()
        cl.addLayout(sr)

        self.cb_headless = CheckBox("无头模式", self)
        cl.addWidget(self.cb_headless)
        layout.addWidget(ctrl)

        log_card = CardWidget(self)
        ll = QVBoxLayout(log_card); ll.setSpacing(8)
        ll.addWidget(StrongBodyLabel("控制台输出"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(300)
        self.log_output.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:12px;")
        ll.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        self.runner = QProcessRunner(self)
        self.runner.process.finished.connect(self._on_finished)

    def _on_finished(self, exit_code, exit_status):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("已关闭")
        self.status_label.setStyleSheet("color: #e63946; font-weight: bold;")
