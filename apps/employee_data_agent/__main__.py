"""`python -m apps.employee_data_agent`独立启动入口。"""

from apps.employee_data_agent.a2a.server import run_local_server


if __name__ == "__main__":
    run_local_server()
