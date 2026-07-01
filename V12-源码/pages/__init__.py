"""
pages/__init__.py
V12 页面模块 — 各页面独立文件。

导出所有 Page 类供 main.py 导入。
"""
from .home_page import HomePage
from .browser_page import BrowserPage
from .collect_page import CollectPage
from .clean_page import CleanPage
from .configure_page import ConfigurePage
from .orchestrate_page import OrchestratePage
from .files_page import FilesPage
from .help_page import HelpPage

__all__ = [
    "HomePage", "BrowserPage", "CollectPage", "CleanPage",
    "ConfigurePage", "OrchestratePage", "FilesPage", "HelpPage",
]
