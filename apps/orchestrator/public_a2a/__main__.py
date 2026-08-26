"""顶层公共A2A Provider入口：python -m apps.orchestrator.public_a2a"""

from apps.orchestrator.public_a2a.server import run_local_server


if __name__ == "__main__":
    run_local_server()
