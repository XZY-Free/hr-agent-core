"""测试环境收敛：仅允许 tests/agentkit 下的 AgentKit 远端 HTTP 客户端验收。

不自动读取本地配置文件（.env / agentkit.yaml 等），不加载模型环境，不启动本地 Agent。
测试进程的云端凭据由执行进程环境安全注入，服务端配置另归属 AgentKit（不在本测试内）。
pytest_sessionstart 在收集 import 任何生产代码之前，对 config.args 做白名单校验：
只放行 tests/agentkit 及其中已存在的文件/目录/::node；越界或不存在的路径、以及未命中
tests/agentkit 的默认收集目标，都抛 pytest.UsageError。

同时禁止 --pyargs（把目标当 Python 包名导入，带起本地应用）与 --showlocals（失败时
打印本地变量/凭据）。纯 --collect-only 在 tests/agentkit 内允许。

校验采用 .resolve() 后的 relative_to 做 containment（非 startswith），避免前缀绕过。
"""

from pathlib import Path

import pytest


def pytest_sessionstart(session) -> None:
    config = session.config
    option = config.option

    if option.pyargs:
        raise pytest.UsageError(
            "拒绝 --pyargs：本环境只允许 AgentKit 远端验收 tests/agentkit，"
            "不接受把目标当 Python 包名导入（带起本地应用 import，且无法按文件系统"
            " containment 校验）。"
        )
    if option.showlocals:
        raise pytest.UsageError(
            "拒绝 --showlocals：失败时会打印本地变量/凭据；"
            "AgentKit 远端验收请使用 --collect-only 等不泄漏本地的选项。"
        )

    invoke_dir = Path(config.invocation_params.dir)
    base = Path(__file__).resolve().parent / "agentkit"

    args = list(config.args)
    if not args:
        raise pytest.UsageError(
            "没有可收集路径；本环境只允许 tests/agentkit（AgentKit 远端 HTTP 客户端验收）。"
        )

    for raw_arg in args:
        path_part = str(raw_arg).split("::", 1)[0].strip()
        if not path_part:
            raise pytest.UsageError(
                f"收集路径为空：{raw_arg!r}；只允许 tests/agentkit 下已存在的文件/目录/节点。"
            )

        resolved = (invoke_dir / path_part).resolve()
        if not resolved.exists():
            raise pytest.UsageError(
                f"收集路径不存在：{raw_arg}（解析为 {resolved}）。"
                "只允许 tests/agentkit 下已存在的文件/目录。"
            )

        try:
            resolved.relative_to(base)
        except ValueError:
            raise pytest.UsageError(
                f"只允许 tests/agentkit（AgentKit 远端 HTTP 客户端验收），收集路径越界：{raw_arg}"
                f"（解析为 {resolved}）。请显式指定 tests/agentkit 下已实现的目标；若默认收集路径"
                "未命中 tests/agentkit，请先确认 pyproject 的 testpaths 已收敛到 tests/agentkit。"
            ) from None
