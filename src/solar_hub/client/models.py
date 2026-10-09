from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class APsystemsBaseResponse(BaseModel, Generic[T]):
    """Envelope padrão de resposta da OpenAPI APsystems."""
    code: int = Field(..., description="0 para sucesso; outros códigos indicam erro")
    data: Optional[T] = Field(None, description="Payload de dados da requisição")


class SystemDetails(BaseModel):
    """Dados cadastrais e status geral da usina."""
    sid: str = Field(..., description="ID único do sistema")
    create_date: str = Field(..., description="Data de comissionamento (yyyy-MM-dd)")
    capacity: str = Field(..., description="Capacidade nominal instalada em kW")
    type: int = Field(1, description="1: Fotovoltaico, 2: Bateria, 3: Híbrido")
    timezone: str = Field(..., description="Fuso horário da usina")
    ecu: List[str] = Field(default_factory=list, description="Lista de seriais de ECU cadastradas")
    light: int = Field(..., description="1: Verde (Normal), 2: Amarelo, 3: Vermelho, 4: Cinza")
    authorization_code: Optional[str] = None

    @property
    def capacity_kwp(self) -> float:
        try:
            return float(self.capacity)
        except (ValueError, TypeError):
            return 0.0


class InverterInfo(BaseModel):
    """Informações cadastrais de um microinversor."""
    uid: str = Field(..., description="Número de série único do inversor")
    type: str = Field(..., description="Modelo do inversor (ex: YC1000, DS3, QT2, QS1)")
    sub_type: Optional[str] = Field(None, alias="subType")

    @property
    def estimated_channels_count(self) -> int:
        """
        Infere a quantidade de canais DC independentes suportados pelo modelo.
        Suporta dinamicamente toda a linha de microinversores da APsystems.
        """
        model_upper = self.type.upper()
        if any(x in model_upper for x in ["YC1000", "QT2", "QS1", "YC600-4"]):
            return 4
        elif any(x in model_upper for x in ["DS3", "YC600", "YC500"]):
            return 2
        elif any(x in model_upper for x in ["EZ1"]):
            return 2
        return 4  # Padrão seguro para inversores quad-channel


class EcuInverters(BaseModel):
    """Agrupamento de microinversores por ECU."""
    eid: str = Field(..., description="Número de série do gateway ECU")
    timezone: str = Field(..., description="Fuso horário configurado na ECU")
    model: Optional[str] = None
    type: Optional[int] = 0
    inverter: List[InverterInfo] = Field(default_factory=list, description="Lista de microinversores vinculados")


class SystemSummary(BaseModel):
    """Resumo consolidado de geração acumulada do sistema."""
    today: str = Field("0.0", description="Geração do dia corrente em kWh")
    month: str = Field("0.0", description="Geração do mês corrente em kWh")
    year: str = Field("0.0", description="Geração do ano corrente em kWh")
    lifetime: str = Field("0.0", description="Geração total acumulada desde o início da usina em kWh")

    @property
    def today_kwh(self) -> float:
        return float(self.today or 0.0)

    @property
    def month_kwh(self) -> float:
        return float(self.month or 0.0)

    @property
    def year_kwh(self) -> float:
        return float(self.year or 0.0)

    @property
    def lifetime_kwh(self) -> float:
        return float(self.lifetime or 0.0)
