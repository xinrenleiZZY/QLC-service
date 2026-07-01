"""
pages/utils.py — 跨页面共享的工具函数和组件
"""
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal, QProcess, QTimer, QUrl
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QWidget, QTextEdit

# ── 项目路径 ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")

def ensure_docs():
    for d in ["json", "cleaned", "yaml", "flows"]:
        os.makedirs(os.path.join(DOCS_DIR, d), exist_ok=True)

def list_json_files(directory: str) -> list:
    p = Path(directory)
    return sorted([f.name for f in p.glob("*.json")])

def list_yaml_files(directory: str) -> list:
    p = Path(directory)
    return sorted([f.name for f in p.glob("*.yaml")] + [f.name for f in p.glob("*.yml")])

def list_all_cleaned_files() -> list:
    return list_json_files(os.path.join(DOCS_DIR, "cleaned"))

def list_all_flow_files() -> list:
    return list_yaml_files(os.path.join(DOCS_DIR, "flows"))

def list_all_raw_files() -> list:
    return list_json_files(os.path.join(DOCS_DIR, "json"))

def file_size_str(filepath: str) -> str:
    try:
        size = os.path.getsize(filepath)
        if size < 1024: return f"{size} B"
        elif size < 1024*1024: return f"{size/1024:.1f} KB"
        else: return f"{size/1024/1024:.1f} MB"
    except:
        return "?"


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
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=self.working_dir, text=True,
                encoding='utf-8', errors='replace', bufsize=1
            )
            for line in iter(self._process.stdout.readline, ''):
                if line: self.output.emit(line.rstrip())
            self._process.wait()
            self.finished.emit(self._process.returncode)
        except Exception as e:
            self.output.emit(f"错误: {e}")
            self.finished.emit(-1)

    def stop(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try: self._process.wait(timeout=3)
            except: self._process.kill()


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
            cwd: str = None, finished_callback=None):
        self._output_widget = output_widget
        self._finished_callback = finished_callback
        self._running = True
        if output_widget: output_widget.clear()
        work_dir = cwd or PROJECT_ROOT
        self.process.setWorkingDirectory(work_dir)
        self.process.start(command, args)

    def _on_output(self):
        if self._output_widget:
            raw = self.process.readAllStandardOutput().data()
            data = raw.decode('utf-8', errors='replace')
            self._output_widget.moveCursor(QTextCursor.End)
            self._output_widget.insertPlainText(data)
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
    def running(self): return self._running
