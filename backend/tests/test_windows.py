from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo
import pytest

from app.db.models import Sprint
from app.metrics.windows import (
    TimeWindow,
    default_window,
    generate_fixed_windows,
    get_zone_info,
    parse_window,
    window_from_sprint,
)


def test_parse_window_brt_sao_paulo():
    """Valida conversão de datas civis em America/Sao_Paulo (UTC-3) para UTC [from 00:00, to+1d 00:00)."""
    window = parse_window("2026-03-01", "2026-03-14", timezone="America/Sao_Paulo")

    assert window.start_date == dt.date(2026, 3, 1)
    assert window.end_date == dt.date(2026, 3, 14)
    assert window.duration_days == 14
    assert window.timezone == "America/Sao_Paulo"

    # 2026-03-01 00:00:00 BRT (-03:00) == 2026-03-01 03:00:00 UTC
    expected_start = dt.datetime(2026, 3, 1, 3, 0, 0, tzinfo=dt.timezone.utc)
    # 2026-03-15 00:00:00 BRT (-03:00) == 2026-03-15 03:00:00 UTC
    expected_end = dt.datetime(2026, 3, 15, 3, 0, 0, tzinfo=dt.timezone.utc)

    assert window.start_utc == expected_start
    assert window.end_utc == expected_end


def test_parse_window_utc():
    """Valida janela no fuso UTC."""
    window = parse_window("2026-04-10", "2026-04-20", timezone="UTC")

    assert window.start_date == dt.date(2026, 4, 10)
    assert window.end_date == dt.date(2026, 4, 20)
    assert window.duration_days == 11
    assert window.start_utc == dt.datetime(2026, 4, 10, 0, 0, 0, tzinfo=dt.timezone.utc)
    assert window.end_utc == dt.datetime(2026, 4, 21, 0, 0, 0, tzinfo=dt.timezone.utc)


def test_window_contains_events_brt():
    """Testa inclusão e exclusão de eventos nos limites da janela em BRT."""
    window = parse_window("2026-03-01", "2026-03-14", timezone="America/Sao_Paulo")
    brt = ZoneInfo("America/Sao_Paulo")

    # Exatamente no início da janela (00:00 local)
    ev_start = dt.datetime(2026, 3, 1, 0, 0, 0, tzinfo=brt)
    assert window.contains(ev_start) is True

    # Meio da janela
    ev_mid = dt.datetime(2026, 3, 7, 15, 30, 0, tzinfo=brt)
    assert window.contains(ev_mid) is True

    # Último segundo da janela inclusiva (23:59:59 local)
    ev_last = dt.datetime(2026, 3, 14, 23, 59, 59, tzinfo=brt)
    assert window.contains(ev_last) is True

    # 1 segundo antes do início
    ev_before = dt.datetime(2026, 2, 28, 23, 59, 59, tzinfo=brt)
    assert window.contains(ev_before) is False

    # Primeiro segundo após o término (00:00:00 do dia 15 local)
    ev_after = dt.datetime(2026, 3, 15, 0, 0, 0, tzinfo=brt)
    assert window.contains(ev_after) is False


def test_window_contains_naive_raises():
    """Verifica que datetime naive levanta erro."""
    window = parse_window("2026-03-01", "2026-03-14")
    with pytest.raises(ValueError, match="fuso horário"):
        window.contains(dt.datetime(2026, 3, 5, 12, 0, 0))


def test_invalid_window_dates():
    """Verifica erro quando start > end."""
    with pytest.raises(ValueError, match="não pode ser posterior"):
        parse_window("2026-03-15", "2026-03-10")


def test_invalid_timezone():
    """Verifica erro para nome de fuso inexistente."""
    with pytest.raises(ValueError, match="Fuso horário inválido"):
        parse_window("2026-03-01", "2026-03-14", timezone="Planeta/Marte")


def test_window_from_sprint():
    """Valida construção a partir do modelo Sprint com UTCDateTime."""
    tz = ZoneInfo("America/Sao_Paulo")
    # Sprint configurada das 00:00 do dia 01/06 às 23:59:59 do dia 14/06 em SP
    start_utc = dt.datetime(2026, 6, 1, 3, 0, 0, tzinfo=dt.timezone.utc)
    end_utc = dt.datetime(2026, 6, 14, 23, 59, 0, tzinfo=dt.timezone.utc)

    sprint = Sprint(
        id="sprint-test",
        project_id="proj-1",
        name="Sprint 1",
        start_date=start_utc,
        end_date=end_utc,
    )

    window = window_from_sprint(sprint, timezone="America/Sao_Paulo")
    assert window.start_date == dt.date(2026, 6, 1)
    assert window.end_date == dt.date(2026, 6, 14)
    assert window.duration_days == 14
    assert window.start_utc == dt.datetime(2026, 6, 1, 3, 0, 0, tzinfo=dt.timezone.utc)
    assert window.end_utc == dt.datetime(2026, 6, 15, 3, 0, 0, tzinfo=dt.timezone.utc)


def test_generate_fixed_windows():
    """Testa partição de um período de 35 dias em blocos de 14 dias."""
    windows = generate_fixed_windows("2026-01-01", "2026-02-04", period_days=14, timezone="UTC")
    # 35 dias: [01/01 a 14/01 (14d)], [15/01 a 28/01 (14d)], [29/01 a 04/02 (7d)]
    assert len(windows) == 3
    assert windows[0].start_date == dt.date(2026, 1, 1)
    assert windows[0].end_date == dt.date(2026, 1, 14)
    assert windows[0].duration_days == 14

    assert windows[1].start_date == dt.date(2026, 1, 15)
    assert windows[1].end_date == dt.date(2026, 1, 28)
    assert windows[1].duration_days == 14

    assert windows[2].start_date == dt.date(2026, 1, 29)
    assert windows[2].end_date == dt.date(2026, 2, 4)
    assert windows[2].duration_days == 7


def test_default_window():
    """Testa janela padrão de 30 dias em relação a data de referência."""
    ref = dt.date(2026, 3, 30)
    window = default_window(timezone="America/Sao_Paulo", days=30, reference_date=ref)
    assert window.end_date == dt.date(2026, 3, 30)
    assert window.start_date == dt.date(2026, 3, 1)
    assert window.duration_days == 30
