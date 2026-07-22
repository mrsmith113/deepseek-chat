"""Integration тесты метрик AI Pipeline — task35/metrics.py.

Пишем записи в изолированный временный JSONL (monkeypatch METRICS_FILE),
читаем обратно и проверяем перцентили, стоимость, success rate, отчёт.
"""
import pytest
import metrics


@pytest.fixture
def tmp_metrics(tmp_path, monkeypatch):
    """Изолируем файл метрик — не трогаем /tmp/rag_orchestrator_metrics.jsonl."""
    f = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(metrics, "METRICS_FILE", str(f))
    return f


# ---------- _perc ----------

def test_perc_empty_is_zero():
    assert metrics._perc([], 95) == 0.0


def test_perc_p50_median_ish():
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert metrics._perc(vals, 50) == 5.0


def test_perc_p99_high_tail():
    # Реализация: idx = int(p/100*len)-1 → для 10 значений P99 = s[8] = 9.0
    # (верхний хвост, не максимум — так работает их формула перцентиля)
    assert metrics._perc([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 99) == 9.0


def test_perc_monotonic_p50_le_p95():
    vals = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
    assert metrics._perc(vals, 50) <= metrics._perc(vals, 95)


# ---------- запись/чтение roundtrip ----------

def test_record_then_load(tmp_metrics):
    metrics.record_request(
        route="CODE_LOOKUP",
        latency_breakdown={"agents": 1.0, "llm": 3.0, "total": 4.0},
        prompt_tokens=1000, completion_tokens=500,
        agents_ok=4, eec_valid=True, codes_found=2,
    )
    entries = metrics._load_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["route"] == "CODE_LOOKUP"
    assert e["latency"]["total"] == 4.0
    assert e["codes_found"] == 2


def test_cost_calculation(tmp_metrics):
    # DeepSeek: prompt $0.27/1M, completion $1.10/1M
    metrics.record_request("FULL_PIPELINE", {"total": 1.0},
                           prompt_tokens=1_000_000, completion_tokens=1_000_000)
    e = metrics._load_entries()[0]
    assert e["cost_usd"] == pytest.approx(0.27 + 1.10, rel=1e-6)


def test_load_entries_missing_file_is_empty(tmp_metrics):
    assert metrics._load_entries() == []


# ---------- build_stats_report ----------

def test_report_empty_message(tmp_metrics):
    rep = metrics.build_stats_report()
    assert "Нет данных" in rep


def test_report_success_rate_counts_only_valid(tmp_metrics):
    # 1 успешный (agents_ok>=3 + eec_valid), 1 провальный
    metrics.record_request("FULL_PIPELINE", {"total": 5.0}, agents_ok=4, eec_valid=True)
    metrics.record_request("FULL_PIPELINE", {"total": 6.0}, agents_ok=2, eec_valid=False)
    rep = metrics.build_stats_report()
    assert "2 запросов" in rep          # всего записей
    assert "50.0%" in rep               # success rate 1 из 2


def test_report_lists_routes(tmp_metrics):
    metrics.record_request("CODE_LOOKUP", {"total": 1.0})
    metrics.record_request("CODE_LOOKUP", {"total": 1.2})
    metrics.record_request("FULL_PIPELINE", {"total": 5.0})
    rep = metrics.build_stats_report()
    assert "CODE_LOOKUP" in rep
    assert "FULL_PIPELINE" in rep
