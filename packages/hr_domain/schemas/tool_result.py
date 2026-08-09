"""工具返回统一结构构造器。所有工具返回值都走这两个函数。"""


def ok(data) -> dict:
    return {"success": True, "data": data}


def err(error_type: str, message: str) -> dict:
    return {"success": False, "error_type": error_type, "message": message}
