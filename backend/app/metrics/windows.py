from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..db.models import Sprint


@dataclass(frozen=True)
class TimeWindow:
    """
    Representa uma janela temporal para métricas e consultas no grafo.
    Conforme SPEC §7.1 regra 4:
    - Intervalo no fuso local: [from_date 00:00:00, to_date + 1 dia 00:00:00)
    - Convertido internamente para UTC tz-aware: [start_utc, end_utc)
    """

    start_date: dt.date
    end_date: dt.date
    timezone: str
    start_utc: dt.datetime
    end_utc: dt.datetime

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError(
                f"Data inicial ({self.start_date}) não pode ser posterior à data final ({self.end_date})"
            )
        if self.start_utc.tzinfo is None or self.start_utc.utcoffset() is None:
            raise ValueError("start_utc deve incluir fuso horário UTC")
        if self.end_utc.tzinfo is None or self.end_utc.utcoffset() is None:
            raise ValueError("end_utc deve incluir fuso horário UTC")
        if self.start_utc >= self.end_utc:
            raise ValueError("start_utc deve ser anterior a end_utc")

    def contains(self, timestamp: dt.datetime) -> bool:
        """Verifica se um datetime com tzinfo está contido no intervalo semiaberto [start_utc, end_utc)."""
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("O datetime deve incluir fuso horário para checagem na janela")
        utc_ts = timestamp.astimezone(dt.timezone.utc)
        return self.start_utc <= utc_ts < self.end_utc

    @property
    def duration_days(self) -> int:
        """Duração da janela em dias inclusivos."""
        return (self.end_date - self.start_date).days + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.start_date.isoformat(),
            "to": self.end_date.isoformat(),
            "timezone": self.timezone,
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "duration_days": self.duration_days,
        }

    def to_tuple(self) -> tuple[dt.datetime, dt.datetime]:
        """Retorna tupla (start_utc, end_utc)."""
        return self.start_utc, self.end_utc


def get_zone_info(tz_name: str) -> ZoneInfo:
    """Valida e retorna o ZoneInfo para o nome IANA informado."""
    if not tz_name or not isinstance(tz_name, str):
        raise ValueError("Nome de fuso horário inválido")
    try:
        return ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValueError(f"Fuso horário inválido ou não suportado: '{tz_name}'") from err


def _parse_date(value: str | dt.date | dt.datetime, tz: ZoneInfo) -> dt.date:
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            return value.astimezone(tz).date()
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        clean = value.strip()
        # Se contiver T ou espaço, tenta parse ISO completo
        if "T" in clean or " " in clean:
            parsed_dt = dt.datetime.fromisoformat(clean)
            if parsed_dt.tzinfo is not None:
                return parsed_dt.astimezone(tz).date()
            return parsed_dt.date()
        return dt.date.fromisoformat(clean)
    raise ValueError(f"Formato de data inválido: {type(value)}")


def parse_window(
    from_date: str | dt.date | dt.datetime,
    to_date: str | dt.date | dt.datetime,
    timezone: str = "America/Sao_Paulo",
) -> TimeWindow:
    """
    Constrói um TimeWindow a partir de datas/strings de início e fim no fuso especificado.
    Converte [from 00:00, to+1d 00:00) local para UTC tz-aware.
    """
    tz = get_zone_info(timezone)
    s_date = _parse_date(from_date, tz)
    e_date = _parse_date(to_date, tz)

    if s_date > e_date:
        raise ValueError(
            f"Data inicial ({s_date.isoformat()}) não pode ser posterior à data final ({e_date.isoformat()})"
        )

    # Início: 00:00:00 no fuso local
    local_start = dt.datetime.combine(s_date, dt.time.min, tzinfo=tz)
    # Fim (semiaberto): 00:00:00 do dia seguinte no fuso local
    next_day = e_date + dt.timedelta(days=1)
    local_end = dt.datetime.combine(next_day, dt.time.min, tzinfo=tz)

    start_utc = local_start.astimezone(dt.timezone.utc)
    end_utc = local_end.astimezone(dt.timezone.utc)

    return TimeWindow(
        start_date=s_date,
        end_date=e_date,
        timezone=tz.key if hasattr(tz, "key") else timezone,
        start_utc=start_utc,
        end_utc=end_utc,
    )


def window_from_sprint(
    sprint: Sprint,
    timezone: str = "America/Sao_Paulo",
) -> TimeWindow:
    """
    Constrói um TimeWindow a partir de uma Sprint do SQLite.
    A sprint armazena start_date e end_date em UTCDateTime.
    """
    if sprint.start_date is None or sprint.end_date is None:
        raise ValueError(f"Sprint '{sprint.name}' não possui datas completas de início e fim")

    tz = get_zone_info(timezone)
    # Converter as datas UTC da sprint para a data civil correspondente no fuso do projeto
    s_date = sprint.start_date.astimezone(tz).date()
    e_date = sprint.end_date.astimezone(tz).date()

    return parse_window(s_date, e_date, timezone=timezone)


def generate_fixed_windows(
    start_date: str | dt.date,
    end_date: str | dt.date,
    period_days: int = 14,
    timezone: str = "America/Sao_Paulo",
) -> list[TimeWindow]:
    """
    Gera períodos fixos consecutivos de `period_days` (padrão 14 dias)
    dentro do intervalo especificado, para análise de evolução temporal (SPEC §7.4 C).
    """
    if period_days <= 0:
        raise ValueError("O período em dias deve ser estritamente positivo")

    tz = get_zone_info(timezone)
    s_date = _parse_date(start_date, tz)
    e_date = _parse_date(end_date, tz)

    if s_date > e_date:
        raise ValueError("Data inicial não pode ser posterior à data final")

    windows: list[TimeWindow] = []
    curr_start = s_date

    while curr_start <= e_date:
        curr_end = curr_start + dt.timedelta(days=period_days - 1)
        if curr_end > e_date:
            curr_end = e_date
        windows.append(parse_window(curr_start, curr_end, timezone=timezone))
        curr_start = curr_end + dt.timedelta(days=1)

    return windows


def default_window(
    timezone: str = "America/Sao_Paulo",
    days: int = 30,
    reference_date: dt.date | None = None,
) -> TimeWindow:
    """
    Retorna uma janela padrão dos últimos N dias (SPEC §11: padrão 30 dias)
    em relação a reference_date (ou hoje no fuso local).
    """
    if days <= 0:
        raise ValueError("O número de dias deve ser maior que zero")

    tz = get_zone_info(timezone)
    if reference_date is None:
        today = dt.datetime.now(tz).date()
    else:
        today = reference_date

    start = today - dt.timedelta(days=days - 1)
    return parse_window(start, today, timezone=timezone)
