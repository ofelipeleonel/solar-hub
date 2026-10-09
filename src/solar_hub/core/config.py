from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações da aplicação SolarHub carregadas de variáveis de ambiente ou arquivo .env.
    Projetado para ser flexível e adaptável a qualquer usina solar APsystems.
    """
    # Credenciais da OpenAPI APsystems
    apsystems_app_id: str = Field(..., alias="APSYSTEMS_APP_ID", description="App ID (32 caracteres) fornecido pela APsystems")
    apsystems_app_secret: str = Field(..., alias="APSYSTEMS_APP_SECRET", description="App Secret (12 caracteres)")
    apsystems_system_id: str = Field(..., alias="APSYSTEMS_SYSTEM_ID", description="System ID (sid) cadastrado na plataforma EMA")
    apsystems_base_url: str = Field("https://api.apsystemsema.com:9282", alias="APSYSTEMS_BASE_URL")

    # Armazenamento e Banco de Dados
    database_url: str = Field("sqlite:///data/solar_hub.db", alias="DATABASE_URL")
    
    # Orçamento e Governança de Requisições (Budget Keeper)
    monthly_budget_limit: int = Field(1000, alias="MONTHLY_BUDGET_LIMIT", description="Limite total contratual de chamadas por mês")
    reserve_daily_calls: int = Field(4, alias="RESERVE_DAILY_CALLS", description="Chamadas mantidas como margem de segurança para testes/manutenções")
    
    # Configurações do Fuso Horário e Janela Solar
    timezone: str = Field("America/Sao_Paulo", alias="TIMEZONE")
    solar_window_start: str = Field("06:30", alias="SOLAR_WINDOW_START", description="Horário inicial para coletas diurnas (HH:MM)")
    solar_window_end: str = Field("18:30", alias="SOLAR_WINDOW_END", description="Horário final para coletas diurnas (HH:MM)")
    nightly_sync_time: str = Field("20:00", alias="NIGHTLY_SYNC_TIME", description="Horário da consolidação noturna definitiva")
    
    # Parâmetros Financeiros Genéricos (Configuráveis para qualquer região/concessionária)
    currency_symbol: str = Field("R$", alias="CURRENCY_SYMBOL")
    tariff_kwh_rate: float = Field(0.92, alias="TARIFF_KWH_RATE", description="Tarifa média por kWh na moeda local")
    
    # Log
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def db_path(self) -> Path:
        """Retorna o caminho do arquivo do banco SQLite caso a URL seja sqlite."""
        if self.database_url.startswith("sqlite:///"):
            raw_path = self.database_url.replace("sqlite:///", "")
            return Path(raw_path)
        return Path("data/solar_hub.db")
