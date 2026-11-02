"""FastAPI entry point untuk IT Helpdesk Assistant."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.router import handle_query

logger = logging.getLogger(__name__)
app = FastAPI(title="IT Helpdesk Assistant API", version="1.0.0")


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Query tidak boleh kosong")
        return value


class AskResponse(BaseModel):
    status: str
    intent: str
    data: str


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "status": "error", "intent": "unknown",
            "data": "Query wajib berupa teks tidak kosong dengan panjang maksimal 1000 karakter.",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    try:
        return AskResponse(**await handle_query(request.query))
    except Exception:
        logger.exception("Gagal memproses query helpdesk")
        return AskResponse(
            status="error",
            intent="unknown",
            data="Layanan sedang bermasalah. Silakan coba lagi nanti.",
        )
