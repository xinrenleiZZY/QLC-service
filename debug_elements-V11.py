"""
领星(Lingxing) 页面元素调试工具 - 完整功能模块化集成版
保留所有原有功能：F1/F2/F3/F4、UI面板、步骤名、文件名、祖先元素等

集成方式：
  1. 作为独立工具：python debug_elements.py --cdp http://127.0.0.1:18800
  2. 作为 Python 模块：from debug_elements import ElementCollector
  3. 在你的框架中调用：collector.attach_and_collect()

V11 特性：保存时自动清洗，直接输出 *_cleaned.json
"""
# ── Windows GBK 编码兼容 ──
import sys, io
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'gb2312', 'cp936'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
import os
import sys
import argparse
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Browser

# ── 导入清洗引擎 ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
try:
    from selector_cleaner import clean_element
    HAS_CLEANER = True
except ImportError:
    HAS_CLEANER = False
    print("  [!] 未找到 selector_cleaner.py，将保存原始格式")

# ------------------------------------------------------------
#  全局共享状态
# ------------------------------------------------------------
class ElementCollector:
    """元素采集器 - 完整功能版，可连接到已有浏览器实例"""
    
    def __init__(self, cdp_url: str = None, output_file: str = "lingxing_elements.json"):
        self.cdp_url = cdp_url
        self.output_file = output_file
        self.playwright = None
        self.browser = None
        self.contexts = []
        
        # 采集状态（与JS同步）
        self.collected_items: List[Dict] = []
        self.is_active = False
        self.hover_mode = False
        self.step_name = ""
        self.save_filename = output_file
        
        # 退出标志
        self.exit_flag = False
        
    async def connect(self):
        """连接到已有的浏览器实例"""
        self.playwright = await async_playwright().start()
        
        if self.cdp_url:
            print(f"连接到浏览器: {self.cdp_url}")
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)
        else:
            # 尝试自动发现
            cdp_url = await self.discover_cdp()
            if cdp_url:
                self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url)
            else:
                raise Exception("未找到运行中的浏览器实例，请先启动浏览器或指定 --cdp URL")
        
        self.contexts = self.browser.contexts
        total_pages = sum(len(c.pages) for c in self.contexts)
        print(f"✅ 已连接到 {len(self.contexts)} 个上下文，{total_pages} 个页面")
        return self
    
    async def discover_cdp(self) -> Optional[str]:
        """自动发现 CDP 端口"""
        import socket
        import urllib.request
        
        common_ports = [18800, 9222, 9223, 9224, 9225]
        
        for port in common_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()
                
                if result == 0:
                    test_url = f"http://127.0.0.1:{port}/json/version"
                    try:
                        with urllib.request.urlopen(test_url, timeout=1) as f:
                            data = json.loads(f.read())
                            if 'webSocketDebuggerUrl' in data:
                                print(f"🔍 发现 CDP 端口: {port}")
                                return f"http://127.0.0.1:{port}"
                    except:
                        pass
            except:
                pass
        
        return None
    
    async def inject_picker(self):
        """注入完整版元素拾取器到所有现有页面和未来页面"""
        
        # 获取完整版注入脚本
        picker_script = self._get_full_picker_script()
        
        # 为所有现有上下文暴露 Python 函数
        for context in self.contexts:
            await context.expose_function("pySyncState", self._py_sync_state)
            
            # 为现有页面注入
            for page in context.pages:
                await page.evaluate(picker_script)
            
            # 为未来页面自动注入
            await context.add_init_script(script=picker_script)
        
        print("✅ 完整版元素拾取器已注入到所有页面")
        print("   - F1: 激活拾取模式 | F2: 高亮模式 | F3: 设置步骤名 | F4: 退出工具")
        print("   - Ctrl+S: 保存数据到文件")
        return self
    
    def _get_full_picker_script(self) -> str:
        """生成完整版注入脚本（保留所有原始功能）"""
        return r"""
        (async () => {
            if (window.__elementPickerInstalled) return;
            window.__elementPickerInstalled = true;
            if (window !== window.top) return;

            let state = await window.pySyncState("GET");

            let isActive = state.isActive;
            let hoverMode = state.hoverMode;
            let collectedCount = state.collected.length;
            let currentStepName = state.step_name || "";
            let currentSaveFilename = state.save_filename || "lingxing_elements.json";

            let lastHovered = null, hoverHighlight = null;
            let panel = null, fallbackBtn = null, content = null, modeLabel = null;

            function initUI() {
                if (!document.getElementById('__pickerPanel')) {
                    panel = document.createElement('div');
                    panel.id = '__pickerPanel';
                    panel.style.cssText = `position: fixed; top: calc(50vh - 200px); left: calc(50vw - 240px); width: 480px; max-height: 80vh; background: #1e1e1e; color: #d4d4d4; font-family: 'Consolas','Courier New',monospace; font-size: 12px; border-radius: 8px; box-shadow: 0 15px 50px rgba(0,0,0,0.6); z-index: 2147483647; overflow: hidden; display: none; flex-direction: column; border: 1px solid #444;`;

                    panel.innerHTML = `
                        <div style="padding:8px 12px;background:#2d2d2d;border-bottom:1px solid #333;display:flex;justify-content:space-between;align-items:center;cursor:move; user-select:none;" id="__pickerHeader">
                            <span style="color:#569cd6;font-weight:bold;">🔍 元素拾取器 (完整版)</span>
                            <span id="__pickerMode" style="color:#6a9955;font-size:11px;">[已暂停] 按 F1 激活</span>
                        </div>
                        <div style="padding:6px 12px;background:#2a2a2a;border-bottom:1px solid #333;display:flex;align-items:center;gap:6px;">
                            <span style="color:#888;font-size:11px;white-space:nowrap;">步骤名:</span>
                            <input id="__stepNameInput" type="text" value="${escapeHtml(currentStepName)}" placeholder="输入当前步骤名称" style="flex:1;background:#1e1e1e;color:#d4d4d4;border:1px solid #444;border-radius:4px;padding:4px 8px;font-size:11px;font-family:monospace;">
                            <button id="__stepNameSetBtn" style="background:#0e639c;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;">设置</button>
                            <button id="__stepNameClearBtn" style="background:#5a1d1d;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;">清空</button>
                        </div>
                        <div style="padding:6px 12px;background:#252526;border-bottom:1px solid #333;display:flex;align-items:center;gap:6px;">
                            <span style="color:#888;font-size:11px;white-space:nowrap;">文件名:</span>
                            <input id="__saveFilenameInput" type="text" value="${escapeHtml(currentSaveFilename)}" placeholder="保存文件名 (*.json)" style="flex:1;background:#1e1e1e;color:#dcdcaa;border:1px solid #444;border-radius:4px;padding:4px 8px;font-size:11px;font-family:monospace;">
                            <button id="__saveFilenameSetBtn" style="background:#0e639c;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;">设置</button>
                            <button id="__saveBtn" style="background:#4ec9b0;color:#1e1e1e;border:none;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:bold;">💾 保存</button>
                            <button id="__exitBtn" style="background:#ce9178;color:#1e1e1e;border:none;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:bold;">⏹ 退出工具</button>
                        </div>
                        <div id="__pickerContent" style="padding:12px;overflow-y:auto;flex:1;"></div>
                        <div style="padding:6px 12px;border-top:1px solid #333;font-size:11px;color:#888;display:flex;justify-content:space-between;align-items:center;">
                            <span>F1:拾取 | F2:高亮 | F3:命名 | F4:退出 | Ctrl+S:保存</span>
                            <div style="display:flex; align-items:center;">
                                <span id="__pickerCount" style="color:#dcdcaa;">全局采集: ${collectedCount}</span>
                                <span id="__pickerClearBtn" style="cursor:pointer; color:#ff6b6b; margin-left:12px; padding: 3px 8px; background: #3a3a3a; border-radius: 4px; transition: 0.2s;" title="清空所有记录">🗑️清空</span>
                            </div>
                        </div>`;
                    document.body.appendChild(panel);

                    const clearBtn = document.getElementById('__pickerClearBtn');
                    clearBtn.addEventListener('click', async function(e) {
                        e.stopPropagation();
                        collectedCount = await window.pySyncState("CLEAR_COLLECTED");
                        document.getElementById('__pickerCount').textContent = `全局采集: ${collectedCount}`;
                        const ct = document.getElementById('__pickerContent');
                        if (ct) ct.innerHTML = '<div style="color:#888;text-align:center;padding:20px;">✅ 全局记录已清空</div>';
                    });
                    clearBtn.onmouseover = () => clearBtn.style.background = '#555';
                    clearBtn.onmouseout = () => clearBtn.style.background = '#3a3a3a';

                    const stepInput = document.getElementById('__stepNameInput');
                    const stepSetBtn = document.getElementById('__stepNameSetBtn');
                    const stepClearBtn = document.getElementById('__stepNameClearBtn');
                    
                    function setStepName(name) {
                        currentStepName = name || '';
                        if (stepInput) stepInput.value = currentStepName;
                        window.pySyncState("SET_STEP_NAME", currentStepName);
                        if (currentStepName) {
                            if (modeLabel) modeLabel.textContent = `[步骤: ${currentStepName.substring(0, 20)}]`;
                        } else {
                            if (modeLabel && !isActive && !hoverMode) modeLabel.textContent = '[已暂停] 按 F1 激活';
                        }
                    }

                    if (stepSetBtn) {
                        stepSetBtn.onclick = function(e) { e.stopPropagation(); setStepName(stepInput.value.trim()); };
                    }
                    if (stepClearBtn) {
                        stepClearBtn.onclick = function(e) { e.stopPropagation(); setStepName(''); };
                    }
                    if (stepInput) {
                        stepInput.onkeydown = function(e) { if (e.key === 'Enter') { e.stopPropagation(); setStepName(stepInput.value.trim()); } };
                    }

                    const filenameInput = document.getElementById('__saveFilenameInput');
                    const filenameSetBtn = document.getElementById('__saveFilenameSetBtn');
                    const saveBtn = document.getElementById('__saveBtn');
                    const exitBtn = document.getElementById('__exitBtn');

                    function setSaveFilename(name) {
                        currentSaveFilename = name || 'lingxing_elements.json';
                        if (!currentSaveFilename.endsWith('.json')) currentSaveFilename += '.json';
                        if (filenameInput) filenameInput.value = currentSaveFilename;
                        window.pySyncState("SET_SAVE_FILENAME", currentSaveFilename);
                    }

                    if (filenameSetBtn) {
                        filenameSetBtn.onclick = function(e) { e.stopPropagation(); setSaveFilename(filenameInput.value.trim()); };
                    }
                    if (filenameInput) {
                        filenameInput.onkeydown = function(e) {
                            if (e.key === 'Enter') { e.stopPropagation(); setSaveFilename(filenameInput.value.trim()); }
                        };
                    }
                    if (saveBtn) {
                        saveBtn.onclick = function(e) { e.stopPropagation(); window.__pickerExport(); };
                    }
                    if (exitBtn) {
                        exitBtn.onclick = function(e) { e.stopPropagation(); window.__pickerExit(); };
                    }

                    let isDragging = false, dragOffsetX, dragOffsetY;
                    const header = document.getElementById('__pickerHeader');
                    header.addEventListener('mousedown', function(e) {
                        isDragging = true; dragOffsetX = e.clientX - panel.offsetLeft; dragOffsetY = e.clientY - panel.offsetTop;
                        document.addEventListener('mousemove', onDrag); 
                        document.addEventListener('mouseup', () => { isDragging = false; document.removeEventListener('mousemove', onDrag); }, {once: true});
                    });
                    function onDrag(e) { 
                        if (!isDragging) return; 
                        panel.style.left = (e.clientX - dragOffsetX) + 'px'; panel.style.top = (e.clientY - dragOffsetY) + 'px'; 
                        panel.style.right = 'auto'; panel.style.bottom = 'auto';
                    }
                }

                if (!document.getElementById('__pickerFallbackBtn')) {
                    fallbackBtn = document.createElement('div');
                    fallbackBtn.id = '__pickerFallbackBtn';
                    fallbackBtn.innerHTML = '🔍 开启拾取(F1) <span id="__pickerExitHint" style="font-size:10px;color:#888;margin-left:6px;font-weight:normal;">右键退出</span>';
                    fallbackBtn.style.cssText = `position: fixed; bottom: 30px; right: 30px; z-index: 2147483647; background: #4ec9b0; color: #1e1e1e; padding: 10px 16px; border-radius: 50px; cursor: pointer; font-weight: bold; font-family: system-ui; box-shadow: 0 4px 15px rgba(0,0,0,0.3); transition: all 0.2s; user-select: none; border: 2px solid #fff;`;
                    fallbackBtn.onclick = function(e) { e.stopPropagation(); window.__pickerToggle(); };
                    fallbackBtn.onmouseover = () => fallbackBtn.style.transform = 'scale(1.05)';
                    fallbackBtn.onmouseout = () => fallbackBtn.style.transform = 'scale(1)';
                    fallbackBtn.oncontextmenu = function(e) { e.preventDefault(); e.stopPropagation(); window.__pickerExit(); };
                    document.body.appendChild(fallbackBtn);
                }

                if (!document.getElementById('__pickerStyle')) {
                    const style = document.createElement('style');
                    style.id = '__pickerStyle';
                    style.textContent = `@keyframes __pickerFlash { 0% { opacity: 1; transform: scale(1); } 100% { opacity: 0; transform: scale(1.5); } }`;
                    document.head.appendChild(style);
                }

                content = document.getElementById('__pickerContent');
                modeLabel = document.getElementById('__pickerMode');

                if (isActive) { 
                    panel.style.display = 'flex'; 
                    if (modeLabel) { modeLabel.textContent = '[跨页激活] 持续记录中...'; modeLabel.style.color = '#4ec9b0'; }
                    if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
                } else if (hoverMode) { 
                    panel.style.display = 'flex'; 
                    if (modeLabel) { modeLabel.textContent = '[高亮激活] 鼠标移动查看'; modeLabel.style.color = '#ce9178'; }
                    if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
                }
            }

            setInterval(() => { if (document.body) initUI(); }, 1000);

            function getElementSelector(el) {
                if (el.id) return `#${CSS.escape(el.id)}`;
                const path = []; let current = el;
                while (current && current !== document.body && current !== document.documentElement) {
                    let selector = current.tagName.toLowerCase();
                    if (current.id) { path.unshift(`#${CSS.escape(current.id)}`); break; }
                    if (current.className && typeof current.className === 'string') {
                        const classes = current.className.trim().split(/\s+/).filter(c => c && !c.startsWith('el-') && c !== 'is-active' && c !== 'is-checked');
                        if (classes.length > 0) selector += '.' + classes.map(c => CSS.escape(c)).join('.');
                    }
                    const parent = current.parentElement;
                    if (parent) {
                        const siblings = Array.from(parent.children).filter(s => s.tagName === current.tagName);
                        if (siblings.length > 1) selector += `:nth-child(${siblings.indexOf(current) + 1})`;
                    }
                    path.unshift(selector); current = current.parentElement;
                }
                return path.join(' > ');
            }

            function getFullXPath(el) {
                const parts = [];
                let current = el;
                while (current && current !== document.documentElement) {
                    let idx = 1;
                    const tag = current.tagName.toLowerCase();
                    if (current.parentElement) {
                        const siblings = Array.from(current.parentElement.children).filter(s => s.tagName === current.tagName);
                        if (siblings.length > 1) {
                            idx = siblings.indexOf(current) + 1;
                        }
                    }
                    parts.unshift(`${tag}[${idx}]`);
                    current = current.parentElement;
                }
                parts.unshift('html[1]');
                return '/' + parts.join('/');
            }

            function getXPath(el) {
                if (el.id) return `//*[@id="${el.id}"]`;
                const parts = []; let current = el;
                while (current && current !== document.body && current !== document.documentElement) {
                    let idx = 0; const siblings = current.parentNode ? Array.from(current.parentNode.children).filter(s => s.tagName === current.tagName) : [];
                    if (siblings.length > 1) idx = siblings.indexOf(current) + 1;
                    const tag = current.tagName.toLowerCase();
                    if (current.id) { parts.unshift(`//*[@id="${current.id}"]`); break; } 
                    else if (idx > 0) parts.unshift(`${tag}[${idx}]`); 
                    else parts.unshift(tag);
                    current = current.parentNode;
                }
                return '/' + parts.join('/');
            }

            function getAllSelectors(el) {
                return {
                    tag: el.tagName.toLowerCase(), id: el.id || null, class: Array.from(el.classList).join(' ') || null,
                    text: (el.textContent || '').trim().substring(0, 100) || null, placeholder: el.getAttribute('placeholder') || null,
                    type: el.getAttribute('type') || null, name: el.getAttribute('name') || null,
                    'data-*': (() => {
                        const d = {}; for (const a of el.attributes) if (a.name.startsWith('data-')) d[a.name] = a.value;
                        return Object.keys(d).length ? d : null;
                    })(),
                    css_selector: getElementSelector(el),
                    xpath_short: getXPath(el),
                    xpath_full: getFullXPath(el),
                    playwright_selector: (() => {
                        if (el.id) return `page.locator("#${CSS.escape(el.id)}")`;
                        const t = (el.textContent || '').trim().substring(0, 50);
                        if (t && ['button','a','span','label','div'].includes(el.tagName.toLowerCase())) return `page.getByText("${t}", { exact: true })`;
                        if (el.getAttribute('placeholder')) return `page.getByPlaceholder("${el.getAttribute('placeholder')}")`;
                        return getFullXPath(el);
                    })(),
                    rect: el.getBoundingClientRect(), inner_text: (el.innerText || '').trim().substring(0, 80) || null,
                };
            }

            function getStableAncestors(el) {
                const ancestors = [];
                let current = el.parentElement;
                let depth = 0;
                const maxDepth = 8;
                
                while (current && current !== document.body && depth < maxDepth) {
                    const info = {
                        tag: current.tagName.toLowerCase(),
                        id: current.id || null,
                        class: (current.className && typeof current.className === 'string') 
                            ? current.className.trim() : null,
                        text: (current.textContent || '').trim().substring(0, 50) || null,
                        role: current.getAttribute('role') || null,
                        aria_label: current.getAttribute('aria-label') || null,
                        depth: depth + 1,
                    };
                    
                    info.is_stable_anchor = (
                        (info.id && !info.id.includes('el-id-') && !info.id.includes(':')) ||
                        info.role === 'dialog' ||
                        info.role === 'alertdialog' ||
                        info.class && info.class.includes('el-dialog') ||
                        info.tag === 'form' ||
                        info.role === 'form' ||
                        info.id === 'yy-table' ||
                        info.id === 'yy-layout-content' ||
                        info.aria_label
                    );
                    
                    if (info.is_stable_anchor || info.id || info.role || info.aria_label) {
                        ancestors.push(info);
                    }
                    
                    current = current.parentElement;
                    depth++;
                }
                
                return ancestors;
            }
            
            const escapeHtml = (str) => str ? str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;') : '';

            function showElementInfo(el) {
                if (!content) return;
                const info = getAllSelectors(el);
                const lines = [
                    `<div style="color:#569cd6;font-weight:bold;margin-bottom:8px;font-size:14px;">&lt;${info.tag}&gt; ${info.text ? ' - ' + escapeHtml(info.text.substring(0, 60)) : ''}</div>`,
                    `<table style="width:100%;border-collapse:collapse;">`,
                    ...Object.entries(info).filter(([k,v]) => v && k !== 'rect' && k !== 'inner_text').map(([k,v]) => {
                        const val = typeof v === 'string' ? escapeHtml(v) : JSON.stringify(v);
                        const color = k === 'playwright_selector' ? '#ce9178' : k === 'xpath_full' ? '#ff6b6b' : k === 'xpath_short' ? '#6a9955' : k === 'css_selector' ? '#dcdcaa' : '#9cdcfe';
                        return `<tr><td style="padding:2px 8px 2px 0;color:#888;white-space:nowrap;vertical-align:top;">${k}</td><td style="padding:2px 0;color:${color};word-break:break-all;font-size:11px;"><code style="background:#2d2d2d;padding:1px 4px;border-radius:3px;">${val}</code></td></tr>`;
                    }),
                    `</table><hr style="border-color:#333;margin:8px 0;">`,
                    `<div style="color:#6a9955;font-size:11px;">位置: (${Math.round(info.rect.left)}, ${Math.round(info.rect.top)}) - 大小: ${Math.round(info.rect.width)}x${Math.round(info.rect.height)}</div>`
                ];
                content.innerHTML = lines.join('\n');
            }

            function highlightElement(el) {
                if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; }
                const rect = el.getBoundingClientRect(); const hl = document.createElement('div'); hl.id = '__hoverHighlight';
                hl.style.cssText = `position: fixed; pointer-events: none; z-index: 2147483646; border: 2px solid #ff6b6b; background: rgba(255,107,107,0.08); border-radius: 2px; transition: all 0.1s; left: ${rect.left}px; top: ${rect.top}px; width: ${rect.width}px; height: ${rect.height}px;`;
                const tip = document.createElement('div');
                tip.style.cssText = `position: fixed; pointer-events: none; z-index: 2147483647; background: #1e1e1e; color: #d4d4d4; font-size: 11px; padding: 4px 8px; border-radius: 4px; font-family: monospace; left: ${rect.left}px; top: ${rect.bottom + 4}px; border: 1px solid #333; max-width: 400px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;`;
                const tag = el.tagName.toLowerCase(); const text = (el.textContent || '').trim().substring(0, 40);
                const selector = el.id ? `#${el.id}` : (el.className ? `.${el.className.split(' ')[0]}` : tag);
                tip.textContent = `<${tag}> ${selector} ${text ? '| ' + text : ''}`;
                hl.appendChild(tip); document.body.appendChild(hl); hoverHighlight = hl;
            }

            function onMouseMove(e) { 
                if (!hoverMode) return; 
                const el = document.elementFromPoint(e.clientX, e.clientY); 
                if (el && el !== lastHovered && el !== panel && el !== fallbackBtn && (!panel || !panel.contains(el))) { 
                    lastHovered = el; highlightElement(el); 
                } 
            }

            function onClick(e) {
                if (!isActive && !hoverMode) return; 
                const el = e.target; 
                if (el === panel || (panel && panel.contains(el)) || el === fallbackBtn) return;
                // 退出确认对话框内的按钮不采集
                const exitOverlay = document.getElementById('__pickerExitOverlay');
                if (exitOverlay && exitOverlay.contains(el)) return;

                showElementInfo(el);

                const item = { 
                    time: new Date().toISOString(), 
                    step_name: currentStepName || "", 
                    page_url: window.location.href,    
                    page_title: document.title,        
                    selectors: getAllSelectors(el),
                    ancestors: getStableAncestors(el),
                };

                window.pySyncState("ADD_COLLECTED", item).then(total => {
                    collectedCount = total;
                    const countSpan = document.getElementById('__pickerCount');
                    if (countSpan) countSpan.textContent = `全局采集: ${collectedCount}`;
                });

                const flash = document.createElement('div'); const rect = el.getBoundingClientRect();
                flash.style.cssText = `position: fixed; pointer-events: none; z-index: 2147483647; border: 3px solid #ff0055; border-radius: 2px; left: ${rect.left}px; top: ${rect.top}px; width: ${rect.width}px; height: ${rect.height}px; animation: __pickerFlash 0.5s ease-out;`;
                document.body.appendChild(flash); setTimeout(() => flash.remove(), 500);
            }

            window.__pickerToggle = function() {
                if (!panel) initUI();
                isActive = !isActive; hoverMode = false;

                window.pySyncState("SET_ACTIVE", isActive);

                if (isActive) { 
                    document.addEventListener('click', onClick, true); 
                    document.removeEventListener('mousemove', onMouseMove, true);
                    if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; }
                    if (modeLabel) { modeLabel.textContent = '[无损拾取激活] 可正常操作网页'; modeLabel.style.color = '#4ec9b0'; }
                    if (panel) panel.style.display = 'flex'; 
                    if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
                } else { 
                    document.removeEventListener('click', onClick, true); 
                    if (modeLabel) { modeLabel.textContent = '[已暂停] 按 F1/F2 激活'; modeLabel.style.color = '#6a9955'; }
                    if (fallbackBtn) { fallbackBtn.innerHTML = '🔍 开启拾取(F1)'; fallbackBtn.style.background = '#4ec9b0'; }
                }
            };

            window.__pickerToggleHover = function() {
                if (!panel) initUI();
                hoverMode = !hoverMode; isActive = false;

                window.pySyncState("SET_HOVER", hoverMode);

                if (hoverMode) { 
                    document.addEventListener('mousemove', onMouseMove, true); 
                    document.addEventListener('click', onClick, true); 
                    if (modeLabel) { modeLabel.textContent = '[悬停高亮激活] 鼠标移动查看'; modeLabel.style.color = '#ce9178'; }
                    if (panel) panel.style.display = 'flex'; 
                    if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
                } else { 
                    document.removeEventListener('mousemove', onMouseMove, true); 
                    document.removeEventListener('click', onClick, true); 
                    if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; } lastHovered = null; 
                    if (modeLabel) { modeLabel.textContent = '[已暂停] 按 F1/F2 激活'; modeLabel.style.color = '#6a9955'; }
                    if (fallbackBtn) { fallbackBtn.innerHTML = '🔍 开启拾取(F1)'; fallbackBtn.style.background = '#4ec9b0'; }
                }
            };

            window.__pickerExport = async function() {
                let fullState = await window.pySyncState("GET");
                let allData = fullState.collected;

                if (allData.length === 0) return alert("全局暂未采集到任何元素！");

                const savedPath = await window.pySyncState("SAVE_FILE");
                alert(`✅ 保存成功！\n\n共导出 ${allData.length} 个元素节点\n文件已直接存入你的项目目录:\n${savedPath}`);
            };

            window.__pickerExit = async function() {
                const overlay = document.createElement('div');
                overlay.id = '__pickerExitOverlay';
                overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:2147483647;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;';
                overlay.innerHTML = `
                    <div style="background:#1e1e1e;color:#d4d4d4;padding:24px 32px;border-radius:8px;box-shadow:0 10px 40px rgba(0,0,0,0.5);text-align:center;border:1px solid #444;min-width:320px;">
                        <div style="font-size:18px;margin-bottom:16px;color:#ce9178;">⏹ 确认退出工具</div>
                        <div style="margin-bottom:20px;font-size:14px;color:#aaa;">退出工具后浏览器将保持运行，可重新连接。</div>
                        <div style="display:flex;gap:12px;justify-content:center;">
                            <button id="__pickerExitConfirm" style="background:#ce9178;color:#1e1e1e;border:none;padding:8px 24px;border-radius:4px;cursor:pointer;font-size:14px;font-weight:bold;">确定退出</button>
                            <button id="__pickerExitCancel" style="background:#3a3a3a;color:#d4d4d4;border:1px solid #555;padding:8px 24px;border-radius:4px;cursor:pointer;font-size:14px;">取消</button>
                        </div>
                    </div>`;
                document.body.appendChild(overlay);

                const result = await new Promise(resolve => {
                    document.getElementById('__pickerExitConfirm').onclick = () => resolve(true);
                    document.getElementById('__pickerExitCancel').onclick = () => resolve(false);
                    overlay.onclick = (e) => { if (e.target === overlay) resolve(false); };
                });

                overlay.remove();
                if (result) {
                    await window.pySyncState("EXIT");
                }
            };

            window.addEventListener('keydown', function(e) {
                if (e.key === 'F1') { e.preventDefault(); e.stopPropagation(); window.__pickerToggle(); } 
                else if (e.key === 'F2') { e.preventDefault(); e.stopPropagation(); window.__pickerToggleHover(); } 
                else if (e.key === 'F3') { e.preventDefault(); e.stopPropagation(); 
                    const inp = document.getElementById('__stepNameInput'); if (inp) { inp.focus(); inp.select(); } 
                }
                else if (e.key === 'F4') { e.preventDefault(); e.stopPropagation(); window.__pickerExit(); }
                else if (e.key === 'Escape') {
                    isActive = false; hoverMode = false;
                    window.pySyncState("SET_ACTIVE", false);

                    document.removeEventListener('click', onClick, true);
                    document.removeEventListener('mousemove', onMouseMove, true);
                    if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; }
                    if (panel) panel.style.display = 'none';
                    if (fallbackBtn) { fallbackBtn.innerHTML = '🔍 开启拾取(F1)'; fallbackBtn.style.background = '#4ec9b0'; }
                }
                else if (e.ctrlKey && e.key === 's') { e.preventDefault(); window.__pickerExport(); }
            }, true); 

            if (isActive) {
                document.addEventListener('click', onClick, true); 
            } else if (hoverMode) {
                document.addEventListener('mousemove', onMouseMove, true); 
                document.addEventListener('click', onClick, true); 
            }

            console.log('%c[元素拾取器] 完整版已就绪，后台写文件特权已开启！', 'color:#4ec9b0;font-weight:bold;font-size:14px;');
        })();
        """
    
    async def _py_sync_state(self, action: str, payload=None):
        """Python 后端接口，与 JS 通信"""
        if action == "GET":
            return {
                "collected": self.collected_items,
                "isActive": self.is_active,
                "hoverMode": self.hover_mode,
                "step_name": self.step_name,
                "save_filename": self.save_filename
            }
        elif action == "ADD_COLLECTED":
            self.collected_items.append(payload)
            print(f"  ✅ 已采集: {payload['selectors']['tag']} - {payload.get('step_name', '无步骤')}")
            return len(self.collected_items)
        elif action == "CLEAR_COLLECTED":
            self.collected_items = []
            print("  🗑️ 已清空所有采集记录")
            return 0
        elif action == "SET_ACTIVE":
            self.is_active = payload
            self.hover_mode = False
            status = "激活" if payload else "停用"
            print(f"  📌 拾取模式已{status}")
            return "ok"
        elif action == "SET_HOVER":
            self.hover_mode = payload
            self.is_active = False
            status = "激活" if payload else "停用"
            print(f"  🔍 高亮模式已{status}")
            return "ok"
        elif action == "SET_STEP_NAME":
            self.step_name = payload
            print(f"  📝 步骤名已设置为: {payload}")
            return self.step_name
        elif action == "SET_SAVE_FILENAME":
            self.save_filename = payload
            print(f"  💾 保存文件名已设置为: {payload}")
            return self.save_filename
        elif action == "SAVE_FILE":
            return await self.save()
        elif action == "EXIT":
            self.exit_flag = True
            print("\n  ⏹️ 用户要求退出工具")
            return "OK"
        return None
    
    async def save(self, filename: str = None) -> str:
        """保存采集结果到文件（自动清洗，输出 *_cleaned.json）"""
        output = filename or self.save_filename

        # 确保是 JSON 文件
        if not output.endswith('.json'):
            output += '.json'

        # 去掉可能已有的 _cleaned 后缀（避免重复）
        stem = output.replace('.json', '').replace('_cleaned', '')
        raw_name = f"{stem}.json"
        cleaned_name = f"{stem}_cleaned.json"

        project_dir = os.path.dirname(os.path.abspath(__file__))
        docs_json = os.path.join(project_dir, "docs", "json")
        docs_cleaned = os.path.join(project_dir, "docs", "cleaned")
        os.makedirs(docs_json, exist_ok=True)
        os.makedirs(docs_cleaned, exist_ok=True)

        raw_path = os.path.join(docs_json, raw_name)
        cleaned_path = os.path.join(docs_cleaned, cleaned_name)

        # ── 1. 保存原始数据（到 docs/json/）──
        with open(raw_path, 'w', encoding='utf-8') as f:
            json.dump(self.collected_items, f, ensure_ascii=False, indent=2)
        print(f"\n[+] 原始数据已保存: {raw_path}")

        # ── 2. 清洗并保存（到 docs/cleaned/）──
        cleaned_items = []
        if HAS_CLEANER and self.collected_items:
            print(f"    正在清洗 {len(self.collected_items)} 个元素...")
            for i, item in enumerate(self.collected_items):
                try:
                    # 与 selector_cleaner.clean_file() 一致：
                    # 保留原始全部字段，新增 cleaned 字段
                    cleaned = dict(item)  # 复制原始元素
                    cleaned["cleaned"] = clean_element(item)
                    cleaned_items.append(cleaned)
                except Exception as e:
                    print(f"    [WARN] 元素 {i} 清洗失败: {e}")
                    cleaned_items.append(dict(item))  # 原始数据兜底
            print(f"    [+] 清洗完成")
        else:
            cleaned_items = [dict(item) for item in self.collected_items]

        with open(cleaned_path, 'w', encoding='utf-8') as f:
            json.dump(cleaned_items, f, ensure_ascii=False, indent=2)

        print(f"[+] 清洗后数据已保存: {cleaned_path}")
        print(f"    [+] 共 {len(cleaned_items)} 个元素")
        if HAS_CLEANER:
            high = sum(1 for d in cleaned_items if d.get("cleaned", {}).get("reliability") == "high")
            print(f"    [+] 可靠性: high={high} total={len(cleaned_items)}")

        return cleaned_path
    
    def get_collected_selectors(self) -> List[Dict]:
        """获取所有采集的选择器（供自动化使用）"""
        return [
            {
                'step_name': item.get('step_name', ''),
                'page_url': item['page_url'],
                'page_title': item.get('page_title', ''),
                'time': item.get('time', ''),
                'selector': item['selectors']['css_selector'],
                'xpath_short': item['selectors'].get('xpath_short', ''),
                'xpath_full': item['selectors'].get('xpath_full', ''),
                'playwright_selector': item['selectors'].get('playwright_selector', ''),
                'tag': item['selectors']['tag'],
                'text': item['selectors'].get('text', ''),
                'id': item['selectors'].get('id', ''),
                'class': item['selectors'].get('class', ''),
                'ancestors': item.get('ancestors', [])
            }
            for item in self.collected_items
        ]
    
    async def wait_for_interaction(self, timeout: int = 0):
        """等待用户交互（F4 退出或超时）"""
        print(f"\n{'='*60}")
        print("🎯 元素拾取器已启动，完整功能已就绪！")
        print("   - F1: 激活/停用拾取模式")
        print("   - F2: 激活/停用高亮模式")
        print("   - F3: 快速设置步骤名")
        print("   - F4: 退出工具（浏览器保持运行）")
        print("   - Ctrl+S: 保存采集数据")
        print("   - ESC: 关闭拾取模式")
        print(f"{'='*60}\n")
        
        if timeout > 0:
            print(f"⏰ 自动超时: {timeout} 秒后自动保存并退出\n")
        
        try:
            if timeout > 0:
                await asyncio.sleep(timeout)
                print(f"\n⏰ 超时 {timeout} 秒，自动保存并退出")
            else:
                while not self.exit_flag:
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            print("\n⚠️ 用户中断")
        
        print(f"\n📊 共采集 {len(self.collected_items)} 个元素")
        return self.collected_items
    
    async def disconnect(self):
        """断开连接（不关闭浏览器）"""
        if self.playwright:
            await self.playwright.stop()
            print("🔌 已断开与浏览器的连接")


