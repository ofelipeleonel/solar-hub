import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from solar_hub.db.models import InverterChannelTelemetryRecord
from solar_hub.db.repository import SolarRepository

logger = logging.getLogger(__name__)


@dataclass
class Anomaly:
    """Representação estruturada de uma anomalia elétrica detectada."""
    anomaly_type: str  # DEAD_CHANNEL, UNDERPERFORMING_CHANNEL, OVERHEATING, GRID_VOLTAGE_FAULT
    severity: str      # CRITICAL, WARNING, INFO
    message: str
    inverter_uid: Optional[str] = None
    channel: Optional[int] = None
    detected_value: Optional[float] = None
    reference_value: Optional[float] = None


@dataclass
class ChannelDiagnostic:
    """Diagnóstico individual de um canal DC / painel solar."""
    inverter_uid: str
    channel: int
    energy_today_kwh: float
    power_w: Optional[float] = None
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None
    temperature_c: Optional[float] = None
    deviation_pct: float = 0.0
    status: str = "NORMAL"  # NORMAL, UNDERPERFORMING, DEAD


@dataclass
class DiagnosticReport:
    """Relatório completo de saúde e telemetria da usina fotovoltaica."""
    health_score: int  # 0 a 100%
    status: str        # HEALTHY, ATTENTION, CRITICAL
    channels_evaluated: int
    anomalies: List[Anomaly] = field(default_factory=list)
    channel_details: List[ChannelDiagnostic] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    average_channel_kwh: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DiagnosticService:
    """
    Motor autônomo de inteligência e diagnóstico para microinversores APsystems.
    Analisa grandezas elétricas (V, A, W, °C, Hz) e identifica desvios de desempenho
    por painel solar, sombreamento, desconexões e estresse térmico.
    """

    def __init__(self, repository: SolarRepository):
        self.repository = repository

    def evaluate_channels(
        self,
        channels: List[InverterChannelTelemetryRecord],
        ambient_threshold_kwh: float = 0.3,
        underperforming_tolerance_pct: float = 30.0,
    ) -> DiagnosticReport:
        """
        Executa a avaliação estatística e diagnóstica sobre a telemetria dos canais.
        """
        if not channels:
            return DiagnosticReport(
                health_score=100,
                status="SEM_DADOS",
                channels_evaluated=0,
                recommendations=["Execute uma coleta de canais ('solar channels') para obter dados de telemetria."],
            )

        # 1. Calcula a média de geração entre os canais ativos
        active_energies = [ch.energy_today_kwh for ch in channels if ch.energy_today_kwh > 0.05]
        mean_kwh = sum(active_energies) / len(active_energies) if active_energies else 0.0

        anomalies: List[Anomaly] = []
        channel_details: List[ChannelDiagnostic] = []
        recommendations: List[str] = []

        # 2. Avaliação canal a canal
        for ch in channels:
            energy = ch.energy_today_kwh
            deviation_pct = 0.0
            channel_status = "NORMAL"

            if mean_kwh > 0.05:
                deviation_pct = round(((energy - mean_kwh) / mean_kwh) * 100.0, 1)

            # Regra A: Canal Morto (Dead Channel)
            if energy <= 0.01 and mean_kwh >= ambient_threshold_kwh:
                channel_status = "DEAD"
                anom = Anomaly(
                    anomaly_type="DEAD_CHANNEL",
                    severity="CRITICAL",
                    message=(
                        f"Inversor {ch.inverter_uid[-4:]} Canal {ch.channel}: Geração nula ({energy:.2f} kWh) "
                        f"enquanto a média da usina é {mean_kwh:.2f} kWh."
                    ),
                    inverter_uid=ch.inverter_uid,
                    channel=ch.channel,
                    detected_value=energy,
                    reference_value=mean_kwh,
                )
                anomalies.append(anom)
                recommendations.append(
                    f"Verifique o conector MC4 e a fiação do canal {ch.channel} no inversor {ch.inverter_uid}."
                )

            # Regra B: Desempenho Abaixo do Esperado (Underperforming / Sujeira / Sombreamento)
            elif deviation_pct < -underperforming_tolerance_pct and mean_kwh >= ambient_threshold_kwh:
                channel_status = "UNDERPERFORMING"
                anom = Anomaly(
                    anomaly_type="UNDERPERFORMING_CHANNEL",
                    severity="WARNING",
                    message=(
                        f"Inversor {ch.inverter_uid[-4:]} Canal {ch.channel}: Produção {abs(deviation_pct):.1f}% abaixo da média "
                        f"({energy:.2f} kWh vs média {mean_kwh:.2f} kWh)."
                    ),
                    inverter_uid=ch.inverter_uid,
                    channel=ch.channel,
                    detected_value=energy,
                    reference_value=mean_kwh,
                )
                anomalies.append(anom)
                recommendations.append(
                    f"Inspecione se há sujeira, fezes de pássaros ou sombreamento sobre a placa do canal {ch.channel} (inversor {ch.inverter_uid[-4:]})."
                )

            # Regra C: Sobreaquecimento Térmico do Inversor (Overheating)
            if ch.temperature_c is not None:
                if ch.temperature_c >= 75.0:
                    anomalies.append(
                        Anomaly(
                            anomaly_type="OVERHEATING",
                            severity="CRITICAL",
                            message=f"Inversor {ch.inverter_uid}: Temperatura crítica de {ch.temperature_c:.1f}°C (risco de desligamento).",
                            inverter_uid=ch.inverter_uid,
                            detected_value=ch.temperature_c,
                            reference_value=65.0,
                        )
                    )
                    recommendations.append(
                        f"Verifique o fluxo de ar e a fixação sob as placas do inversor {ch.inverter_uid[-4:]}."
                    )
                elif ch.temperature_c >= 65.0:
                    anomalies.append(
                        Anomaly(
                            anomaly_type="OVERHEATING",
                            severity="WARNING",
                            message=f"Inversor {ch.inverter_uid}: Temperatura elevada ({ch.temperature_c:.1f}°C).",
                            inverter_uid=ch.inverter_uid,
                            detected_value=ch.temperature_c,
                            reference_value=65.0,
                        )
                    )

            # Regra D: Tensão AC fora dos limites (Grid Voltage Fault)
            if ch.voltage_v is not None and ch.voltage_v > 100.0:
                # Tensão nominal de rede 220V/230V
                if ch.voltage_v < 185.0 or ch.voltage_v > 255.0:
                    anomalies.append(
                        Anomaly(
                            anomaly_type="GRID_VOLTAGE_FAULT",
                            severity="CRITICAL",
                            message=f"Inversor {ch.inverter_uid}: Tensão de rede instável ({ch.voltage_v:.1f} V).",
                            inverter_uid=ch.inverter_uid,
                            detected_value=ch.voltage_v,
                            reference_value=220.0,
                        )
                    )
                    recommendations.append(
                        f"Monitore oscilações de tensão da distribuidora no ponto de conexão do inversor {ch.inverter_uid[-4:]}."
                    )

            channel_details.append(
                ChannelDiagnostic(
                    inverter_uid=ch.inverter_uid,
                    channel=ch.channel,
                    energy_today_kwh=energy,
                    power_w=ch.power_w,
                    voltage_v=ch.voltage_v,
                    current_a=ch.current_a,
                    temperature_c=ch.temperature_c,
                    deviation_pct=deviation_pct,
                    status=channel_status,
                )
            )

        # 3. Cálculo do Health Score (0 a 100%)
        critical_count = sum(1 for a in anomalies if a.severity == "CRITICAL")
        warning_count = sum(1 for a in anomalies if a.severity == "WARNING")

        penalty = (critical_count * 25) + (warning_count * 10)
        score = max(0, min(100, 100 - penalty))

        if score >= 90:
            status_text = "HEALTHY"
        elif score >= 60:
            status_text = "ATTENTION"
        else:
            status_text = "CRITICAL"

        if not recommendations:
            recommendations.append("Todos os painéis e inversores operando com equilíbrio elétrico ideal.")

        return DiagnosticReport(
            health_score=score,
            status=status_text,
            channels_evaluated=len(channels),
            anomalies=anomalies,
            channel_details=channel_details,
            recommendations=list(dict.fromkeys(recommendations)),  # Remove duplicados
            average_channel_kwh=round(mean_kwh, 2),
        )

    def diagnose_and_persist(
        self, system_sid: str, target_date: str
    ) -> DiagnosticReport:
        """
        Carrega os canais do repositório para a data, processa o diagnóstico e salva as anomalias detectadas.
        """
        channels = self.repository.get_channel_telemetry_for_date(target_date)
        report = self.evaluate_channels(channels)

        if report.anomalies:
            anom_dicts = [
                {
                    "inverter_uid": a.inverter_uid,
                    "channel": a.channel,
                    "anomaly_type": a.anomaly_type,
                    "severity": a.severity,
                    "message": a.message,
                    "detected_value": a.detected_value,
                    "reference_value": a.reference_value,
                }
                for a in report.anomalies
            ]
            self.repository.save_anomalies(system_sid, anom_dicts)

        return report
