import calendar
import logging
from dataclasses import dataclass
from datetime import datetime

from solar_hub.core.exceptions import BudgetKeeperBlockError
from solar_hub.db.repository import SolarRepository

logger = logging.getLogger(__name__)


@dataclass
class BudgetStatus:
    """Diagnóstico em tempo real da cota da OpenAPI APsystems."""
    calls_this_month: int
    calls_today: int
    monthly_limit: int
    remaining_month: int
    daily_budget_target: int
    is_solar_window: bool
    can_request_now: bool
    reason: str
    quota_exhausted: bool = False
    quota_exhausted_message: str = ""


class BudgetKeeperService:
    """
    O guardião matemático da cota de 1.000 requisições/mês da OpenAPI APsystems.
    Protege a aplicação contra estouro de cota e bloqueios contratuais.
    """

    def __init__(
        self,
        repository: SolarRepository,
        monthly_limit: int = 1000,
        reserve_calls_daily: int = 4,
        window_start: str = "06:30",
        window_end: str = "18:30",
    ):
        self.repository = repository
        self.monthly_limit = monthly_limit
        self.reserve_calls_daily = reserve_calls_daily
        self.window_start_time = datetime.strptime(window_start, "%H:%M").time()
        self.window_end_time = datetime.strptime(window_end, "%H:%M").time()

    def get_status(self, current_dt: datetime | None = None) -> BudgetStatus:
        now = current_dt or datetime.now()
        calls_month = self.repository.count_api_calls_this_month()
        calls_today = self.repository.count_api_calls_today()
        remaining_month = max(0, self.monthly_limit - calls_month)

        # Checagem de bloqueio por erro da nuvem APsystems (Código 2005 / Cota Esgotada)
        quota_flag = self.repository.get_setting("quota_exhausted", "false") == "true"
        quota_month = self.repository.get_setting("quota_exhausted_month", "")
        current_month_str = now.strftime("%Y-%m")
        exhausted_msg = self.repository.get_setting("quota_exhausted_message", "")

        is_exhausted = False
        if quota_flag:
            if quota_month == current_month_str:
                is_exhausted = True
            else:
                # O mês virou: a cota na APsystems renova no primeiro dia de cada mês
                self.clear_quota_exhausted()

        # Dias restantes no mês (incluindo hoje)
        _, days_in_month = calendar.monthrange(now.year, now.month)
        days_remaining = max(1, days_in_month - now.day + 1)
        daily_target = max(1, remaining_month // days_remaining)

        # Checagem de janela solar
        current_time = now.time()
        in_solar_window = self.window_start_time <= current_time <= self.window_end_time

        # Avaliação de permissão
        if is_exhausted:
            can_request = False
            remaining_month = 0
            calls_month = max(calls_month, self.monthly_limit)
            daily_target = 0
            reason = (
                "Cota mensal OpenAPI da APsystems esgotada na nuvem (Código 2005). "
                f"As requisições estão suspensas até o primeiro dia do próximo mês. {exhausted_msg}".strip()
            )
        elif remaining_month <= 0:
            can_request = False
            reason = "Cota mensal de 1.000 requisições totalmente esgotada no livro-razão local!"
        elif calls_today >= daily_target:
            can_request = False
            reason = f"Teto diário calculado ({daily_target} reqs) atingido para hoje."
        elif not in_solar_window:
            can_request = False
            reason = "Fora da janela solar ativa (geração nula à noite; requisição desnecessária)."
        else:
            can_request = True
            reason = "Dentro da cota segura e da janela solar ativa."

        return BudgetStatus(
            calls_this_month=calls_month,
            calls_today=calls_today,
            monthly_limit=self.monthly_limit,
            remaining_month=remaining_month,
            daily_budget_target=daily_target,
            is_solar_window=in_solar_window,
            can_request_now=can_request,
            reason=reason,
            quota_exhausted=is_exhausted,
            quota_exhausted_message=exhausted_msg,
        )

    def mark_quota_exhausted(self, reason: str = "Limite de requisições excedido na APsystems (Código 2005)") -> None:
        """Marca no banco local que a APsystems retornou código 2005 (cota esgotada na nuvem)."""
        now = datetime.now()
        current_month_str = now.strftime("%Y-%m")
        self.repository.set_setting("quota_exhausted", "true")
        self.repository.set_setting("quota_exhausted_month", current_month_str)
        self.repository.set_setting("quota_exhausted_message", reason)
        logger.critical(f"BudgetKeeper: Cota OpenAPI da APsystems marcada como ESGOTADA ({current_month_str}): {reason}")

    def clear_quota_exhausted(self) -> None:
        """Limpa o bloqueio de cota esgotada (ex: na virada do mês ou restauração contratual)."""
        self.repository.set_setting("quota_exhausted", "false")
        self.repository.set_setting("quota_exhausted_month", "")
        self.repository.set_setting("quota_exhausted_message", "")
        logger.info("BudgetKeeper: Bloqueio de cota esgotada limpo com sucesso.")

    def verify_can_request(self, force: bool = False) -> None:
        """
        Lança uma exceção se a requisição violar a política de cota,
        a menos que 'force=True' seja explicitamente passado pelo operador.
        """
        status = self.get_status()
        if not status.can_request_now and not force:
            raise BudgetKeeperBlockError(
                reason=status.reason,
                calls_made_today=status.calls_today,
                budget_limit=status.daily_budget_target,
            )

