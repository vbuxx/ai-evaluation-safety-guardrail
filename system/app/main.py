"""FastAPI entry point untuk IT Helpdesk Assistant."""

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.router import handle_query

logger = logging.getLogger(__name__)
app = FastAPI(title="IT Helpdesk Assistant API", version="1.0.0")


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class AskResponse(BaseModel):
    status: str
    intent: str
    data: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Query tidak boleh kosong")

    try:
        return AskResponse(**await handle_query(query))
    except Exception:
        logger.exception("Gagal memproses query helpdesk")
        return AskResponse(
            status="error",
            intent="unknown",
            data="Layanan sedang bermasalah. Silakan coba lagi nanti.",
        )
