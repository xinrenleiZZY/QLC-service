import asyncio
import json
import os
from datetime import datetime
from typing import Optional, Callable, Any
from playwright.async_api import Page, Locator

class CDPRetryConfig:
    """CDP重试配置"""
    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 10.0
    backoff_factor: float = 2.0
    jitter: float = 0.1
    
class ElementState:
    """元素状态枚举"""
    VISIBLE = "visible"
    HIDDEN = "hidden"
    ENABLED = "enabled"
    DISABLED = "disabled"
    STABLE = "stable"

class CDPRecoveryManager:
    """CDP恢复管理器 - 提供高可靠性执行"""
    
    def __init__(self, page: Page, state_file: str = "state/flow_state.json"):
        self.page = page
        self.state_file = state_file
        self.retry_config = CDPRetryConfig()
        self._load_state()
    
    def _load_state(self):
        """加载持久化状态"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                self.state = json.load(f)
        else:
            self.state = {
                "last_successful_step": -1,
                "completed_steps": [],
                "failed_steps": [],
                "step_data": {},
                "start_time": datetime.now().isoformat()
            }
    
    def _save_state(self):
        """保存状态"""
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    async def wait_for_element_state(
        self, 
        locator: Locator, 
        expected_state: str,
        timeout: int = 30000
    ) -> bool:
        """等待元素达到指定状态"""
        try:
            if expected_state == ElementState.VISIBLE:
                await locator.wait_for(state="visible", timeout=timeout)
            elif expected_state == ElementState.HIDDEN:
                await locator.wait_for(state="hidden", timeout=timeout)
            elif expected_state == ElementState.ENABLED:
                await self._wait_for_enabled(locator, timeout)
            elif expected_state == ElementState.STABLE:
                await self._wait_for_stable(locator, timeout)
            return True
        except Exception:
            return False
    
    async def _wait_for_enabled(self, locator: Locator, timeout: int):
        """等待元素启用"""
        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) * 1000 < timeout:
            if await locator.is_enabled():
                return True
            await asyncio.sleep(0.1)
        return False
    
    async def _wait_for_stable(self, locator: Locator, timeout: int):
        """等待元素位置稳定（无移动）"""
        start = asyncio.get_event_loop().time()
        last_box = None
        stable_count = 0
        while (asyncio.get_event_loop().time() - start) * 1000 < timeout:
            try:
                box = await locator.bounding_box()
                if box and last_box and box == last_box:
                    stable_count += 1
                    if stable_count >= 3:  # 连续3次位置不变
                        return True
                last_box = box
            except:
                pass
            await asyncio.sleep(0.2)
        return False
    
    async def execute_with_retry(
        self,
        action: Callable,
        action_name: str,
        max_retries: int = None,
        retry_conditions: list = None
    ) -> tuple[bool, Any]:
        """
        带CDP重试的动作执行
        
        Args:
            action: 异步函数，执行实际操作
            action_name: 动作名称（用于日志）
            max_retries: 最大重试次数
            retry_conditions: 可重试的异常类型列表
        
        Returns:
            (success, result)
        """
        max_retries = max_retries or self.retry_config.max_retries
        retry_conditions = retry_conditions or [Exception]
        
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                # 执行动作前检查页面状态
                if not await self._check_page_ready():
                    raise Exception("页面未就绪")
                
                result = await action()
                
                # 执行后验证
                if await self._validate_action_result(action_name):
                    self.state["last_successful_step"] = self.state.get("current_step", -1)
                    self._save_state()
                    return True, result
                
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = min(
                        self.retry_config.base_delay * (self.retry_config.backoff_factor ** (attempt - 1)),
                        self.retry_config.max_delay
                    )
                    delay += self.retry_config.jitter * attempt
                    
                    print(f"  ⚠️  {action_name} 失败 (第{attempt}次): {e}")
                    print(f"     等待 {delay:.1f}s 后重试...")
                    
                    # 尝试恢复页面状态
                    await self._recover_page_state()
                    await asyncio.sleep(delay)
                else:
                    self.state["failed_steps"].append({
                        "step": action_name,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    })
                    self._save_state()
        
        return False, last_error
    
    async def _check_page_ready(self) -> bool:
        """检查页面是否就绪"""
        try:
            ready_state = await self.page.evaluate("document.readyState")
            return ready_state == "complete"
        except:
            return False
    
    async def _validate_action_result(self, action_name: str) -> bool:
        """验证动作执行结果"""
        # 可扩展：根据动作类型验证不同条件
        return True
    
    async def _recover_page_state(self):
        """尝试恢复页面状态"""
        try:
            # 关闭可能存在的遮罩层
            await self.page.evaluate("""
                document.querySelectorAll('.el-loading-mask, .v-loading-mask').forEach(el => el.remove());
            """)
            # 滚动到顶部
            await self.page.evaluate("window.scrollTo(0, 0);")
            await asyncio.sleep(0.5)
        except:
            pass
    
    def get_resume_step(self) -> int:
        """获取可恢复的步骤索引"""
        return self.state["last_successful_step"] + 1