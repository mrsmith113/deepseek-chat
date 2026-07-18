"""
metrics.py — Метрики AI Pipeline.
Концепция курса БЛМ: Latency (P50/P95/P99), Cost, Quality, Success Rate.

Каждый запрос записывается в JSONL-файл.
/stats в боте читает файл и возвращает агрегированную статистику.

Формат записи:
  {"ts": ..., "route": "FULL_PIPELINE",
   "latency": {"agents": 5.2, "llm": 28.5, "total": 41.3},
   "tokens": {"prompt": 12400, "completion": 1850},
   "cost_usd": 0.0041,
   "agents_ok": 4, "eec_valid": true, "codes_found": 3}
"""
import json
import os
import time
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

METRICS_FILE = "/tmp/rag_orchestrator_metrics.jsonl"

# Накопленная per-tool статистика (latency, ok/fail)
_tool_stats: dict[str, list] = defaultdict(list)


def record_tool(name: str, elapsed: float, ok: bool):
    """Вызывается из tool_registry wrapper при каждом вызове инструмента."""
    _tool_stats[name].append({"elapsed": elapsed, "ok": ok})


def record_request(
    route: str,
    latency_breakdown: dict,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    agents_ok: int = 4,
    eec_valid: bool = False,
    codes_found: int = 0,
):
    """Записать метрики одного запроса в JSONL и лог."""
    # DeepSeek pricing ($/1M tokens): prompt $0.27, completion $1.10
    cost_usd = (prompt_tokens * 0.27 + completion_tokens * 1.10) / 1_000_000

    entry = {
        "ts": time.time(),
        "route": route,
        "latency": latency_breakdown,
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        "cost_usd": round(cost_usd, 6),
        "agents_ok": agents_ok,
        "eec_valid": eec_valid,
        "codes_found": codes_found,
    }
    try:
        with open(METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"[Metrics] write error: {e}")

    total = latency_breakdown.get("total", 0)
    log.info(
        f"[Metrics] route={route} total={total:.1f}s "
        f"tokens={prompt_tokens}+{completion_tokens} cost=${cost_usd:.4f} "
        f"agents_ok={agents_ok} eec_valid={eec_valid}"
    )


def _load_entries() -> list[dict]:
    if not os.path.exists(METRICS_FILE):
        return []
    entries = []
    try:
        with open(METRICS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        log.warning(f"[Metrics] read error: {e}")
    return entries


def _perc(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, int(p / 100 * len(s)) - 1)
    return round(s[idx], 1)


def build_stats_report() -> str:
    """Строит отчёт P50/P95/P99 + cost + success rate для /stats."""
    entries = _load_entries()
    if not entries:
        return "📊 Нет данных. Задай вопрос боту — метрики появятся автоматически."

    totals = [e["latency"].get("total", 0) for e in entries if e.get("latency")]
    llm_times = [e["latency"].get("llm", 0) for e in entries if e.get("latency")]
    agent_times = [e["latency"].get("agents", 0) for e in entries if e.get("latency")]
    costs = [e.get("cost_usd", 0) for e in entries]
    prompt_tokens = [e.get("tokens", {}).get("prompt", 0) for e in entries]
    compl_tokens = [e.get("tokens", {}).get("completion", 0) for e in entries]

    success = sum(
        1 for e in entries
        if e.get("agents_ok", 0) >= 3 and e.get("eec_valid", False)
    )
    success_rate = round(100 * success / len(entries), 1) if entries else 0

    routes: dict[str, int] = defaultdict(int)
    for e in entries:
        routes[e.get("route", "?")] += 1

    avg_cost = sum(costs) / len(costs) if costs else 0
    avg_prompt = int(sum(prompt_tokens) / len(prompt_tokens)) if prompt_tokens else 0
    avg_compl = int(sum(compl_tokens) / len(compl_tokens)) if compl_tokens else 0

    lines = [
        f"📊 *Метрики AI Pipeline* — {len(entries)} запросов\n",
        "⏱ *Latency*",
        f"  Total  — P50: {_perc(totals, 50)}s | P95: {_perc(totals, 95)}s | P99: {_perc(totals, 99)}s",
        f"  Агенты — P50: {_perc(agent_times, 50)}s | P95: {_perc(agent_times, 95)}s",
        f"  LLM    — P50: {_perc(llm_times, 50)}s | P95: {_perc(llm_times, 95)}s\n",
        "💰 *Стоимость (DeepSeek)*",
        f"  Средняя: ${avg_cost:.4f}/запрос",
        f"  Всего: ${sum(costs):.3f}",
        f"  Токены: ~{avg_prompt} prompt + {avg_compl} completion\n",
        f"✅ *Success Rate*: {success_rate}%",
        f"  (agents\\_ok≥3 + eec\\_valid)\n",
        "🔀 *Маршруты (Router)*",
    ]
    for route, cnt in sorted(routes.items(), key=lambda x: -x[1]):
        lines.append(f"  `{route}`: {cnt} запросов")

    return "\n".join(lines)