# ------------------------------------------------------------
#  便捷函数：一键采集
# ------------------------------------------------------------
async def collect_elements(
    cdp_url: str = None,
    output_file: str = "lingxing_elements.json",
    timeout: int = 0,
    auto_save: bool = True
) -> List[Dict]:
    """
    连接到浏览器并采集元素（完整功能版）
    
    Args:
        cdp_url: 浏览器 CDP URL，如 http://127.0.0.1:18800，不指定则自动发现
        output_file: 输出文件路径
        timeout: 等待超时（秒），0 表示无限等待直到用户按 F4
        auto_save: 是否自动保存
    
    Returns:
        采集到的元素列表（简化版，便于自动化使用）
    """
    collector = ElementCollector(cdp_url=cdp_url, output_file=output_file)
    
    try:
        await collector.connect()
        await collector.inject_picker()
        await collector.wait_for_interaction(timeout=timeout)
        
        if auto_save and collector.collected_items:
            await collector.save()
        
        return collector.get_collected_selectors()
    
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
        if auto_save and collector.collected_items:
            await collector.save()
        return collector.get_collected_selectors()
    
    finally:
        await collector.disconnect()


# ------------------------------------------------------------
#  命令行入口
# ------------------------------------------------------------
async def main_async():
    parser = argparse.ArgumentParser(description="元素拾取器 - 完整功能版")
    parser.add_argument("--cdp", help="CDP URL，如 http://127.0.0.1:18800")
    parser.add_argument("--output", default="lingxing_elements.json", help="输出文件")
    parser.add_argument("--timeout", type=int, default=0, help="等待超时（秒），0=无限")
    
    args = parser.parse_args()
    
    await collect_elements(
        cdp_url=args.cdp,
        output_file=args.output,
        timeout=args.timeout
    )


