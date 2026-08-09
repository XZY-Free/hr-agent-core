"""独立Consult本地A2A服务入口：python -m apps.consult_agent。"""

from apps.consult_agent.a2a.server import run_local_server


if __name__ == "__main__":
    run_local_server()
