#!/usr/bin/env python3
"""
Task 30 — Локальная LLM как приватный HTTP-сервис
FastAPI обёртка над Ollama: /chat, /health, /info, rate limit, веб-чат
"""

import time
import threading
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:14b"
MAX_CONTEXT = 32768
RATE_LIMIT_RPM = 20

# Отключаем прокси (v2rayN в WSL2)
_http = requests.Session()
_http.trust_env = False

app = FastAPI(title="Private LLM Service", version="1.0.0")

_rate_buckets: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()

DEFAULT_SYSTEM = "Ты полезный AI-ассистент. Отвечай чётко и по делу на языке пользователя."


def check_rate_limit(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets[ip]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_RPM:
            return False
        bucket.append(now)
        return True


class Message(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    stream: bool = False
    temperature: float = 0.7
    max_tokens: int = 1024
    system: Optional[str] = None


class ChatResponse(BaseModel):
    message: Message
    model: str
    elapsed: float
    tokens: int


@app.get("/health")
def health():
    try:
        r = _http.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        model_loaded = MODEL in models
    except Exception as e:
        raise HTTPException(503, f"Ollama недоступен: {e}")
    return {
        "status": "ok",
        "ollama": "up",
        "model": MODEL,
        "model_loaded": model_loaded,
        "available_models": models,
        "rate_limit": f"{RATE_LIMIT_RPM} req/min",
    }


@app.get("/info")
def info():
    return {
        "model": MODEL,
        "max_context_tokens": MAX_CONTEXT,
        "max_tokens_per_response": 4096,
        "rate_limit_rpm": RATE_LIMIT_RPM,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    ip = request.client.host
    if not check_rate_limit(ip):
        raise HTTPException(429, f"Rate limit: не более {RATE_LIMIT_RPM} запросов/мин")

    messages = [{"role": "system", "content": req.system or DEFAULT_SYSTEM}]
    for m in req.messages:
        messages.append({"role": m.role, "content": m.content})

    t0 = time.time()
    try:
        resp = _http.post(f"{OLLAMA_URL}/api/chat", json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": req.temperature,
                "num_predict": min(req.max_tokens, 4096),
            },
        }, timeout=300)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise HTTPException(504, "LLM не ответила за 300с")
    except Exception as e:
        raise HTTPException(502, f"Ollama error: {e}")

    elapsed = round(time.time() - t0, 2)
    data = resp.json()
    answer = data.get("message", {}).get("content", "").strip()
    tokens = data.get("eval_count", 0)

    return ChatResponse(
        message=Message(role="assistant", content=answer),
        model=MODEL,
        elapsed=elapsed,
        tokens=tokens,
    )


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request):
    ip = request.client.host
    if not check_rate_limit(ip):
        raise HTTPException(429, f"Rate limit: {RATE_LIMIT_RPM} req/min")

    messages = [{"role": "system", "content": req.system or DEFAULT_SYSTEM}]
    for m in req.messages:
        messages.append({"role": m.role, "content": m.content})

    def generate():
        import json
        try:
            with _http.post(f"{OLLAMA_URL}/api/chat", json={
                "model": MODEL,
                "messages": messages,
                "stream": True,
                "think": False,
                "options": {"temperature": req.temperature, "num_predict": min(req.max_tokens, 4096)},
            }, stream=True, timeout=300) as r:
                for line in r.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        if chunk.get("done"):
                            yield f"data: {json.dumps({'done': True, 'tokens': chunk.get('eval_count', 0)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
def web_chat():
    html = Path(__file__).parent / "chat.html"
    return HTMLResponse(html.read_text(encoding="utf-8"))
