"""
元素采集页面 — 使用 V11 采集器
"""
import os
import socket
from datetime import datetime

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, LineEdit, SpinBox,
    InfoBar, QTextEdit,
)
from .utils import QProcessRunner, DOCS_DIR


class CollectPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("collectPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("📡 元素采集", self))

        cfg = CardWidget(self)
        cl = QVBoxLayout(cfg)

        r1 = QHBoxLayout()
        r1.addWidget(BodyLabel("CDP 地址:", self))
        self.cdp_input = LineEdit(self)
        self.cdp_input.setText("http://127.0.0.1:18800")
        self.cdp_input.setMinimumWidth(240)
        r1.addWidget(self.cdp_input)
        r1.addSpacing(16)

        r1.addWidget(BodyLabel("输出文件名:", self))
        self.collect_output = LineEdit(self)
        now = datetime.now().strftime("%H%M%S")
        self.collect_output.setText(f"lingxing_elements_{now}")
        self.collect_output.setMinimumWidth(200)
        r1.addWidget(self.collect_output); r1.addStretch()
        cl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(BodyLabel("超时(秒,0=无限):", self))
        self.collect_timeout = SpinBox(self)
        self.collect_timeout.setRange(0, 3600); self.collect_timeout.setValue(0)
        r2.addWidget(self.collect_timeout); r2.addSpacing(20)
        self.btn_collect = PrimaryPushButton("▶️ 启动采集", self)
        r2.addWidget(self.btn_collect)
        self.btn_stop_collect = PushButton("⏹ 停止", self)
        self.btn_stop_collect.setEnabled(False)
        r2.addWidget(self.btn_stop_collect); r2.addStretch()
        cl.addLayout(r2)
        layout.addWidget(cfg)

        info_card = CardWidget(self)
        il = QVBoxLayout(info_card)
        il.addWidget(StrongBodyLabel("快捷键说明"))
        tips = QLabel(
            "F1 — 激活拾取模式（点击元素自动采集）\n"
            "F2 — 高亮模式（鼠标移动查看元素信息）\n"
            "F3 — 设置步骤名\n"
            "F4 — 退出工具（浏览器保持运行）\n"
            "Ctrl+S — 保存数据到 JSON 文件\n"
            "ESC — 关闭拾取模式", self)
        tips.setStyleSheet("color: #666; line-height: 1.6;")
        il.addWidget(tips)
        layout.addWidget(info_card)

        log_card = CardWidget(self)
        ll = QVBoxLayout(log_card); ll.setSpacing(8)
        ll.addWidget(StrongBodyLabel("控制台输出"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        self.log_output.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:12px;")
        ll.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        self.runner = QProcessRunner(self)
        self.btn_collect.clicked.connect(self.start_collect)
        self.btn_stop_collect.clicked.connect(lambda: self.runner.stop())

    def start_collect(self):
        cdp = self.cdp_input.text().strip()
        output_name = self.collect_output.text().strip() or "lingxing_elements.json"
        if not output_name.endswith('.json'): output_name += '.json'
        timeout = self.collect_timeout.value()

        # 检查端口
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        port = 18800
        try:
            if ':' in cdp:
                pp = cdp.split(':')[-1].rstrip('/')
                if pp.isdigit(): port = int(port)
            if sock.connect_ex(('127.0.0.1', port)) != 0:
                sock.close()
                InfoBar.warning("浏览器未运行", f"端口 {port} 无响应。请先在「浏览器」页启动。",
                                duration=8000, parent=self)
                self.log_output.clear()
                self.log_output.append(f"⚠️ 端口 {port} 无响应")
                self.log_output.append(f"   请先在「浏览器」页启动或运行 start_browser.py")
                return
            sock.close()
        except: pass

        os.makedirs(os.path.join(DOCS_DIR, "json"), exist_ok=True)
        full_output = os.path.join(DOCS_DIR, "json", output_name)
        args = ["--cdp", cdp, "--output", full_output]
        if timeout > 0: args += ["--timeout", str(timeout)]

        self.btn_collect.setEnabled(False)
        self.btn_stop_collect.setEnabled(True)
        self.log_output.clear()
        self.log_output.append(f"启动采集: {cdp}")
        self.log_output.append(f"输出文件: {full_output}")
        self.log_output.append(f"{'─'*50}")

        self.runner.run("python", ["debug_elements-V11.py"] + args,
                        output_widget=self.log_output,
                        finished_callback=self._on_finished)

    def _on_finished(self, code):
        self.btn_collect.setEnabled(True)
        self.btn_stop_collect.setEnabled(False)
        if code == 0:
            InfoBar.success("采集完成", "元素数据已保存", duration=3000, parent=self)
        else:
            InfoBar.error("采集异常", f"退出码: {code}", duration=5000, parent=self)
