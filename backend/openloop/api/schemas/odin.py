from pydantic import BaseModel

__all__ = [
    "OdinMessageRequest",
]


class OdinMessageRequest(BaseModel):
    content: str
