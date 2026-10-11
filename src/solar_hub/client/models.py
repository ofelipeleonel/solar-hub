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


class InverterChannelSummary(BaseModel):
    """Resumo de energia por canal DC de um microinversor específico."""
    d1: Optional[str] = "0.0"
    m1: Optional[str] = "0.0"
    y1: Optional[str] = "0.0"
    t1: Optional[str] = "0.0"
    d2: Optional[str] = "0.0"
    m2: Optional[str] = "0.0"
    y2: Optional[str] = "0.0"
    t2: Optional[str] = "0.0"
    d3: Optional[str] = "0.0"
    m3: Optional[str] = "0.0"
    y3: Optional[str] = "0.0"
    t3: Optional[str] = "0.0"
    d4: Optional[str] = "0.0"
    m4: Optional[str] = "0.0"
    y4: Optional[str] = "0.0"
    t4: Optional[str] = "0.0"

    @property
    def channel_today_kwh(self) -> dict[int, float]:
        """Retorna dicionário mapeando canal DC para a geração de hoje em kWh."""
        res = {}
        for ch, val in [(1, self.d1), (2, self.d2), (3, self.d3), (4, self.d4)]:
            if val is not None:
                try:
                    res[ch] = float(val)
                except (ValueError, TypeError):
                    res[ch] = 0.0
        return res


class InverterTelemetry(BaseModel):
    """Telemetria elétrica fina (minutely) de um microinversor."""
    t: List[str] = Field(default_factory=list, description="Lista de horários de leitura (HH:mm)")
    dc_p1: Optional[List[str]] = Field(None, description="Potência DC canal 1 (W)")
    dc_p2: Optional[List[str]] = Field(None, description="Potência DC canal 2 (W)")
    dc_p3: Optional[List[str]] = Field(None, description="Potência DC canal 3 (W)")
    dc_p4: Optional[List[str]] = Field(None, description="Potência DC canal 4 (W)")
    dc_i1: Optional[List[str]] = Field(None, description="Corrente DC canal 1 (A)")
    dc_i2: Optional[List[str]] = Field(None, description="Corrente DC canal 2 (A)")
    dc_i3: Optional[List[str]] = Field(None, description="Corrente DC canal 3 (A)")
    dc_i4: Optional[List[str]] = Field(None, description="Corrente DC canal 4 (A)")
    dc_v1: Optional[List[str]] = Field(None, description="Tensão DC canal 1 (V)")
    dc_v2: Optional[List[str]] = Field(None, description="Tensão DC canal 2 (V)")
    dc_v3: Optional[List[str]] = Field(None, description="Tensão DC canal 3 (V)")
    dc_v4: Optional[List[str]] = Field(None, description="Tensão DC canal 4 (V)")
    dc_e1: Optional[List[str]] = Field(None, description="Energia DC canal 1 (kWh)")
    dc_e2: Optional[List[str]] = Field(None, description="Energia DC canal 2 (kWh)")
    dc_e3: Optional[List[str]] = Field(None, description="Energia DC canal 3 (kWh)")
    dc_e4: Optional[List[str]] = Field(None, description="Energia DC canal 4 (kWh)")
    ac_v1: Optional[List[str]] = Field(None, description="Tensão AC Fase 1 (V)")
    ac_v2: Optional[List[str]] = Field(None, description="Tensão AC Fase 2 (V)")
    ac_v3: Optional[List[str]] = Field(None, description="Tensão AC Fase 3 (V)")
    ac_t: Optional[List[str]] = Field(None, description="Temperatura interna do inversor (°C)")
    ac_p: Optional[List[str]] = Field(None, description="Potência AC total (W)")
    ac_f: Optional[List[str]] = Field(None, description="Frequência da rede elétrica (Hz)")

    def get_latest_snapshot(self) -> dict[str, Any]:
        """Extrai o snapshot com as leituras mais recentes disponíveis."""
        def last_val(lst: Optional[List[str]]) -> Optional[float]:
            if lst and len(lst) > 0:
                for item in reversed(lst):
                    if item not in (None, "", "null", "-"):
                        try:
                            return float(item)
                        except (ValueError, TypeError):
                            pass
            return None

        time_str = self.t[-1] if self.t else "-"
        return {
            "time": time_str,
            "dc_power_w": {
                1: last_val(self.dc_p1),
                2: last_val(self.dc_p2),
                3: last_val(self.dc_p3),
                4: last_val(self.dc_p4),
            },
            "dc_voltage_v": {
                1: last_val(self.dc_v1),
                2: last_val(self.dc_v2),
                3: last_val(self.dc_v3),
                4: last_val(self.dc_v4),
            },
            "dc_current_a": {
                1: last_val(self.dc_i1),
                2: last_val(self.dc_i2),
                3: last_val(self.dc_i3),
                4: last_val(self.dc_i4),
            },
            "ac_voltage_v": last_val(self.ac_v1),
            "ac_power_w": last_val(self.ac_p),
            "temperature_c": last_val(self.ac_t),
            "frequency_hz": last_val(self.ac_f),
        }


class ChannelEnergyItem(BaseModel):
    """Item individual de geração de um canal retornado no lote da ECU."""
    uid: str
    channel: int
    energy_kwh: float


class EcuBatchEnergy(BaseModel):
    """Resposta consolidada em lote de energia de todos os inversores de uma ECU."""
    energy: Optional[List[str]] = Field(default_factory=list, description="Lista de strings 'uid-canal-energia'")
    time: Optional[List[str]] = None
    power: Optional[dict[str, List[float]]] = None

    def get_channel_items(self) -> List[ChannelEnergyItem]:
        """Faz o parsing das strings 'uid-channel-energy' (ex: '701000001234-1-1.24')."""
        items: List[ChannelEnergyItem] = []
        if not self.energy:
            return items
        for entry in self.energy:
            parts = entry.split("-")
            if len(parts) >= 3:
                uid, ch_str, val_str = parts[0], parts[1], parts[2]
                try:
                    items.append(
                        ChannelEnergyItem(
                            uid=uid,
                            channel=int(ch_str),
                            energy_kwh=float(val_str),
                        )
                    )
                except (ValueError, TypeError):
                    continue
        return items