def main():
    asyncio.run(main_async())


# ------------------------------------------------------------
#  在你的框架中集成示例
# ------------------------------------------------------------
"""
在 orchestrator.py 中添加元素采集模块:

from debug_elements import collect_elements

class ElementCollectionModule:
    async def execute(self, session, config):
        '''元素采集模块'''
        
        # 从 session 获取浏览器的 CDP URL
        cdp_url = session.get_cdp_url()  # 需要在 session.py 中实现
        
        # 启动采集（用户手动点击元素）
        elements = await collect_elements(
            cdp_url=cdp_url,
            output_file=config.get('output', 'collected.json'),
            timeout=config.get('timeout', 0)
        )
        
        # 保存到 session 供其他模块使用
        session.collected_elements = elements
        
        # 返回结果
        return {
            'success': len(elements) > 0,
            'count': len(elements),
            'elements': elements
        }

# 在 session.py 中需要暴露 CDP URL:
class BrowserSession:
    def __init__(self):
        self.browser = None
        self.cdp_port = 18800

    async def create(self):
        # 启动浏览器时开启 CDP
        self.browser = await p.chromium.launch_persistent_context(
            user_data_dir="./browser_profile",
            args=[f"--remote-debugging-port={self.cdp_port}"],
            ...
        )
        self.cdp_url = f"http://127.0.0.1:{self.cdp_port}"

    def get_cdp_url(self):
        return self.cdp_url
"""

if __name__ == "__main__":
    main()