"""
tool_registry.py — Tool Registry + Executor.
Концепция курса БЛМ: Tool Registry, Tool Executor, Dangerous Operations.

Каждый инструмент регистрируется декоратором @register_tool.
Executor автоматически пишет метрики latency/ok при вызове.
Dangerous-инструменты помечены флагом — требуют HITL-подтверждения.
"""
import time
import logging
from functools import wraps
from typing import Callable, Any

log = logging.getLogger(__name__)

# Единый реестр инструментов: name → spec
TOOL_REGISTRY: dict[str, dict] = {}

# Колбэк для записи метрик (устанавливается из metrics.py через set_metrics_recorder)
_metrics_recorder = None


def set_metrics_recorder(recorder):
    global _metrics_recorder
    _metrics_recorder = recorder


def register_tool(name: str, description: str, dangerous: bool = False, timeout: int = 30):
    """
    Декоратор регистрации инструмента в реестре.

    Оборачивает функцию: при каждом вызове замеряет latency и вызывает _metrics_recorder.
    dangerous=True — инструмент требует HITL-подтверждения (отмечается в /tools).
    """
    def deco(fn: Callable) -> Callable:
        TOOL_REGISTRY[name] = {
            "fn": fn,
            "description": description,
            "dangerous": dangerous,
            "timeout": timeout,
        }

        @wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                result = fn(*args, **kwargs)
                elapsed = time.time() - t0
                if _metrics_recorder:
                    _metrics_recorder(name, elapsed, ok=True)
                log.debug(f"[Tool] {name} OK ({elapsed:.2f}s)")
                return result
            except Exception as e:
                elapsed = time.time() - t0
                if _metrics_recorder:
                    _metrics_recorder(name, elapsed, ok=False)
                log.warning(f"[Tool] {name} FAILED ({elapsed:.2f}s): {e}")
                raise

        return wrapper
    return deco


def list_tools() -> str:
    """Форматированный список всех зарегистрированных инструментов для /tools."""
    if not TOOL_REGISTRY:
        return "Инструменты не зарегистрированы."
    lines = [f"📋 *Tool Registry* — {len(TOOL_REGISTRY)} инструментов:\n"]
    for name, spec in sorted(TOOL_REGISTRY.items()):
        danger = " ⚠️ *DANGEROUS*" if spec["dangerous"] else ""
        lines.append(f"• `{name}` (timeout={spec['timeout']}s){danger}\n  _{spec['description']}_")
    return "\n".join(lines)
