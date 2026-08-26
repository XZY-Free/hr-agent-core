"""Operator-only：从公共执行主体生成内部pseudonymous映射键。

输入 subject_kind + subject_id，只输出 internal_user_id。
绝不接收或输出 employeeId；管理员私下在 EMPLOYEE_IDENTITY_MAP_JSON
中配置 internal_user_id → employeeId 映射。

用法：
    python scripts/public_subject_ref.py --subject-kind platform_user \
        --subject-id <snow-subject-id>
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.orchestrator.public_runtime.identity_adapter import (  # noqa: E402
    derive_internal_user_id,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成SnowHarness公共执行主体的内部pseudonymous user_id。"
    )
    parser.add_argument(
        "--subject-kind",
        required=True,
        choices=["platform_user", "platform_service"],
    )
    parser.add_argument("--subject-id", required=True)
    arguments = parser.parse_args()
    print(
        derive_internal_user_id(
            arguments.subject_kind, arguments.subject_id
        )
    )


if __name__ == "__main__":
    main()
