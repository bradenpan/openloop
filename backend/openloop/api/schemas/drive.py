from pydantic import BaseModel

__all__ = [
    "DriveLinkRequest",
    "DriveLinkResponse",
    "DriveRefreshResponse",
    "DriveAuthStatusResponse",
]


class DriveLinkRequest(BaseModel):
    space_id: str
    folder_id: str
    folder_name: str


class DriveLinkResponse(BaseModel):
    data_source_id: str
    folder_id: str
    folder_name: str
    documents_indexed: int


class DriveRefreshResponse(BaseModel):
    added: int
    updated: int
    removed: int


class DriveAuthStatusResponse(BaseModel):
    authenticated: bool
