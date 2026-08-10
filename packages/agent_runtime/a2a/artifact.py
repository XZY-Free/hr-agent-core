"""官方TextPart与DataPart的通用Artifact辅助。"""

from a2a.types import DataPart, Part, TextPart


def structured_result_parts(answer: str, data: dict) -> list[Part]:
    return [
        Part(root=TextPart(text=answer)),
        Part(root=DataPart(data=data)),
    ]
