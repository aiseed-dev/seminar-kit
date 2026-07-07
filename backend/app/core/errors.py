"""API エラー。応答形式は { "detail": "...", "code": "..." }(02_api)。"""

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, detail: str, code: str):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
