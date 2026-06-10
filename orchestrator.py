"""
orchestrator.py - 流程编排器（模块组合 + 失败重试 + 人工介入）
==============================================================

职责:
  - 定义流程 flow.yaml（模块列表 + 执行顺序）
  - 依次执行每个模块（共享同一浏览器会话）
  - 失败时：可重试该模块 / 跳过 / 终止
  - 浏览器保持打开直到全部完成

用法:
    python orchestrator.py <flow.yaml>
    python orchestrator.py flows/批量创建关键词.yaml

流程定义文件 (flow.yaml):
    name: 批量创建关键词
    modules:
      - name: 登录
        json: lingxing_elements-登录界面_cleaned.json
        yaml: actions_config_登录界面.yaml
      - name: 进入广告
        json: lingxing_elements-广告_cleaned.json
        yaml: actions_config_广告.yaml
      - name: 创建词库
        json: lingxing_elements-批量创建关键词流程_cleaned.json
        yaml: actions_config_批量创建关键词流程.yaml
"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

try:
    import yaml as _yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from session import BrowserSession
from module_runner import ModuleRunner
from advanced_runner import RunResult


class Orchestrator:
    """
    流程编排器。
    按 flow.yaml 定义依次执行多个模块，全部共享同一浏览器实例。
    """

    def __init__(self, flow_path: str):
        self.flow_path = flow_path
        self.flow = self._load_flow(flow_path)
        self.session = None
        self.module_runner = None
        self.results = {}  # module_name -> RunResult

    def _load_flow(self, path: str) -> dict:
        """加载流程定义文件"""
        if not os.path.isfile(path):
            print(f"流程文件不存在: {path}")
            sys.exit(1)

        if path.endswith(('.yaml', '.yml')) and HAS_YAML:
            with open(path, 'r', encoding='utf-8') as f:
                return _yaml.safe_load(f) or {}
        elif path.endswith('.json'):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            print(f"不支持的格式: {path}（支持 .yaml/.yml/.json）")
            sys.exit(1)

    async def run(self):
        """执行整个流程"""

        name = self.flow.get("name", Path(self.flow_path).stem)
        modules = self.flow.get("modules", [])

        if not modules:
            print("流程定义中没有模块!")
            return

        print(f"\n{'='*60}")
        print(f"  🎬 流程: {name}")
        print(f"  模块数: {len(modules)}")
        print(f"  开始时间: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        # ── 1. 启动浏览器（全局唯一） ──
        self.session = await BrowserSession.create()
        self.module_runner = ModuleRunner(self.session)

        all_success = True

        try:
            # ── 2. 逐个执行模块 ──
            idx = 0
            while idx < len(modules):
                mod = modules[idx]
                idx += 1
                mod_name = mod.get("name", f"模块{idx}")
                json_path = self._resolve_path(mod["json"])
                yaml_path = self._resolve_path(mod.get("yaml", "")) if mod.get("yaml") else None

                print(f"\n{'#'*60}")
                print(f"  ▶  [{idx}/{len(modules)}] 执行模块: {mod_name}")
                print(f"  JSON: {json_path}")
                if yaml_path:
                    print(f"  YAML: {yaml_path}")
                print(f"{'#'*60}")

                result = await self._run_with_retry(mod_name, json_path, yaml_path)
                self.results[mod_name] = result

                if result.fail > 0 and not result.fatal:
                    all_success = False
                    retry_result = await self._module_menu(mod_name, result, modules, idx)
                    if retry_result == "abort":
                        break
                    elif isinstance(retry_result, RunResult):
                        self.results[mod_name] = retry_result
                    elif isinstance(retry_result, list):
                        # 运行中插入了新模块 → 替换 modules 列表
                        modules = retry_result
                        # 调整循环继续执行新插入的模块
                        break

                # 模块成功后也询问是否插入新步骤
                if idx < len(modules):
                    inserted = await self._insert_menu(mod_name, modules, idx)
                    if isinstance(inserted, list):
                        modules = inserted
                        break  # 重新遍历（含有新模块）
                    elif inserted == "retry":
                        idx -= 1  # 重试当前模块
                        continue

            # ── 3. 最终报告 ──
            await self._final_report()

        except KeyboardInterrupt:
            print("\n\n  用户中断")
        finally:
            # ── 4. 询问是否关闭浏览器 ──
            await self._exit_menu()

    def _resolve_path(self, path: str) -> str:
        """解析路径（相对路径基于流程文件所在目录）"""
        if os.path.isabs(path):
            return path
        # 先尝试相对于项目根目录
        candidate = os.path.join(PROJECT_ROOT, path)
        if os.path.isfile(candidate):
            return candidate
        # 再尝试相对于流程文件所在目录
        flow_dir = os.path.dirname(self.flow_path)
        candidate2 = os.path.join(flow_dir, path)
        if os.path.isfile(candidate2):
            return candidate2
        return path  # 原样返回，让调用方处理

    async def _run_with_retry(self, label: str, json_path: str,
                               yaml_path: str = None) -> RunResult:
        """执行一个模块，返回结果"""
        return await self.module_runner.run(json_path, yaml_path, label=label)

    def _save_flow(self):
        """将当前 flow 保存到磁盘（热替换持久化）"""
        try:
            with open(self.flow_path, 'w', encoding='utf-8') as f:
                if HAS_YAML:
                    _yaml.dump(self.flow, f, allow_unicode=True,
                               default_flow_style=False, sort_keys=False, indent=2)
                else:
                    f.write(f"name: {self.flow.get('name', '')}\nmodules:\n")
                    for m in self.flow.get("modules", []):
                        f.write(f"  - name: {m['name']}\n")
                        f.write(f"    json: {m['json']}\n")
                        if 'yaml' in m:
                            f.write(f"    yaml: {m['yaml']}\n")
        except Exception as e:
            print(f"  ⚠️  保存 flow 文件失败: {e}")

    async def _module_menu(self, mod_name: str, result: RunResult,
                            modules: list = None, current_idx: int = 0):
        """模块执行完毕后，如果有失败，显示菜单。支持热替换和插入"""
        while result.fail > 0:
            print(f"\n{'='*50}")
            print(f"  模块 [{mod_name}] 有 {result.fail} 个元素失败")
            if result.fail_indices:
                print(f"  失败索引: {result.fail_indices}")
            print(f"{'='*50}")
            print(f"  r — 重试失败的 {result.fail} 个元素")
            print(f"  a — 全部重新执行此模块")
            print(f"  h — 人工检查（浏览器保持，操作后回车）")
            print(f"  n — 用新 JSON 替换此模块（热替换）")
            print(f"  i — 在此模块后插入一个新步骤")
            print(f"  s — 跳过失败，继续下一个模块")
            print(f"  q — 终止整个流程")
            print(f"  {'─'*30}")

            cmd = await self._read_input()
            loop = asyncio.get_running_loop()

            if cmd == 'q':
                return "abort"

            elif cmd == 's':
                print("  → 跳过失败，继续")
                return result

            elif cmd == 'r':
                if not result.fail_indices:
                    print("  → 没有可重试的步骤")
                    continue
                print(f"  → 重试 {len(result.fail_indices)} 个元素...")
                new_result = await self._retry_indices(
                    json_path=self._find_json_for_module(mod_name)
                )
                result.fail = new_result.fail
                result.fail_indices = new_result.fail_indices
                result.success += new_result.success
                result.success_indices.extend(new_result.success_indices)
                if new_result.fail == 0:
                    print(f"  ✅ 全部重试成功！")
                    return result

            elif cmd == 'a':
                print(f"  → 重新执行整个模块...")
                new_result = await self.module_runner.run(
                    self._find_json_for_module(mod_name),
                    label=mod_name
                )
                result = new_result
                if result.fail == 0:
                    return result

            elif cmd == 'n':
                print(f"\n  → 热替换: 为 [{mod_name}] 选择新 JSON 文件")
                new_mod = self._prompt_new_module()
                if new_mod:
                    # 替换当前模块
                    for i, m in enumerate(modules):
                        if m.get("name") == mod_name:
                            modules[i] = new_mod
                            self._save_flow()
                            break
                    # 重新执行新模块
                    new_result = await self.module_runner.run(
                        self._resolve_path(new_mod["json"]),
                        self._resolve_path(new_mod.get("yaml", "")) if new_mod.get("yaml") else None,
                        label=new_mod["name"]
                    )
                    self.results[new_mod["name"]] = new_result
                    if new_result.fail == 0:
                        print(f"  ✅ 热替换成功！新模块 [{new_mod['name']}] 全部通过")
                        return new_result
                    else:
                        print(f"  ⚠️  新模块仍有 {new_result.fail} 个失败")
                        result = new_result
                        continue
                else:
                    print("  → 已取消")
                    continue

            elif cmd == 'i':
                print(f"\n  → 在 [{mod_name}] 后插入新步骤")
                new_mod = self._prompt_new_module()
                if new_mod:
                    modules.insert(current_idx, new_mod)
                    self.flow["modules"] = modules
                    self._save_flow()
                    print(f"  ✅ 已插入 [{new_mod['name']}] 到位置 {current_idx+1}")
                    # 立即执行新插入的模块
                    new_result = await self.module_runner.run(
                        self._resolve_path(new_mod["json"]),
                        self._resolve_path(new_mod.get("yaml", "")) if new_mod.get("yaml") else None,
                        label=new_mod["name"]
                    )
                    self.results[new_mod["name"]] = new_result
                    if new_result.fail == 0:
                        print(f"  ✅ 新模块 [{new_mod['name']}] 全部通过")
                    return modules  # 返回新列表让主循环继续
                else:
                    print("  → 已取消")
                    continue

            elif cmd == 'h':
                print("  → 人工检查模式")
                print("  浏览器保持打开，请手动操作。完成后输入 ok 继续...")
                while True:
                    resp = await loop.run_in_executor(None, input, "  输入 ok 继续, q 放弃: ")
                    if resp.strip().lower() == 'ok':
                        break
                    if resp.strip().lower() == 'q':
                        return "abort"

            else:
                print(f"  未知命令: {cmd}")

        return result

    async def _insert_menu(self, mod_name: str, modules: list, current_idx: int):
        """模块成功后弹出的插入菜单"""
        loop = asyncio.get_running_loop()
        print(f"\n  ✅ 模块 [{mod_name}] 执行完毕")
        print(f"  i — 在此后插入一个新步骤")
        print(f"  r — 回到模块 {mod_name} 重试菜单")
        print(f"  c — 继续执行下一个模块")

        while True:
            cmd = await loop.run_in_executor(None, input, "  选择 (i/r/c): ")
            cmd = cmd.strip().lower()
            if cmd == 'i':
                new_mod = self._prompt_new_module()
                if new_mod:
                    modules.insert(current_idx, new_mod)
                    self.flow["modules"] = modules
                    self._save_flow()
                    print(f"  ✅ 已插入 [{new_mod['name']}]")
                    return modules
                return None
            elif cmd == 'r':
                return "retry"
            elif cmd == 'c' or not cmd:
                return None
            print(f"  未知: {cmd}")

    def _prompt_new_module(self) -> dict:
        """
        交互式让用户选择新的 JSON 文件。
        列出目录下所有 *_cleaned.json 供选择。
        """
        # 查找所有 cleaned JSON
        cleaned_files = list(Path(PROJECT_ROOT).glob("*_cleaned.json"))
        if not cleaned_files:
            print("  没有找到 cleaned JSON 文件")
            return None

        print(f"\n  可用的模块文件:")
        for i, f in enumerate(cleaned_files):
            # 自动查找同名 YAML
            stem = f.stem.replace("_cleaned", "")
            yaml_exists = (Path(PROJECT_ROOT) / f"actions_config_{stem}.yaml").exists()
            yaml_flag = " [有配置]" if yaml_exists else " [无配置]"
            print(f"    {i+1}. {f.name}{yaml_flag}")

        print(f"    q. 取消")

        while True:
            choice = input("  选择编号: ").strip()
            if not choice or choice.lower() == 'q':
                return None
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(cleaned_files):
                    f = cleaned_files[idx]
                    stem = f.stem.replace("_cleaned", "")
                    yaml_path = Path(PROJECT_ROOT) / f"actions_config_{stem}.yaml"
                    mod = {
                        "name": stem,
                        "json": str(f.name),
                    }
                    if yaml_path.exists():
                        mod["yaml"] = str(yaml_path.name)
                    return mod
                else:
                    print("    编号无效")
            except ValueError:
                print("    请输入数字")

    def _find_json_for_module(self, mod_name: str) -> str:
        """根据模块名找到对应的 JSON 路径"""
        for mod in self.flow.get("modules", []):
            if mod.get("name") == mod_name:
                return self._resolve_path(mod["json"])
        return ""

    async def _retry_indices(self, json_path: str) -> RunResult:
        """只重试失败的步骤"""
        # 调用 module_runner 的重试逻辑
        from module_runner import ModuleRunner
        from advanced_runner import (
            StepRunner, StepAction, StepState
        )

        with open(json_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        # 展平所有格式 → 平铺元素列表（同 advanced_runner.py）
        def _flatten(raw):
            if isinstance(raw, dict) and "elements" in raw:
                return raw["elements"]
            if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], dict) and "elements" in raw[0]:
                flat = []
                for wrapper in raw:
                    inner = wrapper.get("elements", [])
                    for el in inner:
                        if "step_name" not in el or not el.get("step_name"):
                            el["step_name"] = wrapper.get("metadata", {}).get("step_name", "unknown")
                        if "cleaned" not in el and "cleaned" in wrapper:
                            el["cleaned"] = wrapper["cleaned"]
                        flat.append(el)
                return flat
            if isinstance(raw, list):
                return raw
            raise ValueError(f"不支持的 JSON 格式: {type(raw)}")

        elements = _flatten(raw)

        result = RunResult()
        result.total = len(elements)

        # 读取动作配置
        actions = {}
        yaml_path = self._find_yaml_for_module(Path(json_path).stem)
        if yaml_path and HAS_YAML:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = _yaml.safe_load(f) or {}
            for item in data.get("actions", []):
                idx = item.get("index")
                if idx is not None:
                    actions[idx] = item.get("action", {})

        # 只需重试之前失败的
        from advanced_runner import HumanInterventionConfig
        runner = StepRunner(
            self.session.page, self.session.cdp, self.session.event_bus,
            elements, {}, HumanInterventionConfig()
        )

        from collections import OrderedDict
        indices = []
        for mod in self.flow.get("modules", []):
            mname = mod.get("name")
            if mname in self.results:
                indices.extend(self.results[mname].fail_indices)

        if not indices:
            return result

        groups = OrderedDict()
        for idx in indices:
            if idx >= len(elements):
                continue
            sn = elements[idx]["step_name"]
            if sn not in groups:
                groups[sn] = []
            groups[sn].append(idx)

        print(f"  重试 {len(indices)} 个元素, {len(groups)} 个区域")

        for group_idx, (sn, idx_list) in enumerate(groups.items(), 1):
            print(f"\n    [{group_idx}/{len(groups)}] {sn}")
            for ei, gi in enumerate(idx_list, 1):
                item = elements[gi]
                action = actions.get(gi, self.module_runner._auto_action(item))
                step = StepAction(gi, sn, item.get("cleaned", {}).get("strategies", []),
                                  action, {})
                state, msg = await runner.run(step)
                if state == StepState.SUCCESS:
                    result.success += 1
                    result.success_indices.append(gi)
                elif state == StepState.SKIP:
                    result.skip += 1
                    result.skip_indices.append(gi)
                elif state == StepState.FAIL:
                    result.fail += 1
                    result.fail_indices.append(gi)

        return result

    def _find_yaml_for_module(self, json_stem: str) -> str:
        """查找模块对应的 YAML"""
        stem = json_stem.replace("_cleaned", "")
        candidates = [
            os.path.join(PROJECT_ROOT, f"actions_config_{stem}.yaml"),
            os.path.join(PROJECT_ROOT, f"actions_config_{stem}.yml"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return ""

    async def _final_report(self):
        """最终报告"""
        print(f"\n{'='*60}")
        print(f"  📊 最终报告")
        print(f"{'='*60}")

        total_success = 0
        total_skip = 0
        total_fail = 0
        for mod_name, result in self.results.items():
            status = "✅" if result.fail == 0 else "❌"
            print(f"  {status} {mod_name}: "
                  f"成功={result.success} 跳过={result.skip} 失败={result.fail}")
            total_success += result.success
            total_skip += result.skip
            total_fail += result.fail

        total = total_success + total_skip + total_fail
        net = total_success + total_fail
        print(f"{'─'*40}")
        print(f"  总计: ✅ {total_success}  ⏭️  {total_skip}  ❌ {total_fail}")
        if net > 0:
            print(f"  有效率: {total_success}/{net} ({total_success*100//net}%)")
        print(f"{'='*60}")

    async def _exit_menu(self):
        """退出菜单"""
        loop = asyncio.get_running_loop()

        print(f"\n{'='*50}")
        print(f"  q — 退出并关闭浏览器")
        print(f"  k — 保持浏览器打开（手动关闭）")
        print(f"{'='*50}")

        while True:
            cmd = await loop.run_in_executor(None, input, "  选择: ")
            cmd = cmd.strip().lower()
            if cmd == 'q':
                await self.session.close()
                break
            elif cmd == 'k':
                print("  → 浏览器保持打开，手动关闭")
                break
            else:
                print(f"  未知: {cmd}")

    async def _read_input(self) -> str:
        """读取用户输入（Windows 兼容）"""
        loop = asyncio.get_running_loop()
        cmd = await loop.run_in_executor(None, input, "  选择: ")
        return cmd.strip().lower()


# ============================================================
#  快速创建流程文件
# ============================================================
def _scaffold_flow():
    """交互式创建流程文件"""
    print("快速创建流程文件...")
    flow_name = input("流程名称: ").strip() or "我的流程"

    # 查找所有 cleaned JSON
    cleaned_files = list(Path(PROJECT_ROOT).glob("*_cleaned.json"))
    if not cleaned_files:
        print("没有找到 cleaned JSON 文件")
        return

    print(f"\n可用的模块文件:")
    for i, f in enumerate(cleaned_files):
        print(f"  {i+1}. {f.name}")

    modules = []
    while True:
        choice = input("\n输入编号添加模块（回车完成）: ").strip()
        if not choice:
            break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(cleaned_files):
                f = cleaned_files[idx]
                # 自动查找同名 YAML
                stem = f.stem.replace("_cleaned", "")
                yaml_path = Path(PROJECT_ROOT) / f"actions_config_{stem}.yaml"
                mod = {
                    "name": stem,
                    "json": str(f.name),
                }
                if yaml_path.exists():
                    mod["yaml"] = str(yaml_path.name)
                modules.append(mod)
                print(f"    已添加: {stem}")
            else:
                print("    编号无效")
        except ValueError:
            break

    if not modules:
        print("没有添加任何模块")
        return

    flow = {
        "name": flow_name,
        "modules": modules,
    }

    flow_path = Path(PROJECT_ROOT) / f"flow_{flow_name}.yaml"
    with open(flow_path, 'w', encoding='utf-8') as f:
        if HAS_YAML:
            _yaml.dump(flow, f, allow_unicode=True, default_flow_style=False,
                       sort_keys=False, indent=2)
        else:
            f.write(f"name: {flow_name}\nmodules:\n")
            for m in modules:
                f.write(f"  - name: {m['name']}\n")
                f.write(f"    json: {m['json']}\n")
                if 'yaml' in m:
                    f.write(f"    yaml: {m['yaml']}\n")

    print(f"\n✅ 已生成流程文件: {flow_path}")
    print(f"运行: python orchestrator.py {flow_path.name}")


# ============================================================
#  CLI
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python orchestrator.py <flow.yaml>          执行流程")
        print("  python orchestrator.py --scaffold           快速创建流程文件")
        print()
        print("流程文件格式 (flow.yaml):")
        print("  name: 批量创建关键词")
        print("  modules:")
        print("    - name: 登录")
        print("      json: lingxing_elements-登录界面_cleaned.json")
        print("      yaml: actions_config_登录界面.yaml")
        print("    - name: 创建词库")
        print("      json: lingxing_elements-批量创建关键词流程_cleaned.json")
        sys.exit(1)

    if sys.argv[1] == "--scaffold":
        _scaffold_flow()
        return

    flow_path = sys.argv[1]
    orch = Orchestrator(flow_path)
    asyncio.run(orch.run())


if __name__ == "__main__":
    main()
