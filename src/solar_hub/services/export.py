import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, Optional

from solar_hub.db.repository import SolarRepository


class ExportService:
    """
    Serviço central de exportação de dados analíticos do SolarHub.
    Extrai telemetrias salvas no SQLite para CSV ou JSON sem efetuar
    qualquer requisição à OpenAPI da APsystems (Zero Quota Impact).
    """

    def __init__(self, repository: SolarRepository, system_sid: str):
        self.repository = repository
        self.system_sid = system_sid

    def export_generation(
        self,
        export_format: str = "csv",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_file: Optional[Path] = None,
    ) -> str:
        """
        Exporta a série histórica de geração diária (agregados).
        Retorna a string formatada em CSV ou JSON e opcionalmente salva em disco.
        """
        records = self.repository.get_daily_aggregates_range(
            system_sid=self.system_sid,
            start_date=start_date,
            end_date=end_date,
        )

        fmt = export_format.lower().strip()
        if fmt == "json":
            data = [
                {
                    "system_sid": r.system_sid,
                    "date": r.date,
                    "energy_kwh": r.energy_kwh,
                    "peak_power_w": r.peak_power_w,
                    "is_finalized": r.is_finalized,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in records
            ]
            content = json.dumps(data, indent=2, ensure_ascii=False)
        elif fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(["system_sid", "date", "energy_kwh", "peak_power_w", "is_finalized", "updated_at"])
            for r in records:
                writer.writerow([
                    r.system_sid,
                    r.date,
                    f"{r.energy_kwh:.3f}",
                    f"{r.peak_power_w:.1f}" if r.peak_power_w is not None else "",
                    "true" if r.is_finalized else "false",
                    r.updated_at.isoformat() if r.updated_at else "",
                ])
            content = output.getvalue()
        else:
            raise ValueError(f"Formato não suportado: '{export_format}'. Utilize 'csv' ou 'json'.")

        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(content, encoding="utf-8")

        return content

    def export_channels(
        self,
        export_format: str = "csv",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        inverter_uid: Optional[str] = None,
        output_file: Optional[Path] = None,
    ) -> str:
        """
        Exporta os registros de telemetria fina por canal DC e microinversor.
        Retorna a string formatada em CSV ou JSON e opcionalmente salva em disco.
        """
        records = self.repository.get_channel_telemetry_range(
            start_date=start_date,
            end_date=end_date,
            inverter_uid=inverter_uid,
        )

        fmt = export_format.lower().strip()
        if fmt == "json":
            data = [
                {
                    "inverter_uid": r.inverter_uid,
                    "channel": r.channel,
                    "date": r.date,
                    "energy_today_kwh": r.energy_today_kwh,
                    "power_w": r.power_w,
                    "voltage_v": r.voltage_v,
                    "current_a": r.current_a,
                    "temperature_c": r.temperature_c,
                    "frequency_hz": r.frequency_hz,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in records
            ]
            content = json.dumps(data, indent=2, ensure_ascii=False)
        elif fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow([
                "inverter_uid",
                "channel",
                "date",
                "energy_today_kwh",
                "power_w",
                "voltage_v",
                "current_a",
                "temperature_c",
                "frequency_hz",
                "updated_at",
            ])
            for r in records:
                writer.writerow([
                    r.inverter_uid,
                    r.channel,
                    r.date,
                    f"{r.energy_today_kwh:.3f}",
                    f"{r.power_w:.1f}" if r.power_w is not None else "",
                    f"{r.voltage_v:.1f}" if r.voltage_v is not None else "",
                    f"{r.current_a:.2f}" if r.current_a is not None else "",
                    f"{r.temperature_c:.1f}" if r.temperature_c is not None else "",
                    f"{r.frequency_hz:.1f}" if r.frequency_hz is not None else "",
                    r.updated_at.isoformat() if r.updated_at else "",
                ])
            content = output.getvalue()
        else:
            raise ValueError(f"Formato não suportado: '{export_format}'. Utilize 'csv' ou 'json'.")

        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(content, encoding="utf-8")

        return content

    def export_summary(self) -> Dict[str, Any]:
        """
        Retorna estatísticas gerais das tabelas exportáveis no banco local.
        """
        aggregates = self.repository.get_daily_aggregates_range(self.system_sid)
        channels = self.repository.get_channel_telemetry_range()
        anomalies = self.repository.get_latest_anomalies(self.system_sid, limit=1000)
        alerts = self.repository.get_recent_alerts(self.system_sid, limit=1000)

        total_kwh = sum(r.energy_kwh for r in aggregates)
        dates = [r.date for r in aggregates]

        return {
            "system_sid": self.system_sid,
            "total_days_recorded": len(aggregates),
            "total_energy_kwh": round(total_kwh, 2),
            "date_range": {
                "start": dates[0] if dates else None,
                "end": dates[-1] if dates else None,
            },
            "channel_records_count": len(channels),
            "anomalies_count": len(anomalies),
            "alerts_dispatched_count": len(alerts),
        }
