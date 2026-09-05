"""按Runtime配置选择唯一应用入口。"""

import os
import sys


_RUNTIME_MODULES = {
    "orchestrator": "apps.orchestrator.public_a2a",
    "consult": "apps.consult_agent.cloud",
    "employee-data": "apps.employee_data_agent.cloud",
}


def runtime_module(runtime_app: str) -> str:
    try:
        return _RUNTIME_MODULES[runtime_app]
    except KeyError as exc:
        raise RuntimeError(
            "HR_RUNTIME_APP必须是orchestrator、consult或employee-data"
        ) from exc


def main() -> None:
    module = runtime_module(os.getenv("HR_RUNTIME_APP", ""))
    os.execv(sys.executable, [sys.executable, "-m", module])


if __name__ == "__main__":
    main()
