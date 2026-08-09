"""独立Consult必须在导入veADK前建立INFO安全日志默认值。"""

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_fresh_standalone_import_suppresses_veadk_debug_tool_payloads():
    env = dict(os.environ)
    env.pop("LOGGING_LEVEL", None)
    marker = "SENSITIVE_KNOWLEDGE_CHUNK_MUST_NOT_BE_LOGGED"
    code = (
        "import logging\n"
        "import apps.consult_agent.runtime\n"
        f"logging.getLogger('veadk.runner').debug('{marker}')\n"
        "print(logging.getLogger('veadk').getEffectiveLevel())\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    combined = completed.stdout + completed.stderr
    assert marker not in combined
    assert completed.stdout.rstrip().endswith("20")
