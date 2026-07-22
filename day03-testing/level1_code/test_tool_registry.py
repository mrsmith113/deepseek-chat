"""Unit тесты Tool Registry + Executor — task35/tool_registry.py.

Декоратор регистрирует инструмент, обёртка замеряет latency и дёргает
metrics-recorder (ok/fail), опасные инструменты помечаются флагом.
"""
import pytest
import tool_registry as tr


@pytest.fixture(autouse=True)
def clean_registry():
    """Изолируем глобальный реестр и recorder между тестами."""
    saved = dict(tr.TOOL_REGISTRY)
    saved_rec = tr._metrics_recorder
    tr.TOOL_REGISTRY.clear()
    tr.set_metrics_recorder(None)
    yield
    tr.TOOL_REGISTRY.clear()
    tr.TOOL_REGISTRY.update(saved)
    tr._metrics_recorder = saved_rec


def test_register_puts_tool_in_registry():
    @tr.register_tool("search_hs", "поиск кода ТН ВЭД")
    def search(q):
        return f"code:{q}"

    assert "search_hs" in tr.TOOL_REGISTRY
    assert tr.TOOL_REGISTRY["search_hs"]["description"] == "поиск кода ТН ВЭД"
    assert tr.TOOL_REGISTRY["search_hs"]["dangerous"] is False


def test_wrapper_returns_result_and_preserves_name():
    @tr.register_tool("echo", "echo tool")
    def echo(x):
        return x * 2

    assert echo(21) == 42
    assert echo.__name__ == "echo"          # functools.wraps сохранил имя


def test_recorder_called_on_success():
    calls = []
    tr.set_metrics_recorder(lambda name, elapsed, ok: calls.append((name, ok)))

    @tr.register_tool("ok_tool", "ok")
    def ok_tool():
        return "done"

    ok_tool()
    assert calls == [("ok_tool", True)]


def test_recorder_called_on_failure_and_reraises():
    calls = []
    tr.set_metrics_recorder(lambda name, elapsed, ok: calls.append((name, ok)))

    @tr.register_tool("boom", "падает")
    def boom():
        raise ValueError("bang")

    with pytest.raises(ValueError, match="bang"):
        boom()
    assert calls == [("boom", False)]       # метрика зафиксировала провал


def test_dangerous_flag_and_timeout_stored():
    @tr.register_tool("delete_all", "опасно", dangerous=True, timeout=60)
    def delete_all():
        return "ok"

    spec = tr.TOOL_REGISTRY["delete_all"]
    assert spec["dangerous"] is True
    assert spec["timeout"] == 60


def test_list_tools_empty():
    assert "не зарегистрированы" in tr.list_tools()


def test_list_tools_marks_dangerous():
    @tr.register_tool("safe", "безопасно")
    def safe():
        ...

    @tr.register_tool("nuke", "опасно", dangerous=True)
    def nuke():
        ...

    out = tr.list_tools()
    assert "safe" in out and "nuke" in out
    assert "DANGEROUS" in out
