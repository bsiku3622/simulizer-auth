from pydantic import BaseModel, field_validator
from typing import Literal, Optional

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024  # 2 MB

FileType = Literal["blockfile", "clangfile"]


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    picture_url: Optional[str]
    last_login_at: Optional[str]
    created_at: str
    updated_at: str


class RecoveryUserOut(UserOut):
    days_remaining: int


class FileCreate(BaseModel):
    name: str
    type: FileType = "blockfile"
    content: str = "{}"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        if len(v) > 50:
            raise ValueError("name must be 50 characters or fewer")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v.encode()) > MAX_CONTENT_BYTES:
            raise ValueError("content exceeds 5 MB limit")
        return v


class FileOut(BaseModel):
    idx: int
    id: str
    author_id: int
    name: str
    type: FileType
    visibility: str
    thumbnail_custom: bool
    created_at: str
    updated_at: str


class FileDetail(FileOut):
    content: str


class FileContentUpdate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v.encode()) > MAX_CONTENT_BYTES:
            raise ValueError("content exceeds 5 MB limit")
        return v


class FileRename(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        if len(v) > 50:
            raise ValueError("name must be 50 characters or fewer")
        return v


class FileVisibilityUpdate(BaseModel):
    visibility: Literal["private", "link"]


class CreditOut(BaseModel):
    credits: int


class CreditAmount(BaseModel):
    amount: int

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be a positive integer")
        return v
