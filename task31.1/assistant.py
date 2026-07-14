"""Ассистент разработчика — команда /help.

Отвечает на вопросы о проекте, объединяя:
  1) RAG-поиск по документации (README + docs/),
  2) живой git-контекст через MCP-сервер (mcp_server.py, stdio),
  3) генерацию ответа: DeepSeek API → Ollama → extractive fallback.

Использование:
    python3 assistant.py "как устроен RAG в проекте?"
    python3 assistant.py            # интерактивно; команда /help
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import indexer
import search

HERE = Path(__file__).parent
INDEX_PATH = HERE / "index.json"


# --------------------------------------------------------------- MCP client --
def mcp_call(tool: str, arguments: dict | None = None) -> str:
    """Вызывает инструмент через MCP-сервер по stdio (реальный протокол)."""
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": tool, "arguments": arguments or {}}},
    ]
    payload = "\n".join(json.dumps(r) for r in reqs) + "\n"
    try:
        proc = subprocess.run(
            [sys.executable, str(HERE / "mcp_server.py")],
            input=payload, capture_output=True, text=True, timeout=20)
        for line in proc.stdout.splitlines():
            msg = json.loads(line)
            if msg.get("id") == 2 and "result" in msg:
                return msg["result"]["content"][0]["text"]
    except Exception as e:
        return f"[mcp error] {e}"
    return "(нет ответа от MCP)"


# ----------------------------------------------------------------- retrieval -
def ensure_index() -> list[dict]:
    if not INDEX_PATH.exists():
        indexer.build_index()
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def retrieve(backend, question: str, k: int = 4):
    return backend.search(question, k=k)


# ---------------------------------------------------------------- generation -
def _prompt(question: str, hits, git_ctx: str) -> str:
    ctx = "\n\n".join(
        f"[{s:.2f}] {c['source']} :: {c['section']}\n{c['text']}"
        for s, c in hits)
    return (
        "Ты — ассистент разработчика этого проекта. Отвечай на русском, "
        "коротко и по делу, опираясь только на документацию и git-контекст ниже. "
        "Если данных нет — так и скажи.\n\n"
        f"=== ДОКУМЕНТАЦИЯ ===\n{ctx}\n\n"
        f"=== GIT-КОНТЕКСТ ===\n{git_ctx}\n\n"
        f"=== ВОПРОС ===\n{question}\n\n=== ОТВЕТ ===")


def gen_deepseek(prompt: str) -> str | None:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key or key == "YOUR_DEEPSEEK_API_KEY":
        return None
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[deepseek недоступен: {e}]")
        return None


def gen_ollama(prompt: str) -> str | None:
    body = json.dumps({"model": os.getenv("OLLAMA_MODEL", "qwen3:14b"),
                       "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate",
                                data=body,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get("response", "").strip() or None
    except Exception:
        return None


def gen_extractive(hits, git_ctx: str) -> str:
    """Fallback без LLM: собираем ответ из найденных фрагментов."""
    lines = ["Ответ собран из документации (LLM недоступна):", ""]
    for s, c in hits:
        snippet = c["text"].replace("\n", " ")[:220]
        lines.append(f"• ({c['source']} :: {c['section']}) {snippet}")
    lines += ["", "Git-контекст:", git_ctx]
    return "\n".join(lines)


def answer(backend, question: str) -> str:
    hits = retrieve(backend, question)
    diff = mcp_call("git_diff").splitlines()
    diff_short = "\n".join(diff[:12]) + ("\n…" if len(diff) > 12 else "")
    git_ctx = f"Ветка: {mcp_call('git_branch')}\nИзменения:\n{diff_short}"
    prompt = _prompt(question, hits, git_ctx)
    text = gen_deepseek(prompt) or gen_ollama(prompt)
    if text:
        srcs = ", ".join(sorted({c["source"] for _, c in hits}))
        return f"{text}\n\n— источники: {srcs}"
    return gen_extractive(hits, git_ctx)


# --------------------------------------------------------------------- CLI ---
BANNER = """Ассистент разработчика (task32). Команды:
  /help <вопрос>   — спросить о проекте
  /branch          — текущая git-ветка (через MCP)
  /files           — файлы проекта (через MCP)
  выход / exit     — выйти
"""


def main() -> None:
    chunks = ensure_index()
    backend = search.build_backend(chunks)
    print(f"[индекс: {len(chunks)} чанков, backend={backend.name}]")

    if len(sys.argv) > 1:
        print(answer(backend, " ".join(sys.argv[1:])))
        return

    print(BANNER)
    while True:
        try:
            q = input("dev> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        low = q.lower()
        if low in ("выход", "exit", "quit"):
            break
        if low in ("/branch",):
            print("ветка:", mcp_call("git_branch"))
            continue
        if low in ("/files",):
            print(mcp_call("git_files", {"limit": 30}))
            continue
        if low.startswith("/help"):
            q = q[5:].strip() or "что это за проект и как он устроен?"
        print(answer(backend, q))


if __name__ == "__main__":
    main()
