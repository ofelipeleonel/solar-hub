from datetime import date
from typing import List

from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService
from solar_hub.services.diagnostic import DiagnosticService


class PrometheusMetricsService:
    """
    Exportador de métricas operacionais no formato padrão do Prometheus (Exposition 0.0.4).
    Lê diretamente do banco local SQLite e do Budget Keeper sem consumir chamadas da API.
    """

    def __init__(
        self,
        repository: SolarRepository,
        budget: BudgetKeeperService,
        system_sid: str,
    ):
        self.repository = repository
        self.budget = budget
        self.system_sid = system_sid

    def generate_metrics(self) -> str:
        """
        Gera o documento de métricas Prometheus formatado em texto puro.
        """
        lines: List[str] = []
        today_str = date.today().isoformat()
        sid = self.system_sid

        # 1. Informações cadastrais e capacidade da usina
        system = self.repository.get_system(sid)
        capacity_kwp = system.capacity_kwp if system else 0.0

        lines.append("# HELP solar_capacity_kwp Total installed photovoltaic capacity in kWp")
        lines.append("# TYPE solar_capacity_kwp gauge")
        lines.append(f'solar_capacity_kwp{{system_id="{sid}"}} {capacity_kwp:.2f}')

        # 2. Geração diária e agregados
        today_agg = self.repository.get_daily_aggregates(sid, limit=1)
        today_kwh = today_agg[0].energy_kwh if today_agg and today_agg[0].date == today_str else 0.0

        lines.append("# HELP solar_today_kwh Solar energy produced today in kWh")
        lines.append("# TYPE solar_today_kwh gauge")
        lines.append(f'solar_today_kwh{{system_id="{sid}"}} {today_kwh:.3f}')

        # 3. Métricas de governança da API (Budget Keeper)
        budget_status = self.budget.get_status()

        lines.append("# HELP solar_budget_calls_this_month OpenAPI calls consumed in current month")
        lines.append("# TYPE solar_budget_calls_this_month gauge")
        lines.append(f'solar_budget_calls_this_month{{system_id="{sid}"}} {budget_status.calls_this_month}')

        lines.append("# HELP solar_budget_monthly_limit Contractual monthly OpenAPI quota limit")
        lines.append("# TYPE solar_budget_monthly_limit gauge")
        lines.append(f'solar_budget_monthly_limit{{system_id="{sid}"}} {budget_status.monthly_limit}')

        lines.append("# HELP solar_budget_remaining OpenAPI calls remaining for current month")
        lines.append("# TYPE solar_budget_remaining gauge")
        lines.append(f'solar_budget_remaining{{system_id="{sid}"}} {budget_status.remaining_month}')

        lines.append("# HELP solar_budget_calls_today Total OpenAPI calls made today")
        lines.append("# TYPE solar_budget_calls_today gauge")
        lines.append(f'solar_budget_calls_today{{system_id="{sid}"}} {budget_status.calls_today}')

        lines.append("# HELP solar_budget_solar_window_active Indicates if current time is within active solar window (1=true, 0=false)")
        lines.append("# TYPE solar_budget_solar_window_active gauge")
        lines.append(f'solar_budget_solar_window_active{{system_id="{sid}"}} {1 if budget_status.is_solar_window else 0}')

        # 4. Saúde e diagnóstico da usina
        channels = self.repository.get_channel_telemetry_for_date(today_str)
        if channels:
            diag_service = DiagnosticService(self.repository)
            report = diag_service.evaluate_channels(channels)
            health_score = report.health_score
            anomalies_count = len(report.anomalies)
        else:
            health_score = 100
            anomalies_count = 0

        lines.append("# HELP solar_health_score Overall plant operational health score (0-100%)")
        lines.append("# TYPE solar_health_score gauge")
        lines.append(f'solar_health_score{{system_id="{sid}"}} {health_score}')

        lines.append("# HELP solar_active_anomalies_count Count of anomalies detected in today readings")
        lines.append("# TYPE solar_active_anomalies_count gauge")
        lines.append(f'solar_active_anomalies_count{{system_id="{sid}"}} {anomalies_count}')

        # 5. Telemetria fina por canal e microinversor
        if channels:
            # Geração por canal (kWh)
            lines.append("# HELP solar_channel_energy_today_kwh Energy generated today by individual DC channel in kWh")
            lines.append("# TYPE solar_channel_energy_today_kwh gauge")
            for ch in channels:
                labels = f'system_id="{sid}",inverter_uid="{ch.inverter_uid}",channel="{ch.channel}"'
                lines.append(f"solar_channel_energy_today_kwh{{{labels}}} {ch.energy_today_kwh:.3f}")

            # Potência DC instantânea (W)
            dc_powers = [ch for ch in channels if ch.power_w is not None]
            if dc_powers:
                lines.append("# HELP solar_channel_power_watts Instantaneous DC power per channel in Watts")
                lines.append("# TYPE solar_channel_power_watts gauge")
                for ch in dc_powers:
                    labels = f'system_id="{sid}",inverter_uid="{ch.inverter_uid}",channel="{ch.channel}"'
                    lines.append(f"solar_channel_power_watts{{{labels}}} {ch.power_w:.1f}")

            # Tensão DC (V)
            dc_volts = [ch for ch in channels if ch.voltage_v is not None]
            if dc_volts:
                lines.append("# HELP solar_channel_voltage_volts Instantaneous DC voltage per channel in Volts")
                lines.append("# TYPE solar_channel_voltage_volts gauge")
                for ch in dc_volts:
                    labels = f'system_id="{sid}",inverter_uid="{ch.inverter_uid}",channel="{ch.channel}"'
                    lines.append(f"solar_channel_voltage_volts{{{labels}}} {ch.voltage_v:.1f}")

            # Corrente DC (A)
            dc_amps = [ch for ch in channels if ch.current_a is not None]
            if dc_amps:
                lines.append("# HELP solar_channel_current_amperes Instantaneous DC current per channel in Amperes")
                lines.append("# TYPE solar_channel_current_amperes gauge")
                for ch in dc_amps:
                    labels = f'system_id="{sid}",inverter_uid="{ch.inverter_uid}",channel="{ch.channel}"'
                    lines.append(f"solar_channel_current_amperes{{{labels}}} {ch.current_a:.2f}")

            # Temperatura interna do microinversor (°C)
            seen_invs = set()
            temps = []
            for ch in channels:
                if ch.inverter_uid not in seen_invs and ch.temperature_c is not None:
                    seen_invs.add(ch.inverter_uid)
                    temps.append(ch)

            if temps:
                lines.append("# HELP solar_inverter_temperature_celsius Inverter internal temperature in Celsius")
                lines.append("# TYPE solar_inverter_temperature_celsius gauge")
                for ch in temps:
                    labels = f'system_id="{sid}",inverter_uid="{ch.inverter_uid}"'
                    lines.append(f"solar_inverter_temperature_celsius{{{labels}}} {ch.temperature_c:.1f}")

        lines.append("")
        return "\n".join(lines)
