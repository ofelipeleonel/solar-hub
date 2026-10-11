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

    # Configurações de Fuso Horário e Janela Solar (atualizadas pela descoberta da API)
    timezone: str = Field("UTC", alias="TIMEZONE", description="Fuso horário padrão (atualizado dinamicamente pela API)")
    solar_window_start: str = Field("06:30", alias="SOLAR_WINDOW_START", description="Horário inicial para coletas diurnas (HH:MM)")
    solar_window_end: str = Field("18:30", alias="SOLAR_WINDOW_END", description="Horário final para coletas diurnas (HH:MM)")
    nightly_sync_time: str = Field("20:00", alias="NIGHTLY_SYNC_TIME", description="Horário da consolidação noturna definitiva")

    # Execução em Background
    enable_daemon: bool = Field(False, alias="ENABLE_DAEMON", description="Inicia automaticamente o coletor em background junto com o servidor web")

    # Sistema de Alertas e Notificações (Webhooks & Telegram)
    alert_webhook_url: Optional[str] = Field(None, alias="ALERT_WEBHOOK_URL", description="URL para disparos de webhook genérico (Discord, Slack, Home Assistant, etc.)")
    alert_telegram_bot_token: Optional[str] = Field(None, alias="ALERT_TELEGRAM_BOT_TOKEN", description="Token do bot Telegram (BotFather)")
    alert_telegram_chat_id: Optional[str] = Field(None, alias="ALERT_TELEGRAM_CHAT_ID", description="Chat ID de destino no Telegram")
    alert_cooldown_hours: int = Field(4, alias="ALERT_COOLDOWN_HOURS", description="Janela de silenciamento para alertas idênticos (horas)")
    alert_min_health_score: int = Field(80, alias="ALERT_MIN_HEALTH_SCORE", description="Dispara alerta se o índice de saúde ficar abaixo deste percentual")
    alert_quota_warning_pct: float = Field(85.0, alias="ALERT_QUOTA_WARNING_PCT", description="Dispara alerta se o consumo da cota mensal ultrapassar este percentual")
    alert_midday_check: bool = Field(True, alias="ALERT_MIDDAY_CHECK", description="Alerta de geração zero no pico solar do meio-dia")

    # Integração MQTT & Home Assistant Discovery
    mqtt_enabled: bool = Field(False, alias="MQTT_ENABLED", description="Habilita publicação MQTT e descoberta automática no Home Assistant")
    mqtt_broker: str = Field("localhost", alias="MQTT_BROKER", description="Host ou IP do broker MQTT (ex: homeassistant.local)")
    mqtt_port: int = Field(1883, alias="MQTT_PORT", description="Porta TCP do broker MQTT")
    mqtt_username: Optional[str] = Field(None, alias="MQTT_USERNAME", description="Usuário de autenticação MQTT (opcional)")
    mqtt_password: Optional[str] = Field(None, alias="MQTT_PASSWORD", description="Senha de autenticação MQTT (opcional)")
    mqtt_discovery_prefix: str = Field("homeassistant", alias="MQTT_DISCOVERY_PREFIX", description="Prefixo de auto-descoberta do Home Assistant")
    mqtt_topic_prefix: str = Field("solarhub", alias="MQTT_TOPIC_PREFIX", description="Prefixo dos tópicos de estado do SolarHub")

    # Autenticação e Segurança (Dashboard Web e API)
    auth_username: Optional[str] = Field(None, alias="AUTH_USERNAME", description="Usuário para proteção HTTP Basic Auth do Dashboard/API")
    auth_password: Optional[str] = Field(None, alias="AUTH_PASSWORD", description="Senha para proteção HTTP Basic Auth do Dashboard/API")
    api_key: Optional[str] = Field(None, alias="API_KEY", description="Chave de API secreta para acesso via header X-API-Key ou Bearer")
    cors_origins: str = Field("*", alias="CORS_ORIGINS", description="Origens CORS permitidas separadas por vírgula (ex: 'https://meudominio.com')")
    allow_private_webhooks: bool = Field(False, alias="ALLOW_PRIVATE_WEBHOOKS", description="Permite disparos para redes privadas (mantenha false em VPS pública)")

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
