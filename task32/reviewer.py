"""Ядро AI code review: diff + RAG-контекст → текст ревью.

Пайплайн:
  1. parse_diff        — изменённые файлы и добавленные строки;
  2. heuristics.scan   — офлайн-находки (баги/архитектура/рекомендации);
  3. RAG (search)      — по каждому файлу тянем релевантные куски документации
                         и кода проекта (чтобы ревью учитывало контекст, а не
                         только сам diff);
  4. LLM-каскад        — DeepSeek API → Ollama → без LLM (только эвристики);
  5. render_markdown   — итоговое ревью с 3 разделами.

LLM выступает усилителем: даже без неё ревью содержательное (эвристики + RAG).
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import heuristics
from diff_parser import FileDiff, parse_diff, summary
from indexer import load_index
from search import build_backend

HERE = Path(__file__).parent


# ------------------------------------------------------------- RAG-контекст --
def rag_context(backend, files: list[FileDiff], k: int = 3) -> str:
    """Для каждого файла ищем в индексе релевантные доки и код проекта."""
    blocks: list[str] = []
    for fd in files:
        query = f"{fd.path}\n{fd.added_text[:600]}"
        hits = backend.search(query, k=k)
        lines = [f"### Контекст для {fd.path}"]
        for score, ch in hits:
            if score < 0.02:
                continue
            snippet = ch["text"].replace("\n", " ")[:220]
            lines.append(f"- [{score:.2f}] {ch['source']} :: "
                         f"{ch['section']} — {snippet}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "(релевантный контекст в индексе не найден)"


# --------------------------------------------------------------- LLM-каскад --
def _prompt(diff_text: str, findings, rag: str) -> str:
    heur = "\n".join(f"- {f.severity}/{f.category} {f.path}:{f.line} "
                     f"{f.message}" for f in findings) or "(эвристики пусты)"
    return (
        "Ты — старший инженер, делаешь ревью pull request. Отвечай на русском.\n"
        "Опирайся на: (1) сам diff, (2) находки статического анализатора, "
        "(3) контекст проекта из RAG (документация + код). Не выдумывай.\n"
        "Верни строго три раздела маркдауном:\n"
        "## 🐞 Потенциальные баги\n## 🏗 Архитектурные проблемы\n"
        "## 💡 Рекомендации\n"
        "Каждый пункт — конкретно, с указанием файла/строки, коротко.\n\n"
        f"=== DIFF ===\n{diff_text[:6000]}\n\n"
        f"=== НАХОДКИ СТАТ.АНАЛИЗА ===\n{heur}\n\n"
        f"=== КОНТЕКСТ ПРОЕКТА (RAG) ===\n{rag[:2500]}\n\n=== РЕВЬЮ ===")


def gen_deepseek(prompt: str) -> str | None:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key or key == "YOUR_DEEPSEEK_API_KEY":
        return None
    body = json.dumps({"model": "deepseek-chat",
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.2}).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
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
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("response", "").strip() or None
    except Exception:
        return None


# ------------------------------------------------------ рендер без LLM --------
def render_heuristic(findings) -> str:
    buckets = {"bug": [], "arch": [], "rec": []}
    for f in findings:
        buckets[f.category].append(f"- {f.render()}")
    titles = {"bug": "## 🐞 Потенциальные баги",
              "arch": "## 🏗 Архитектурные проблемы",
              "rec": "## 💡 Рекомендации"}
    out = []
    for cat in ("bug", "arch", "rec"):
        out.append(titles[cat])
        out.append("\n".join(buckets[cat]) if buckets[cat]
                   else "- Проблем не выявлено.")
        out.append("")
    return "\n".join(out)


# ----------------------------------------------------------------- пайплайн --
def review(diff_text: str, use_llm: bool = True) -> str:
    files = parse_diff(diff_text)
    if not files:
        return "PR не содержит изменений в отслеживаемых файлах."

    findings = heuristics.scan(files)
    backend = build_backend(load_index())
    rag = rag_context(backend, files)

    header = [f"# 🤖 AI-ревью PR", "", summary(files), "",
              f"Файлов: {len(files)} · находок стат.анализа: {len(findings)} "
              f"· RAG-бэкенд: {backend.name} ({len(backend.chunks)} чанков)", ""]

    body = None
    if use_llm:
        prompt = _prompt(diff_text, findings, rag)
        text = gen_deepseek(prompt) or gen_ollama(prompt)
        if text:
            body = (text + "\n\n---\n### 🔎 Находки статического анализатора\n"
                    + render_heuristic(findings))
    if body is None:
        body = ("> LLM недоступна — ревью собрано статическим анализатором "
                "и RAG-контекстом.\n\n" + render_heuristic(findings))

    footer = ["", "---", "<details><summary>📚 RAG-контекст (док-я + код)</summary>",
              "", rag, "</details>", "",
              "_Сгенерировано автоматически (task32, AI code review)._"]
    return "\n".join(header) + body + "\n".join(footer)


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else None
    diff = Path(src).read_text("utf-8") if src else sys.stdin.read()
    print(review(diff))
