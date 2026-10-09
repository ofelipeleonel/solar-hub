"""
Hierarquia de exceções especializadas do SolarHub.
"""

class SolarHubError(Exception):
    """Exceção base do sistema SolarHub."""
    pass


class APsystemsAPIError(SolarHubError):
    """Erro retornado pela API da APsystems."""
    def __init__(self, code: int, message: str, endpoint: str = ""):
        self.code = code
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"APsystems API Error [{code}] no endpoint '{endpoint}': {message}")


class APsystemsAuthError(APsystemsAPIError):
    """Falha de autenticação HMAC ou credenciais inválidas (Códigos 2000-2004, 3000-3004)."""
    pass


class QuotaExceededError(APsystemsAPIError):
    """Limite de requisições mensais ou bloqueio de taxa atingido (Código 2005 ou 7001)."""
    pass


class BudgetKeeperBlockError(SolarHubError):
    """Requisição bloqueada preventivamente pelo Budget Keeper local para proteger a cota."""
    def __init__(self, reason: str, calls_made_today: int, budget_limit: int):
        self.reason = reason
        self.calls_made_today = calls_made_today
        self.budget_limit = budget_limit
        super().__init__(f"Budget Keeper: {reason} (Hoje: {calls_made_today}/{budget_limit})")


class HardwareDiscoveryError(SolarHubError):
    """Erro durante o mapeamento automático de usina, ECUs ou microinversores."""
    pass
