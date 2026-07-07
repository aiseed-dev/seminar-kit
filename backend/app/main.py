"""FastAPI アプリ(公開・申込系のみ。事務局は Flet・DB 直結で API なし)。

起動: uvicorn app.main:app --host 127.0.0.1 --port 8000(Caddy が前段)
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import ApiError
from app.routers import courses, docs, qr

app = FastAPI(title="研修・セミナー 公開API", version="0.1.0")

# apply ページ(Cloudflare Pages)からの fetch を許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().site_base_url],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(courses.router, prefix="/api/v1")
app.include_router(qr.router, prefix="/api/v1")
app.include_router(docs.router, prefix="/api/v1/docs")


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )
