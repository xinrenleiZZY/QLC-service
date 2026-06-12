"""
领星 ERP 自动化框架 - 桌面 GUI
===================================
基于 PyQt5 + qfluentwidgets 的全流程可视化操作工具。

工作流:
  浏览器管理 → 元素采集 → 数据清洗 → 动作配置 → 编排运行

使用方法:
    python main.py

文件管理:
  所有 JSON / YAML 文件统一存放在 docs/ 目录下
  docs/
    ├── json/      原始采集 JSON
    ├── cleaned/   清洗后 JSON
    ├── yaml/      动作配置 YAML
    └── flows/     流程定义 YAML
"""

import sys
import os
import subprocess
import json
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── 环境配置 ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
os.makedirs(os.path.join(DOCS_DIR, "json"), exist_ok=True)
os.makedirs(os.path.join(DOCS_DIR, "cleaned"), exist_ok=True)
os.makedirs(os.path.join(DOCS_DIR, "yaml"), exist_ok=True)
os.makedirs(os.path.join(DOCS_DIR, "flows"), exist_ok=True)

# ── PyQt5 导入 ──
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QProcess, QTimer, QUrl, QSize
)
from PyQt5.QtGui import QFont, QIcon, QDesktopServices, QColor, QPixmap, QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFileDialog, QMessageBox,
    QListWidget, QListWidgetItem, QSplitter, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QLineEdit, QGroupBox, QCheckBox,
    QSpinBox, QProgressBar, QTabWidget, QGridLayout,
    QScrollArea, QAbstractItemView, QMenu, QAction
)

# ── qfluentwidgets 导入 ──
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
    PrimaryPushButton, PushButton, ToolButton,
    CardWidget, TitleLabel, CaptionLabel, BodyLabel,
    LineEdit, ComboBox, TextEdit, InfoBadge,
    InfoBar, InfoBarPosition, ProgressBar,
    ListView, HorizontalFlipView,
    MessageBox, TableView, SpinBox,
    CheckBox, setTheme, Theme,
    SimpleCardWidget, HeaderCardWidget,
    StateToolTip, RoundMenu, Action,
    SearchLineEdit, StrongBodyLabel,
    HyperlinkButton, TransparentToolButton,
    PillPushButton, CommandBarView,
    isDarkTheme, SegmentedWidget,
    ScrollArea, ExpandLayout, SingleDirectionScrollArea,
)


# ════════════════════════════════════════════════════════════════
#  工具函数
# ════════════════════════════════════════════════════════════════

def list_json_files(directory: str) -> list:
    """列出目录下所有 JSON 文件"""
    p = Path(directory)
    return sorted([f.name for f in p.glob("*.json")])

def list_yaml_files(directory: str) -> list:
    """列出目录下所有 YAML 文件"""
    p = Path(directory)
    return sorted([f.name for f in p.glob("*.yaml")] + [f.name for f in p.glob("*.yml")])

def list_all_cleaned_files() -> list:
    """列出所有清洗后的 JSON"""
    return list_json_files(os.path.join(DOCS_DIR, "cleaned"))

def list_all_flow_files() -> list:
    """列出所有流程定义"""
    return list_yaml_files(os.path.join(DOCS_DIR, "flows"))

def list_all_raw_files() -> list:
    """列出所有原始采集 JSON"""
    return list_json_files(os.path.join(DOCS_DIR, "json"))

