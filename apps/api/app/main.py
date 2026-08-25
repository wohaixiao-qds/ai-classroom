"""FastAPI 入口。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.catalog import router as catalog_router
from app.routes.chat import router as chat_router
from app.routes.eval import router as eval_router
from app.routes.learning import router as learning_router

app = FastAPI(title="AI 课堂 API", version="0.1.0")

# 本地前端 dev 端口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5273", "http://127.0.0.1:5273"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(eval_router)
app.include_router(catalog_router)
app.include_router(learning_router)