def count_lines(filepath: str) -> int:
    """文件行数"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except:
        return 0

def file_size_str(filepath: str) -> str:
    """文件大小可读字符串"""
    try:
        size = os.path.getsize(filepath)
        if size < 1024:
            return f"{size} B"
        elif size < 1024*1024:
            return f"{size/1024:.1f} KB"
        else:
            return f"{size/1024/1024:.1f} MB"
    except:
        return "?"


# ════════════════════════════════════════════════════════════════
#  工作线程（异步执行命令）
# ════════════════════════════════════════════════════════════════

class CommandThread(QThread):
    """在后台线程中执行命令，发射输出信号"""
    output = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, command: list, cwd: str = None):
        super().__init__()
        self.command = command
        self.working_dir = cwd or PROJECT_ROOT
        self._process = None

    def run(self):
        try:
            self._process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.working_dir,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1
            )
            for line in iter(self._process.stdout.readline, ''):
                if line:
                    self.output.emit(line.rstrip())
            self._process.wait()
            self.finished.emit(self._process.returncode)
        except Exception as e:
            self.output.emit(f"错误: {e}")
            self.finished.emit(-1)

    def stop(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except:
                self._process.kill()


class QProcessRunner(QWidget):
    """基于 QProcess 的命令执行器（实时输出到 QTextEdit）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)
        self._output_widget: Optional[QTextEdit] = None
        self._finished_callback = None
        self._running = False

    def run(self, command: str, args: list,
            output_widget: QTextEdit = None,
            cwd: str = None,
            finished_callback=None):
        """启动命令"""
        self._output_widget = output_widget
        self._finished_callback = finished_callback
        self._running = True

        if output_widget:
            output_widget.clear()

        work_dir = cwd or PROJECT_ROOT
        self.process.setWorkingDirectory(work_dir)
        full_cmd = [command] + args
        self.process.start(command, args)

    def _on_output(self):
        if self._output_widget:
            raw = self.process.readAllStandardOutput().data()
            # 自动检测编码：优先 utf-8，回退 gbk
            data = raw.decode('utf-8', errors='replace')
            self._output_widget.moveCursor(QTextCursor.End)
            self._output_widget.insertPlainText(data)
            # 自动滚动到底部
            sb = self._output_widget.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_finished(self, exit_code, exit_status):
        self._running = False
        if self._output_widget:
            status = "完成" if exit_code == 0 else f"退出码={exit_code}"
            self._output_widget.append(f"\n{'─'*50}")
            self._output_widget.append(f"  进程结束: {status}")
        if self._finished_callback:
            self._finished_callback(exit_code)

    def stop(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            QTimer.singleShot(2000, self.process.kill)

    @property
    def running(self):
        return self._running


# ════════════════════════════════════════════════════════════════
#  页面组件
# ════════════════════════════════════════════════════════════════

class HomePage(QWidget):
    """首页 - 工作流概览"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)

        # 标题
        title = TitleLabel("领星 ERP 自动化框架", self)
        subtitle = BodyLabel("完整工作流：浏览器管理 → 元素采集 → 数据清洗 → 动作配置 → 编排运行", self)
        subtitle.setStyleSheet("color: #888; font-size: 14px;")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # 快捷操作卡片
        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)

        card_title = StrongBodyLabel("快速启动", self)
        card_title.setStyleSheet("font-size: 16px;")
        card_layout.addWidget(card_title)

        btn_layout = QGridLayout()
        btn_layout.setSpacing(12)

        self.btn_browser = PrimaryPushButton("🚀 启动浏览器", self)
        self.btn_collect = PrimaryPushButton("📡 采集元素", self)
        self.btn_clean = PrimaryPushButton("🧹 清洗数据", self)
        self.btn_configure = PrimaryPushButton("⚙️ 配置动作", self)
        self.btn_flow = PrimaryPushButton("▶️ 运行流程", self)
        self.btn_editor = PushButton("📝 可视化编辑器", self)

        for btn in [self.btn_browser, self.btn_collect, self.btn_clean,
                     self.btn_configure, self.btn_flow, self.btn_editor]:
            btn.setMinimumHeight(48)
            btn.setMaximumWidth(200)

        btn_layout.addWidget(self.btn_browser, 0, 0)
        btn_layout.addWidget(self.btn_collect, 0, 1)
        btn_layout.addWidget(self.btn_clean, 1, 0)
        btn_layout.addWidget(self.btn_configure, 1, 1)
        btn_layout.addWidget(self.btn_flow, 2, 0)
        btn_layout.addWidget(self.btn_editor, 2, 1)

        card_layout.addLayout(btn_layout)
        layout.addWidget(card)

        # 帮助卡片
        help_card = CardWidget(self)
        help_layout = QHBoxLayout(help_card)
        help_layout.setSpacing(16)
        help_icon = TitleLabel("📖", self)
        help_icon.setStyleSheet("font-size: 32px;")
        help_layout.addWidget(help_icon)
        help_text = QWidget(self)
        help_text_layout = QVBoxLayout(help_text)
        help_text_layout.setSpacing(2)
        help_text_layout.addWidget(StrongBodyLabel("新手上路？查看完整功能说明"))
        help_text_layout.addWidget(BodyLabel("快捷键、参数详解、推荐工作流、常见问题一站式查阅"))
        help_layout.addWidget(help_text, 1)
        self.btn_open_help = PushButton("📖 查看帮助", self)
        self.btn_open_help.setMinimumHeight(40)
        help_layout.addWidget(self.btn_open_help)
        layout.addWidget(help_card)

        # 统计卡片
        stat_card = CardWidget(self)
        stat_layout = QHBoxLayout(stat_card)
        stat_layout.setSpacing(30)

        self.stat_raw = self._make_stat_item("📄", "原始 JSON", "0")
        self.stat_cleaned = self._make_stat_item("✨", "清洗后", "0")
        self.stat_yaml = self._make_stat_item("⚙️", "动作配置", "0")
        self.stat_flows = self._make_stat_item("📋", "流程定义", "0")

        stat_layout.addWidget(self.stat_raw)
        stat_layout.addWidget(self.stat_cleaned)
        stat_layout.addWidget(self.stat_yaml)
        stat_layout.addWidget(self.stat_flows)

        layout.addWidget(stat_card)
        layout.addStretch()

        # 刷新统计
        self.refresh_stats()

    def _make_stat_item(self, icon, label, value):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(4)
        v = TitleLabel(value, self)
        v.setObjectName("statValue")
        v.setStyleSheet("font-size: 28px;")
        l = CaptionLabel(f"{icon} {label}", self)
        layout.addWidget(v)
        layout.addWidget(l)
        return w

    def refresh_stats(self):
        raw_count = len(list_all_raw_files())
        cleaned_count = len(list_all_cleaned_files())
        yaml_count = len(list_yaml_files(os.path.join(DOCS_DIR, "yaml")))
        flow_count = len(list_all_flow_files())

        self.stat_raw.findChild(TitleLabel).setText(str(raw_count))
        self.stat_cleaned.findChild(TitleLabel).setText(str(cleaned_count))
        self.stat_yaml.findChild(TitleLabel).setText(str(yaml_count))
        self.stat_flows.findChild(TitleLabel).setText(str(flow_count))


class BrowserPage(QWidget):
    """浏览器管理页面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("browserPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        # 标题
        title = TitleLabel("🌐 浏览器管理", self)
        layout.addWidget(title)

        # 控制卡片
        ctrl_card = CardWidget(self)
        ctrl_layout = QVBoxLayout(ctrl_card)
        ctrl_layout.setSpacing(12)

        row1 = QHBoxLayout()
        self.btn_start = PrimaryPushButton("🚀 启动浏览器", self)
        self.btn_stop = PushButton("⏹ 关闭浏览器", self)
        self.btn_stop.setEnabled(False)
        row1.addWidget(self.btn_start)
        row1.addWidget(self.btn_stop)
        row1.addStretch()
        ctrl_layout.addLayout(row1)

        status_row = QHBoxLayout()
        status_row.addWidget(BodyLabel("状态:", self))
        self.status_label = BodyLabel("未启动", self)
        self.status_label.setStyleSheet("color: #888; font-weight: bold;")
        status_row.addWidget(self.status_label)
        status_row.addSpacing(20)
        status_row.addWidget(BodyLabel("端口:", self))
        self.port_label = BodyLabel("18800", self)
        status_row.addWidget(self.port_label)
        status_row.addStretch()
        ctrl_layout.addLayout(status_row)

        self.cb_headless = CheckBox("无头模式", self)
        ctrl_layout.addWidget(self.cb_headless)

        layout.addWidget(ctrl_card)

        # 日志卡片
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        log_layout.setSpacing(8)
        log_layout.addWidget(StrongBodyLabel("控制台输出"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(300)
        self.log_output.setStyleSheet("background: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; font-size: 12px;")
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        # QProcess
        self.runner = QProcessRunner(self)
        self.runner.process.finished.connect(self._on_browser_finished)

    def _on_browser_finished(self, exit_code, exit_status):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("已关闭")
        self.status_label.setStyleSheet("color: #e63946; font-weight: bold;")


class CollectPage(QWidget):
    """元素采集页面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("collectPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title = TitleLabel("📡 元素采集", self)
        layout.addWidget(title)

        # 配置卡片
        cfg_card = CardWidget(self)
        cfg_layout = QVBoxLayout(cfg_card)

        row1 = QHBoxLayout()
        row1.addWidget(BodyLabel("CDP 地址:", self))
        self.cdp_input = LineEdit(self)
        self.cdp_input.setText("http://127.0.0.1:18800")
        self.cdp_input.setMinimumWidth(240)
        row1.addWidget(self.cdp_input)

        row1.addSpacing(16)
        row1.addWidget(BodyLabel("输出文件名:", self))
        self.collect_output = LineEdit(self)
        now = datetime.now().strftime("%H%M%S")
        self.collect_output.setText(f"lingxing_elements_V10_{now}")
        self.collect_output.setMinimumWidth(200)
        row1.addWidget(self.collect_output)
        row1.addStretch()
        cfg_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(BodyLabel("超时(秒,0=无限):", self))
        self.collect_timeout = SpinBox(self)
        self.collect_timeout.setRange(0, 3600)
        self.collect_timeout.setValue(0)
        row2.addWidget(self.collect_timeout)
        row2.addSpacing(20)
        self.btn_collect = PrimaryPushButton("▶️ 启动采集", self)
        row2.addWidget(self.btn_collect)
        self.btn_stop_collect = PushButton("⏹ 停止", self)
        self.btn_stop_collect.setEnabled(False)
        row2.addWidget(self.btn_stop_collect)
        row2.addStretch()
        cfg_layout.addLayout(row2)

        layout.addWidget(cfg_card)

        # 使用说明
        info_card = CardWidget(self)
        info_layout = QVBoxLayout(info_card)
        info_layout.addWidget(StrongBodyLabel("快捷键说明"))
        tips = QLabel(
            "F1 — 激活拾取模式（点击元素自动采集）\n"
            "F2 — 高亮模式（鼠标移动查看元素信息）\n"
            "F3 — 设置步骤名\n"
            "F4 — 退出工具（浏览器保持运行）\n"
            "Ctrl+S — 保存数据到 JSON 文件\n"
            "ESC — 关闭拾取模式", self)
        tips.setStyleSheet("color: #666; line-height: 1.6;")
        info_layout.addWidget(tips)
        layout.addWidget(info_card)

        # 日志
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        log_layout.addWidget(StrongBodyLabel("控制台输出"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        self.log_output.setStyleSheet("background: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; font-size: 12px;")
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        self.runner = QProcessRunner(self)

    def start_collect(self):
        cdp = self.cdp_input.text().strip()
        output_name = self.collect_output.text().strip() or "lingxing_elements.json"
        if not output_name.endswith('.json'):
            output_name += '.json'
        timeout = self.collect_timeout.value()

        # 先检查浏览器是否运行
        import socket
        sock_check = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_check.settimeout(1.0)
        port = 18800
        try:
            # 从 cdp URL 提取端口
            if ':' in cdp:
                port_part = cdp.split(':')[-1].rstrip('/')
                if port_part.isdigit():
                    port = int(port_part)
            result = sock_check.connect_ex(('127.0.0.1', port))
            sock_check.close()
            if result != 0:
                InfoBar.warning("浏览器未运行",
                    f"端口 {port} 没有检测到浏览器。请先在「浏览器」页面启动。",
                    duration=8000, parent=self)
                self.log_output.clear()
                self.log_output.append(f"⚠️ 端口 {port} 无响应")
                self.log_output.append(f"   请先在「浏览器」页面启动浏览器")
                self.log_output.append(f"   或手动运行: python start_browser.py")
                self.btn_collect.setEnabled(True)
                return
        except Exception:
            pass

        # 输出到 docs/json/
        os.makedirs(os.path.join(DOCS_DIR, "json"), exist_ok=True)
        full_output = os.path.join(DOCS_DIR, "json", output_name)

        args = ["--cdp", cdp, "--output", full_output]
        if timeout > 0:
            args += ["--timeout", str(timeout)]

        self.btn_collect.setEnabled(False)
        self.btn_stop_collect.setEnabled(True)
        self.log_output.clear()
        self.log_output.append(f"启动采集: {cdp}")
        self.log_output.append(f"输出文件: {full_output}")
        self.log_output.append(f"{'─'*50}")

        self.runner.run("python", ["debug_elements-V10.py"] + args,
                        output_widget=self.log_output,
                        finished_callback=self._on_collect_finished)

    def _on_collect_finished(self, code):
        self.btn_collect.setEnabled(True)
        self.btn_stop_collect.setEnabled(False)
        if code == 0:
            InfoBar.success("采集完成", "元素数据已保存", duration=3000, parent=self)
            self.log_output.append("\n✅ 采集完成")
        else:
            InfoBar.error("采集异常", f"退出码: {code}", duration=5000, parent=self)


class CleanPage(QWidget):
    """数据清洗页面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cleanPage")
        self._browsed_file_map = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title = TitleLabel("🧹 数据清洗", self)
        layout.addWidget(title)

        # 源文件选择
        cfg_card = CardWidget(self)
        cfg_layout = QVBoxLayout(cfg_card)

        row1 = QHBoxLayout()
        row1.addWidget(BodyLabel("原始 JSON 文件:", self))
        self.cb_raw = ComboBox(self)
        self.cb_raw.setMinimumWidth(350)
        self.refresh_raw_list()
        row1.addWidget(self.cb_raw)
        self.btn_browse_raw = PushButton("📂 浏览...", self)
        row1.addWidget(self.btn_browse_raw)
        row1.addStretch()
        cfg_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_clean = PrimaryPushButton("▶️ 开始清洗", self)
        self.btn_clean.setMinimumWidth(160)
        row2.addWidget(self.btn_clean)
        row2.addWidget(BodyLabel("输出 → docs/cleaned/", self))
        row2.addStretch()
        cfg_layout.addLayout(row2)

        layout.addWidget(cfg_card)

        # 批量清洗
        batch_card = CardWidget(self)
        batch_layout = QVBoxLayout(batch_card)
        batch_layout.addWidget(StrongBodyLabel("批量清洗所有文件"))
        self.btn_batch_clean = PrimaryPushButton("🧹 清洗全部原始 JSON", self)
        batch_layout.addWidget(self.btn_batch_clean)
        layout.addWidget(batch_card)

        # 日志
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        log_layout.addWidget(StrongBodyLabel("清洗日志"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(300)
        self.log_output.setStyleSheet("background: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; font-size: 12px;")
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        self.runner = QProcessRunner(self)
        self.runner.process.finished.connect(self._on_clean_finished)

        # 连接信号
        self.btn_clean.clicked.connect(self.start_clean)
        self.btn_batch_clean.clicked.connect(self.start_batch_clean)
        self.btn_browse_raw.clicked.connect(self.browse_raw_file)

    def refresh_raw_list(self):
        self.cb_raw.clear()
        files = list_all_raw_files()
        if files:
            for f in files:
                self.cb_raw.addItem(f)
        else:
            self.cb_raw.addItem("(无原始文件)")

    def browse_raw_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择原始 JSON", DOCS_DIR, "JSON Files (*.json)")
        if path:
            fname = os.path.basename(path)
            self._browsed_file_map[fname] = path
            # 检查是否在已有列表中
            idx = self.cb_raw.findText(fname)
            if idx >= 0:
                self.cb_raw.setCurrentIndex(idx)
            else:
                self.cb_raw.addItem(fname)
                self.cb_raw.setCurrentIndex(self.cb_raw.count() - 1)

    def start_clean(self):
        fname = self.cb_raw.currentText()
        if not fname or fname == "(无原始文件)":
            InfoBar.warning("请选择文件", "先选择要清洗的原始 JSON 文件", parent=self)
            return

        # 先从浏览映射查找，再尝试标准路径
        actual_path = self._browsed_file_map.get(fname)
        if not actual_path:
            candidates = [
                os.path.join(DOCS_DIR, "json", fname),
                os.path.join(PROJECT_ROOT, fname),
            ]
            for p in candidates:
                if os.path.isfile(p):
                    actual_path = p
                    break
        if not actual_path:
            InfoBar.error("文件不存在", f"找不到: {fname}", parent=self)
            return

        self.log_output.clear()
        self.log_output.append(f"清洗: {actual_path}")
        self.log_output.append(f"{'─'*50}")
        self.btn_clean.setEnabled(False)

        self.runner.run("python", ["selector_cleaner.py", actual_path],
                        output_widget=self.log_output)

    def start_batch_clean(self):
        files = list_all_raw_files()
        if not files:
            InfoBar.warning("没有文件", "docs/json/ 目录下没有原始文件", parent=self)
            return

        self.log_output.clear()
        self.log_output.append(f"批量清洗 {len(files)} 个文件...")
        self.log_output.append(f"{'─'*50}")
        self.btn_batch_clean.setEnabled(False)

        # 逐个清洗
        for fname in files:
            fpath = os.path.join(DOCS_DIR, "json", fname)
            if os.path.isfile(fpath):
                self.log_output.append(f"\n▶ {fname}")
                result = subprocess.run(
                    ["python", "selector_cleaner.py", fpath],
                    capture_output=True, text=False, cwd=PROJECT_ROOT
                )
                # 手动解码，兼容 GBK/UTF-8
                out_text = result.stdout.decode('utf-8', errors='replace')
                for line in out_text.split('\n'):
                    if line.strip():
                        self.log_output.append(f"  {line}")
                if result.stderr:
                    err_text = result.stderr.decode('utf-8', errors='replace')
                    self.log_output.append(f"  错误: {err_text}")

        self.log_output.append(f"\n{'─'*50}")
        self.log_output.append("批量清洗完成")
        self.btn_batch_clean.setEnabled(True)
        InfoBar.success("批量清洗完成", f"已处理 {len(files)} 个文件", parent=self)

    def _on_clean_finished(self, exit_code, exit_status):
        self.btn_clean.setEnabled(True)


class ConfigurePage(QWidget):
    """动作配置页面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("configurePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title = TitleLabel("⚙️ 动作配置", self)
        layout.addWidget(title)

        # 方式1: 可视化编辑器
        card1 = CardWidget(self)
        c1_layout = QVBoxLayout(card1)
        c1_layout.addWidget(StrongBodyLabel("📝 可视化编辑器（推荐）"))
        c1_layout.addWidget(BodyLabel(
            "打开浏览器端的 YAML 编辑器，可视化配置每个元素的操作类型和参数。"))
        self.btn_open_editor = PrimaryPushButton("📝 打开可视化编辑器", self)
        c1_layout.addWidget(self.btn_open_editor)
        layout.addWidget(card1)

        # 方式2: CLI 配置
        card2 = CardWidget(self)
        c2_layout = QVBoxLayout(card2)
        c2_layout.addWidget(StrongBodyLabel("💻 命令行配置"))
        c2_layout.addWidget(BodyLabel("选择清洗后的 JSON 文件，用 CLI 逐一配置每个元素。"))

        row = QHBoxLayout()
        self.cb_cleaned = ComboBox(self)
        self.cb_cleaned.setMinimumWidth(350)
        self.refresh_cleaned_list()
        row.addWidget(self.cb_cleaned)
        self.btn_configure_cli = PrimaryPushButton("▶️ 开始配置", self)
        row.addWidget(self.btn_configure_cli)
        row.addStretch()
        c2_layout.addLayout(row)

        layout.addWidget(card2)

        # 查看已生成的 YAML
        card3 = CardWidget(self)
        c3_layout = QVBoxLayout(card3)
        c3_layout.addWidget(StrongBodyLabel("📂 查看已生成的配置"))
        self.refresh_yaml_btn = PushButton("🔄 刷新列表", self)
        c3_layout.addWidget(self.refresh_yaml_btn)

        self.yaml_table = QTableWidget(self)
        self.yaml_table.setColumnCount(3)
        self.yaml_table.setHorizontalHeaderLabels(["文件名", "大小", "修改时间"])
        self.yaml_table.horizontalHeader().setStretchLastSection(True)
        self.yaml_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.yaml_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.yaml_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.yaml_table.setMaximumHeight(200)
        self.refresh_yaml_table()
        c3_layout.addWidget(self.yaml_table)

        layout.addWidget(card3)
        layout.addStretch()

        # 连接信号
        self.btn_open_editor.clicked.connect(self.open_editor)
        self.btn_configure_cli.clicked.connect(self.start_cli_configure)
        self.refresh_yaml_btn.clicked.connect(self.refresh_yaml_table)

    def refresh_cleaned_list(self):
        self.cb_cleaned.clear()
        files = list_all_cleaned_files()
        if files:
            for f in files:
                self.cb_cleaned.addItem(f)
        else:
            self.cb_cleaned.addItem("(无清洗文件)")

    def refresh_yaml_table(self):
        self.yaml_table.setRowCount(0)
        yaml_dir = os.path.join(DOCS_DIR, "yaml")
        files = list_yaml_files(yaml_dir)
        for fname in files:
            fpath = os.path.join(yaml_dir, fname)
            row = self.yaml_table.rowCount()
            self.yaml_table.insertRow(row)
            self.yaml_table.setItem(row, 0, QTableWidgetItem(fname))
            self.yaml_table.setItem(row, 1, QTableWidgetItem(file_size_str(fpath)))
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            self.yaml_table.setItem(row, 2, QTableWidgetItem(mtime.strftime("%Y-%m-%d %H:%M")))

    def open_editor(self):
        html_path = os.path.join(PROJECT_ROOT, "yaml_editor.html")
        if os.path.isfile(html_path):
            webbrowser.open(f"file://{html_path}")
            InfoBar.info("已打开编辑器", "在浏览器中操作", parent=self)
        else:
            InfoBar.error("文件不存在", "yaml_editor.html 未找到", parent=self)

    def start_cli_configure(self):
        fname = self.cb_cleaned.currentText()
        if not fname or fname == "(无清洗文件)":
            InfoBar.warning("请选择文件", "先选择要配置的清洗后 JSON", parent=self)
            return

        cleaned_dir = os.path.join(DOCS_DIR, "cleaned", fname)
        if not os.path.isfile(cleaned_dir):
            InfoBar.error("文件不存在", f"找不到: {cleaned_dir}", parent=self)
            return

        # 在终端中启动 CLI 配置
        info = InfoBar.info("启动配置", f"在终端运行:\npython configure_actions.py \"{cleaned_dir}\"",
                           duration=8000, parent=self)


class OrchestratePage(QWidget):
    """编排运行页面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("orchestratePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title = TitleLabel("▶️ 编排运行", self)
        layout.addWidget(title)

        # 流程选择
        cfg_card = CardWidget(self)
        cfg_layout = QVBoxLayout(cfg_card)
        cfg_layout.setSpacing(12)

        row1 = QHBoxLayout()
        row1.addWidget(BodyLabel("选择流程文件:", self))
        self.cb_flows = ComboBox(self)
        self.cb_flows.setMinimumWidth(400)
        self.refresh_flow_list()
        row1.addWidget(self.cb_flows)
        self.btn_browse_flow = PushButton("📂 浏览...", self)
        row1.addWidget(self.btn_browse_flow)
        row1.addStretch()
        cfg_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_run = PrimaryPushButton("▶️ 运行流程", self)
        self.btn_run.setMinimumWidth(160)
        row2.addWidget(self.btn_run)
        self.btn_stop_flow = PushButton("⏹ 停止", self)
        self.btn_stop_flow.setEnabled(False)
        row2.addWidget(self.btn_stop_flow)
        row2.addSpacing(20)
        self.cb_close_browser = CheckBox("运行后关闭浏览器", self)
        row2.addWidget(self.cb_close_browser)
        row2.addStretch()
        cfg_layout.addLayout(row2)

        layout.addWidget(cfg_card)

        # 快速创建流程 + 可视化编排
        create_card = CardWidget(self)
        create_layout = QVBoxLayout(create_card)
        create_layout.addWidget(StrongBodyLabel("快速创建流程"))

        c_row = QHBoxLayout()
        self.flow_name_input = LineEdit(self)
        self.flow_name_input.setPlaceholderText("输入流程名称...")
        self.flow_name_input.setText("新建流程")
        c_row.addWidget(self.flow_name_input)
        self.btn_create_flow = PrimaryPushButton("📋 创建空白流程", self)
        c_row.addWidget(self.btn_create_flow)
        c_row.addStretch()
        create_layout.addLayout(c_row)

        # 可视化编排按钮
        c_row2 = QHBoxLayout()
        self.btn_flow_editor = PrimaryPushButton("📝 可视化编排流程", self)
        self.btn_flow_editor.clicked.connect(self.open_flow_editor)
        c_row2.addWidget(self.btn_flow_editor)
        c_row2.addWidget(BodyLabel("打开浏览器端的流程编排编辑器（yaml_editor.html → 📋 流程标签页）"))
        c_row2.addStretch()
        create_layout.addLayout(c_row2)

        layout.addWidget(create_card)

        # 日志
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        log_layout.addWidget(StrongBodyLabel("运行日志"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; font-size: 12px;")
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        self.runner = QProcessRunner(self)
        self.runner.process.finished.connect(self._on_flow_finished)

        # 连接信号
        self.btn_run.clicked.connect(self.run_flow)
        self.btn_stop_flow.clicked.connect(self.stop_flow)
        self.btn_browse_flow.clicked.connect(self.browse_flow)
        self.btn_create_flow.clicked.connect(self.create_flow)

    def refresh_flow_list(self):
        self.cb_flows.clear()
        files = list_all_flow_files()
        # 也检查项目根目录
        root_files = list_yaml_files(PROJECT_ROOT)
        flow_root = [f for f in root_files if f.startswith("flow_")]

        all_files = list(set(files + flow_root))
        if all_files:
            for f in sorted(all_files):
                self.cb_flows.addItem(f)
        else:
            self.cb_flows.addItem("(无流程文件)")

    def browse_flow(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择流程文件", PROJECT_ROOT, "YAML Files (*.yaml *.yml)")
        if path:
            fname = os.path.basename(path)
            idx = self.cb_flows.findText(fname)
            if idx >= 0:
                self.cb_flows.setCurrentIndex(idx)
            else:
                self.cb_flows.addItem(fname)
                self.cb_flows.setCurrentIndex(self.cb_flows.count() - 1)

    def create_flow(self):
        name = self.flow_name_input.text().strip()
        if not name:
            InfoBar.warning("输入名称", "请输入流程名称", parent=self)
            return

        yaml_name = f"flow_{name}.yaml"
        yaml_path = os.path.join(DOCS_DIR, "flows", yaml_name)

        if os.path.isfile(yaml_path):
            InfoBar.warning("已存在", f"{yaml_name} 已存在", parent=self)
            return

        content = f"""name: {name}

# 在此添加模块
# pre_flows:
#   - flow_检查登录态.yaml

modules:
  - name: 模块名
    json: 模块名_cleaned.json
    # yaml: actions_config_模块名.yaml
"""
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.refresh_flow_list()
        InfoBar.success("已创建", f"{yaml_name} 已保存到 docs/flows/", parent=self)

    def run_flow(self):
        fname = self.cb_flows.currentText()
        if not fname or fname == "(无流程文件)":
            InfoBar.warning("请选择流程", "先选择一个流程文件", parent=self)
            return

        # 查找文件
        candidates = [
            os.path.join(DOCS_DIR, "flows", fname),
            os.path.join(PROJECT_ROOT, fname),
        ]
        actual_path = None
        for p in candidates:
            if os.path.isfile(p):
                actual_path = p
                break
        if not actual_path:
            InfoBar.error("文件不存在", f"找不到: {fname}", parent=self)
            return

        self.log_output.clear()
        self.log_output.append(f"▶ 运行流程: {fname}")
        self.log_output.append(f"  文件: {actual_path}")
        self.log_output.append(f"{'─'*50}\n")

        self.btn_run.setEnabled(False)
        self.btn_stop_flow.setEnabled(True)

        self.runner.run("python", ["orchestrator.py", actual_path],
                        output_widget=self.log_output)

    def stop_flow(self):
        self.runner.stop()
        self.btn_run.setEnabled(True)
        self.btn_stop_flow.setEnabled(False)
        self.log_output.append("\n⏹ 已手动停止")

    def open_flow_editor(self):
        """打开 yaml_editor.html 到流程编排页"""
        html_path = os.path.join(PROJECT_ROOT, "yaml_editor.html")
        if os.path.isfile(html_path):
            webbrowser.open(f"file://{html_path}")
            InfoBar.info("已打开流程编辑器", "切换到「📋 流程」标签页编排流程", parent=self)
        else:
            InfoBar.error("文件不存在", "yaml_editor.html 未找到", parent=self)

    def _on_flow_finished(self, exit_code, exit_status):
        self.btn_run.setEnabled(True)
        self.btn_stop_flow.setEnabled(False)
        if exit_code == 0:
            self.log_output.append("\n✅ 流程运行完成")
        else:
            self.log_output.append(f"\n⚠️ 流程退出码: {exit_code}")


class FilesPage(QWidget):
    """文件管理页面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filesPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title = TitleLabel("📂 文件管理", self)
        layout.addWidget(title)

        # 目录快速跳转
        dir_card = CardWidget(self)
        dir_layout = QHBoxLayout(dir_card)
        dir_layout.setSpacing(12)

        dirs = [
            ("📄 原始 JSON", "json"),
            ("✨ 清洗后", "cleaned"),
            ("⚙️ 动作配置", "yaml"),
            ("📋 流程定义", "flows"),
        ]
        self.dir_buttons = {}
        for label, subdir in dirs:
            btn = PushButton(label, self)
            btn.clicked.connect(lambda checked, d=subdir: self.open_dir(d))
            dir_layout.addWidget(btn)
            self.dir_buttons[subdir] = btn

        # 项目根目录
        btn_root = PushButton("📁 项目根目录", self)
        btn_root.clicked.connect(lambda: self.open_dir(".."))
        dir_layout.addWidget(btn_root)

        dir_layout.addStretch()
        layout.addWidget(dir_card)

        # 文件浏览器
        self.file_table = QTableWidget(self)
        self.file_table.setColumnCount(5)
        self.file_table.setHorizontalHeaderLabels(["文件名", "类型", "大小", "修改时间", "目录"])
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.setSortingEnabled(True)
        self.file_table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.file_table, 1)

        # 刷新按钮
        btn_row = QHBoxLayout()
        self.btn_refresh = PrimaryPushButton("🔄 刷新列表", self)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        self.file_count_label = BodyLabel("", self)
        btn_row.addWidget(self.file_count_label)
        layout.addLayout(btn_row)

        self.btn_refresh.clicked.connect(self.refresh_files)
        self.file_table.cellDoubleClicked.connect(self.on_file_double_click)

        self.refresh_files()

    def open_dir(self, subdir: str):
        if subdir == "..":
            target = PROJECT_ROOT
        else:
            target = os.path.join(DOCS_DIR, subdir)
        if os.path.isdir(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def refresh_files(self):
        self.file_table.setRowCount(0)
        total = 0

        for dirname, label in [("json", "原始JSON"), ("cleaned", "清洗后"),
                                ("yaml", "动作配置"), ("flows", "流程定义")]:
            d = os.path.join(DOCS_DIR, dirname)
            if not os.path.isdir(d):
                continue
            for fname in sorted(os.listdir(d)):
                if not (fname.endswith('.json') or fname.endswith('.yaml') or fname.endswith('.yml')):
                    continue
                fpath = os.path.join(d, fname)
                if not os.path.isfile(fpath):
                    continue
                total += 1
                row = self.file_table.rowCount()
                self.file_table.insertRow(row)
                self.file_table.setItem(row, 0, QTableWidgetItem(fname))
                ext = os.path.splitext(fname)[1]
                type_label = "YAML" if ext in ('.yaml', '.yml') else "JSON"
                self.file_table.setItem(row, 1, QTableWidgetItem(type_label))
                self.file_table.setItem(row, 2, QTableWidgetItem(file_size_str(fpath)))
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                self.file_table.setItem(row, 3, QTableWidgetItem(mtime.strftime("%Y-%m-%d %H:%M")))
                self.file_table.setItem(row, 4, QTableWidgetItem(dirname))

        self.file_count_label.setText(f"共 {total} 个文件")

    def on_file_double_click(self, row, col):
        item = self.file_table.item(row, 0)
        dir_item = self.file_table.item(row, 4)
        if item and dir_item:
            fname = item.text()
            subdir = dir_item.text()
            fpath = os.path.join(DOCS_DIR, subdir, fname)
            if os.path.isfile(fpath):
                # 用系统默认编辑器打开
                QDesktopServices.openUrl(QUrl.fromLocalFile(fpath))


# ════════════════════════════════════════════════════════════════
#  帮助文档页面
# ════════════════════════════════════════════════════════════════

class HelpPage(QWidget):
    """功能说明页面"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("helpPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title = TitleLabel("📖 功能说明与使用指南", self)
        layout.addWidget(title)

        # 用 ScrollArea 包裹内容
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)

        # ── 1. 整体架构 ──
        arch_card = CardWidget(self)
        arch_layout = QVBoxLayout(arch_card)
        arch_layout.addWidget(StrongBodyLabel("一、整体架构"))
        arch_layout.addWidget(BodyLabel(
            "本框架用于自动化操作领星 ERP 网页端，通过 浏览器管理 → 元素采集 → 数据清洗 → "
            "动作配置 → 编排运行 五个步骤完成自动化流程。"))
        arch_layout.addWidget(BodyLabel(
            "核心脚本均位于项目根目录，JSON/YAML 配置统一存放于 docs/ 目录下，方便管理。"))
        arch_layout.addWidget(BodyLabel("运行入口：python main.py"))
        content_layout.addWidget(arch_card)

        # ── 2. 浏览器管理 ──
        br_card = CardWidget(self)
        br_layout = QVBoxLayout(br_card)
        br_layout.addWidget(StrongBodyLabel("二、浏览器管理"))
        br_layout.addWidget(BodyLabel(
            "端口：18800（已统一，兼容 OpenClaw）"))
        br_layout.addWidget(BodyLabel(
            "启动方式：\n"
            "  • GUI 中点击「浏览器 → 启动浏览器」\n"
            "  • 命令行：python start_browser.py\n"
            "  • 编排器自动检测：运行 orchestrator.py 时自动检测端口 18800 复用或启动"))
        br_layout.addWidget(BodyLabel(
            "特点：\n"
            "  • 单例模式：全局只启动一个浏览器实例\n"
            "  • 复用检测：自动连接已有 Chrome（CDP 端口 18800）\n"
            "  • 持久化配置：使用 playwright_profile 目录保存登录态"))
        content_layout.addWidget(br_card)

        # ── 3. 元素采集 ──
        col_card = CardWidget(self)
        col_layout = QVBoxLayout(col_card)
        col_layout.addWidget(StrongBodyLabel("三、元素采集"))
        col_layout.addWidget(BodyLabel(
            "使用 debug_elements-V10.py 连接已有浏览器，通过快捷键在页面上采集元素。"))

        col_layout.addWidget(StrongBodyLabel("快捷键列表"))
        tips = [
            ("F1", "激活/停用拾取模式", "激活后点击页面任意元素即可采集其选择器信息"),
            ("F2", "激活/停用高亮模式", "鼠标移动时高亮显示元素信息"),
            ("F3", "设置步骤名", "快速定位到步骤名输入框"),
            ("F4", "退出工具", "退出后浏览器保持运行，可重新连接"),
            ("Ctrl+S", "保存数据", "保存到 JSON 文件"),
            ("ESC", "关闭拾取", "退出拾取模式"),
        ]
        for key, name, desc in tips:
            col_layout.addWidget(BodyLabel(f"  {key:8s} {name:12s} {desc}"))

        col_layout.addWidget(StrongBodyLabel("操作步骤"))
        col_layout.addWidget(BodyLabel(
            "1. 启动浏览器（端口 18800）\n"
            "2. GUI 中设置 CDP 地址和输出文件名\n"
            "3. 点击「启动采集」- 按 F1 激活拾取模式\n"
            "4. 依次点击需要自动化的元素\n"
            "5. 在 UI 面板中填写步骤名（同一步骤的元素名需一致）\n"
            "6. 按 F4 退出并保存 → 文件输出到 docs/json/"))

        col_layout.addWidget(StrongBodyLabel("参数说明"))
        col_layout.addWidget(BodyLabel(
            "CDP 地址：浏览器调试端口，默认 http://127.0.0.1:18800\n"
            "输出文件名：自定义文件名，自动添加 .json 后缀\n"
            "超时时间：0 表示无限等待直到手动退出"))

        content_layout.addWidget(col_card)

        # ── 4. 数据清洗 ──
        cl_card = CardWidget(self)
        cl_layout = QVBoxLayout(cl_card)
        cl_layout.addWidget(StrongBodyLabel("四、数据清洗"))
        cl_layout.addWidget(BodyLabel(
            "selector_cleaner.py 读取原始 JSON，生成多策略定位信息（cleaned 字段）。"))

        cl_layout.addWidget(StrongBodyLabel("清洗规则"))
        rules = [
            "过滤动态 ID：el-id-5062-151、el-popper-container-5062 等动态 ID 被识别并过滤",
            "过滤动态 class：data-v-xxx、sc-xxx 等无用 class 被移除",
            "保留稳定 class：el-button、yy-table、tree__item 等有语义的 class 保留",
            "提取祖先锚点：从 ancestors 中提取稳定元素（role=dialog、id 稳定等）",
            "生成多策略：按优先级生成 anchored → text → placeholder → css → xpath",
            "标记可靠性：high（有锚定/文本）/ medium（仅 css）/ low（仅有动态选择器）",
        ]
        for r in rules:
            cl_layout.addWidget(BodyLabel(f"  • {r}"))

        cl_layout.addWidget(StrongBodyLabel("参数说明"))
        cl_layout.addWidget(BodyLabel(
            "输入：原始 JSON 文件（来自采集步骤，位于 docs/json/）\n"
            "输出：*_cleaned.json（自动保存到 docs/cleaned/）\n"
            "批量清洗：一键处理 docs/json/ 下所有未清洗文件"))

        content_layout.addWidget(cl_card)

        # ── 5. 动作配置 ──
        cfg_card = CardWidget(self)
        cfg_layout = QVBoxLayout(cfg_card)
        cfg_layout.addWidget(StrongBodyLabel("五、动作配置"))

        cfg_layout.addWidget(StrongBodyLabel("可视化编辑器（推荐）"))
        cfg_layout.addWidget(BodyLabel(
            "yaml_editor.html — 纯前端浏览器应用，无需安装。\n"
            "  • 左侧栏可加载多个 JSON 文件，切换编辑\n"
            "  • 按 step_name 分组展示，可视化编辑每个元素\n"
            "  • 支持添加/删除变量，导出 YAML 到 docs/yaml/"))

        cfg_layout.addWidget(StrongBodyLabel("动作参数详解"))
        params = [
            ("type", "操作类型",
             ["click — 点击", "fill — 填写文本", "select — 选择下拉选项",
              "hover — 悬浮", "check_exists — 检测元素是否存在",
              "check_visible — 检测元素可见", "wait_visible — 等待元素出现",
              "scroll_to — 滚动到元素位置", "locate_parent — 设为父元素容器",
              "screenshot — 截图区域"]),
            ("on_not_found", "找不到元素时的行为",
             ["fail — 标记为致命错误，终止流程",
              "skip — 跳过该元素，继续执行"]),
            ("wait_before", "操作前等待时间", ["浮点数（秒），默认 0.5"]),
            ("wait_after", "操作后等待时间", ["浮点数（秒），默认 0.5"]),
            ("wait_strategy", "操作后等待策略",
             ["timeout — 固定等待 wait_after 秒",
              "navigation — 等待页面加载完成（load 事件）",
              "element_appear — 等待 DOM 就绪（domcontentloaded）"]),
            ("wait_for_element", "是否先等待元素出现",
             ["true — 先 wait_for_selector，等元素出现再操作",
              "false — 直接定位"]),
            ("wait_timeout", "等待超时", ["整数（秒），默认 10"]),
            ("value", "输入值（fill/select 时使用）",
             ["普通文本或 ${变量名} 引用 vars.yaml"]),
            ("clear_first", "fill 前是否清空",
             ["true — 先清空再填入", "false — 直接填入"]),
            ("click_first", "是否先点击再输入",
             ["true — 先 click() 再 fill()，用于下拉搜索框、span 弹出输入框等",
              "false — 直接 fill()"]),
        ]
        for name, desc, values in params:
            cfg_layout.addWidget(BodyLabel(f"  {name}"))
            cfg_layout.addWidget(BodyLabel(f"    说明：{desc}"))
            for v in values:
                cfg_layout.addWidget(BodyLabel(f"      • {v}"))

        cfg_layout.addWidget(StrongBodyLabel("默认自动推断动作"))
        cfg_layout.addWidget(BodyLabel(
            "如果不配置动作，module_runner 会根据标签自动推断：\n"
            '  <input>/<textarea> → type: fill, value: ${INPUT_VALUE}\n'
            '  <button>/<a> → type: click（含"登录/提交/确认/保存"时 wait_strategy: navigation）\n'
            "  <select> → type: select\n"
            "  步骤名含「父元素」 → type: locate_parent\n"
            "  步骤名含「是否可见」 → type: check_exists\n"
            "  其他 → type: click\n"
            "  所有自动推断默认 on_not_found: skip"))

        content_layout.addWidget(cfg_card)

        # ── 6. 变量配置 ──
        var_card = CardWidget(self)
        var_layout = QVBoxLayout(var_card)
        var_layout.addWidget(StrongBodyLabel("六、变量配置（vars.yaml）"))
        var_layout.addWidget(BodyLabel(
            "变量文件位于项目根目录 vars.yaml，在动作 YAML 中用 ${变量名} 引用。"))

        var_layout.addWidget(StrongBodyLabel("示例"))
        var_layout.addWidget(BodyLabel(
            "# vars.yaml\n"
            "ACCOUNT: \"your_account\"\n"
            "PASSWORD: \"your_password\"\n"
            "SEARCH_KEYWORD: \"US\"\n"
            "INPUT_VALUE: \"测试内容\""))

        var_layout.addWidget(StrongBodyLabel("在动作中引用"))
        var_layout.addWidget(BodyLabel(
            "action:\n"
            "  type: fill\n"
            "  value: \"${ACCOUNT}\"    # 运行时替换为 your_account"))

        var_layout.addWidget(StrongBodyLabel("GUI 编辑"))
        var_layout.addWidget(BodyLabel(
            "在可视化编辑器（yaml_editor.html）中切换到「变量」标签页：\n"
            "  • 加载 vars.yaml → 编辑变量值\n"
            "  • 支持添加新变量、删除变量\n"
            "  • 保存后覆盖原文件"))

        content_layout.addWidget(var_card)

        # ── 7. 编排流程 ──
        flow_card = CardWidget(self)
        flow_layout = QVBoxLayout(flow_card)
        flow_layout.addWidget(StrongBodyLabel("七、流程编排"))

        flow_layout.addWidget(StrongBodyLabel("flow.yaml 基本结构"))
        flow_layout.addWidget(BodyLabel(
            "name: 流程名称\n"
            "pre_flows:            # 可选：前置流程\n"
            "  - flow_检查登录态.yaml\n"
            "modules:\n"
            "  - name: 模块名       # 显示名称\n"
            "    json: xxx_cleaned.json           # 元素数据（docs/cleaned/ 下）\n"
            "    yaml: actions_config_xxx.yaml     # 可选：动作配置（docs/yaml/ 下）"))

        flow_layout.addWidget(StrongBodyLabel("条件跳转（on_success / on_failure）"))
        flow_layout.addWidget(BodyLabel(
            "模块执行结果可分为「全部成功」和「有失败」两种，可配置不同跳转行为。"))

        flow_layout.addWidget(StrongBodyLabel("支持的动作"))
        flow_jumps = [
            ("goto", "跳转到指定模块", "target: 模块名"),
            ("skip_next", "跳过接下来 N 个模块", "count: N"),
            ("abort", "终止整个流程", "无参数"),
            ("retry_once", "自动重试一次", "仅 on_failure 可用"),
        ]
        for name, desc, param in flow_jumps:
            flow_layout.addWidget(BodyLabel(f"  {name:12s} {desc:16s} {param}"))

        flow_layout.addWidget(StrongBodyLabel("示例：检查登录态"))
        flow_layout.addWidget(BodyLabel(
            "modules:\n"
            "  - name: 检测是否处于登录态\n"
            "    on_failure:\n"
            "      action: goto\n"
            "      target: lingxing_elements_V10_登录    # 检测失败 → 跳转登录\n"
            "  - name: lingxing_elements_V10_退出登录     # 已登录则执行退出\n"
            "  - name: lingxing_elements_V10_登录         # 失败时跳转到此"))

        flow_layout.addWidget(StrongBodyLabel("前置流程（pre_flows）"))
        flow_layout.addWidget(BodyLabel(
            "在运行主流程前先执行前置流程的模块，适合登录态检查、环境初始化等：\n"
            "  pre_flows:\n"
            "    - flow_检查登录态.yaml       # 先检查登录\n"
            "    - flow_初始化环境.yaml        # 再初始化环境\n\n"
            "所有模块会合并到一个列表按顺序执行。"))

        flow_layout.addWidget(StrongBodyLabel("创建空白流程"))
        flow_layout.addWidget(BodyLabel(
            "在 GUI「编排」页面输入流程名称，点击「创建空白流程」，自动生成模板到 docs/flows/。"))

        content_layout.addWidget(flow_card)

        # ── 8. 运行说明 ──
        run_card = CardWidget(self)
        run_layout = QVBoxLayout(run_card)
        run_layout.addWidget(StrongBodyLabel("八、运行与交互"))

        run_layout.addWidget(StrongBodyLabel("命令行"))
        run_layout.addWidget(BodyLabel(
            "  python start_browser.py               # 单独启动浏览器\n"
            "  python debug_elements-V10.py --cdp http://127.0.0.1:18800  # 采集\n"
            "  python selector_cleaner.py <file.json>  # 清洗\n"
            "  python configure_actions.py <cleaned.json>  # CLI 配置\n"
            "  python module_runner.py <cleaned.json>  # 测试单个模块\n"
            "  python orchestrator.py <flow.yaml>     # 运行编排"))

        run_layout.addWidget(StrongBodyLabel("模块成功时"))
        run_layout.addWidget(BodyLabel(
            "✅ 模块执行完毕 → 弹出菜单（10 秒无操作自动继续）\n"
            "  i — 在此后插入一个新步骤\n"
            "  r — 回到模块重试菜单\n"
            "  c — 继续执行下一个模块"))

        run_layout.addWidget(StrongBodyLabel("模块失败时"))
        run_layout.addWidget(BodyLabel(
            "❌ 模块有 N 个元素失败 → 交互菜单：\n"
            "  r — 重试失败的 N 个元素\n"
            "  a — 全部重新执行此模块\n"
            "  h — 人工检查（浏览器保持，操作后回车）\n"
            "  n — 用新 JSON 替换此模块（热替换）\n"
            "  i — 在此模块后插入一个新步骤\n"
            "  s — 跳过失败，继续下一个模块\n"
            "  q — 终止整个流程"))

        content_layout.addWidget(run_card)

        # ── 9. 定位策略 ──
        loc_card = CardWidget(self)
        loc_layout = QVBoxLayout(loc_card)
        loc_layout.addWidget(StrongBodyLabel("九、元素定位策略"))

        loc_layout.addWidget(BodyLabel(
            "框架按以下顺序尝试定位元素，找到即停："))

        strategies = [
            ("1. anchored 锚定", "在指定容器内定位（如「在 el-dialog 内找 placeholder=搜索」）"),
            ("2. text 文本匹配", "用 get_by_text 精确匹配元素文本"),
            ("3. placeholder", "用 get_by_placeholder 匹配 input 的 placeholder"),
            ("4. aria_label", "用 aria-label 属性定位"),
            ("5. title", "用 title 属性定位"),
            ("6. name", "用 name 属性定位"),
            ("7. id", "用 CSS #id 定位（精确 + 前缀回退）"),
            ("8. css 选择器", "用 CSS 选择器定位"),
            ("9. xpath", "用 XPath 定位"),
            ("10. CDP 深度搜索", "通过 CDP 执行 JS 暴力遍历 DOM（穿透 Shadow DOM、iframe）"),
            ("11. OCR 识别", "截图 → Tesseract OCR → 找到文字坐标 → 点击（最后一层兜底）"),
        ]
        for title, desc in strategies:
            loc_layout.addWidget(BodyLabel(f"  {title}"))
            loc_layout.addWidget(BodyLabel(f"    {desc}"))

        loc_layout.addWidget(StrongBodyLabel("动态 ID 处理"))
        loc_layout.addWidget(BodyLabel(
            "以下模式被视为动态 ID，清洗时过滤，运行时用前缀匹配回退：\n"
            "  el-id-数字、el-popper-container-数字、el-overlay-数字\n"
            "  el-dialog__body-数字、含冒号:、纯数字、UUID 格式"))

        content_layout.addWidget(loc_card)

        # ── 10. 推荐用法 ──
        rec_card = CardWidget(self)
        rec_layout = QVBoxLayout(rec_card)
        rec_layout.addWidget(StrongBodyLabel("十、推荐工作流"))

        rec_layout.addWidget(BodyLabel(
            "▸ 日常使用：\n"
            "  python main.py   # 打开 GUI，按页面引导操作\n\n"
            "▸ 完整流程：\n"
            "  1. GUI「浏览器」→ 启动浏览器\n"
            "  2. GUI「采集」→ 连接浏览器，F1 拾取元素 → F4 保存\n"
            "  3. GUI「清洗」→ 选择原始 JSON → 清洗\n"
            "  4. GUI「配置」→ 打开可视化编辑器 → 配置动作 → 导出 YAML\n"
            "  5. GUI「编排」→ 创建/选择流程 → 运行\n\n"
            "▸ 快速测试：\n"
            "  python module_runner.py docs/cleaned/xxx_cleaned.json\n\n"
            "▸ 无头执行：\n"
            "  python orchestrator.py docs/flows/flow_xxx.yaml\n\n"
            "▸ 批量处理：\n"
            "  1. 浏览器中采集多个页面的元素\n"
            "  2. GUI「清洗」→ 批量清洗全部原始 JSON\n"
            "  3. GUI「编排」→ 创建流程 YAML，编写模块列表\n"
            "  4. 运行编排"))

        content_layout.addWidget(rec_card)

        # ── 11. 常见问题 ──
        faq_card = CardWidget(self)
        faq_layout = QVBoxLayout(faq_card)
        faq_layout.addWidget(StrongBodyLabel("十一、常见问题"))

        faqs = [
            ("找不到浏览器实例？",
             "确保已启动 Chrome 并开启 CDP（端口 18800），或点击「浏览器 → 启动浏览器」。"),
            ("元素定位不到？",
             "检查：① 是否在正确的页面上 ② 是否有弹窗/iframe 遮挡 ③ 尝试重新采集 + 清洗"),
            ("输入框找到但填不进去？",
             "设置 click_first: true，先点击激活再输入（用于下拉搜索框等场景）。"),
            ("动态 ID 导致定位失败？",
             "用 selector_cleaner.py 重新清洗，最新版本已处理 el-popper-container 等动态 ID。"),
            ("如何跳过非关键元素？",
             "在动作 YAML 中设置 on_not_found: skip。"),
            ("流程中断后如何恢复？",
             "浏览器保持打开，在编排菜单中选择：\n"
             "  n — 用新的 JSON 替换失败模块\n"
             "  i — 插入缺失的步骤\n"
             "  h — 人工操作后继续"),
            ("采集时采集到了工具自身的按钮？",
             "已修复：退出确认对话框内的按钮（#__pickerExitOverlay）会被自动过滤不采集。"),
        ]
        for q, a in faqs:
            faq_layout.addWidget(StrongBodyLabel(f"Q: {q}"))
            faq_layout.addWidget(BodyLabel(f"A: {a}"))

        content_layout.addWidget(faq_card)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)


# ════════════════════════════════════════════════════════════════
#  主窗口
# ════════════════════════════════════════════════════════════════

class MainWindow(FluentWindow):
    """主窗口 - 使用 qfluentwidgets FluentWindow"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("领星 ERP 自动化框架")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)

        # 创建各页面
        self.home_page = HomePage(self)
        self.help_page = HelpPage(self)
        self.browser_page = BrowserPage(self)
        self.collect_page = CollectPage(self)
        self.clean_page = CleanPage(self)
        self.configure_page = ConfigurePage(self)
        self.orchestrate_page = OrchestratePage(self)
        self.files_page = FilesPage(self)

        # 添加导航项
        self.addSubInterface(self.home_page, FluentIcon.HOME, "首页")
        self.addSubInterface(self.help_page, FluentIcon.HELP, "帮助",
                             position=NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.browser_page, FluentIcon.GLOBE, "浏览器")
        self.addSubInterface(self.collect_page, FluentIcon.CAMERA, "采集")
        self.addSubInterface(self.clean_page, FluentIcon.BROOM, "清洗")
        self.addSubInterface(self.configure_page, FluentIcon.SETTING, "配置")
        self.addSubInterface(self.orchestrate_page, FluentIcon.PLAY, "编排")
        self.addSubInterface(self.files_page, FluentIcon.FOLDER, "文件管理",
                             position=NavigationItemPosition.BOTTOM)

        # 连接首页快捷按钮
        self.home_page.btn_browser.clicked.connect(
            lambda: self.switch_to(self.browser_page.objectName()))
        self.home_page.btn_collect.clicked.connect(
            lambda: self.switch_to(self.collect_page.objectName()))
        self.home_page.btn_clean.clicked.connect(
            lambda: self.switch_to(self.clean_page.objectName()))
        self.home_page.btn_configure.clicked.connect(
            lambda: self.switch_to(self.configure_page.objectName()))
        self.home_page.btn_flow.clicked.connect(
            lambda: self.switch_to(self.orchestrate_page.objectName()))
        self.home_page.btn_editor.clicked.connect(
            self.configure_page.open_editor)
        self.home_page.btn_open_help.clicked.connect(
            lambda: self.switch_to(self.help_page.objectName()))

        # 浏览器页面连接
        self.browser_page.btn_start.clicked.connect(self.start_browser)
        self.browser_page.btn_stop.clicked.connect(self.stop_browser)

        # 采集页面连接
        self.collect_page.btn_collect.clicked.connect(self.collect_page.start_collect)
        self.collect_page.btn_stop_collect.clicked.connect(
            lambda: self.collect_page.runner.stop())

        # 状态栏
        self.status_bar = QLabel("就绪", self)
        self.status_bar.setStyleSheet("padding: 4px 16px; color: #888; font-size: 12px;")

        # 刷新首页统计
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.home_page.refresh_stats)
        self._refresh_timer.start(10000)

    def start_browser(self):
        bp = self.browser_page
        bp.btn_start.setEnabled(False)
        bp.btn_stop.setEnabled(True)
        bp.status_label.setText("启动中...")
        bp.status_label.setStyleSheet("color: #f77f00; font-weight: bold;")
        bp.log_output.clear()
        bp.log_output.append("▶ 启动浏览器...")
        bp.log_output.append(f"{'─'*50}")

        args = []
        if bp.cb_headless.isChecked():
            args = ["--headless"]

        bp.runner.run("python", ["start_browser.py"] + args,
                       output_widget=bp.log_output)

    def switch_to(self, object_name: str):
        """切换到指定导航页面"""
        self.navigationInterface.navigate(object_name)

    def stop_browser(self):
        bp = self.browser_page
        bp.log_output.append("\n⏹ 关闭浏览器...")
        # 通过 session 的 close 逻辑 - 直接发信号
        bp.runner.stop()


# ════════════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════════════

def main():
    # 高 DPI 缩放
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))

    # 创建 docs 目录
    for d in ["json", "cleaned", "yaml", "flows"]:
        os.makedirs(os.path.join(DOCS_DIR, d), exist_ok=True)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
