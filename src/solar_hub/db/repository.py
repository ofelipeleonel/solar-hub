from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from solar_hub.db.models import (
    AlertLogRecord,
    AnomalyRecord,
    ApiCallAuditRecord,
    AppSettingRecord,
    DailyAggregateRecord,
    EcuRecord,
    InverterChannelTelemetryRecord,
    InverterRecord,
    SystemRecord,
)


class SolarRepository:
    """Camada de persistência e repositório de dados do SolarHub."""

    def __init__(self, session: Session):
        self.session = session

    def upsert_system(
        self,
        sid: str,
        capacity_kwp: float,
        system_type: int = 1,
        timezone: str = "UTC",
        create_date: Optional[str] = None,
        status_light: int = 1,
        name: Optional[str] = None,
    ) -> SystemRecord:
        """Insere ou atualiza os dados cadastrais da usina."""
        stmt = select(SystemRecord).where(SystemRecord.sid == sid)
        system = self.session.execute(stmt).scalar_one_or_none()

        if system is None:
            system = SystemRecord(
                sid=sid,
                name=name or f"Usina {sid[-6:]}",
                capacity_kwp=capacity_kwp,
                system_type=system_type,
                timezone=timezone,
                create_date=create_date,
                status_light=status_light,
            )
            self.session.add(system)
        else:
            system.capacity_kwp = capacity_kwp
            system.system_type = system_type
            system.timezone = timezone
            system.status_light = status_light
            if create_date:
                system.create_date = create_date
            if name:
                system.name = name

        self.session.commit()
        return system

    def upsert_ecu(
        self,
        eid: str,
        system_sid: str,
        timezone: Optional[str] = None,
        model: Optional[str] = None,
    ) -> EcuRecord:
        """Insere ou atualiza um gateway ECU."""
        stmt = select(EcuRecord).where(EcuRecord.eid == eid)
        ecu = self.session.execute(stmt).scalar_one_or_none()

        if ecu is None:
            ecu = EcuRecord(eid=eid, system_sid=system_sid, timezone=timezone, model=model)
            self.session.add(ecu)
        else:
            ecu.system_sid = system_sid
            if timezone:
                ecu.timezone = timezone
            if model:
                ecu.model = model

        self.session.commit()
        return ecu

    def upsert_inverter(
        self,
        uid: str,
        ecu_eid: str,
        model: str,
        channels_count: int = 4,
        alias: Optional[str] = None,
    ) -> InverterRecord:
        """Insere ou atualiza um microinversor."""
        stmt = select(InverterRecord).where(InverterRecord.uid == uid)
        inverter = self.session.execute(stmt).scalar_one_or_none()

        if inverter is None:
            inverter = InverterRecord(
                uid=uid,
                ecu_eid=ecu_eid,
                model=model,
                channels_count=channels_count,
                alias=alias,
            )
            self.session.add(inverter)
        else:
            inverter.ecu_eid = ecu_eid
            inverter.model = model
            inverter.channels_count = channels_count
            if alias:
                inverter.alias = alias

        self.session.commit()
        return inverter

    def get_system(self, sid: str) -> Optional[SystemRecord]:
        stmt = select(SystemRecord).where(SystemRecord.sid == sid)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_inverters(self, ecu_eid: Optional[str] = None) -> List[InverterRecord]:
        stmt = select(InverterRecord)
        if ecu_eid:
            stmt = stmt.where(InverterRecord.ecu_eid == ecu_eid)
        return list(self.session.execute(stmt).scalars().all())

    def record_api_call(
        self,
        endpoint: str,
        method: str = "GET",
        status_code: int = 200,
        success: bool = True,
        notes: Optional[str] = None,
    ) -> ApiCallAuditRecord:
        """Registra no livro-razão local uma chamada de API executada."""
        record = ApiCallAuditRecord(
            timestamp=datetime.now(timezone.utc),
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            success=success,
            notes=notes,
        )
        self.session.add(record)
        self.session.commit()
        return record

    def count_api_calls_this_month(self) -> int:
        """Conta quantas requisições foram efetuadas no mês corrente."""
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        stmt = select(func.count(ApiCallAuditRecord.id)).where(
            ApiCallAuditRecord.timestamp >= start_of_month
        )
        return self.session.execute(stmt).scalar() or 0

    def count_api_calls_today(self) -> int:
        """Conta quantas requisições foram efetuadas hoje."""
        now = datetime.now(timezone.utc)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        stmt = select(func.count(ApiCallAuditRecord.id)).where(
            ApiCallAuditRecord.timestamp >= start_of_day
        )
        return self.session.execute(stmt).scalar() or 0

    def upsert_daily_aggregate(
        self,
        system_sid: str,
        target_date: str,
        energy_kwh: float,
        is_finalized: bool = False,
    ) -> DailyAggregateRecord:
        stmt = select(DailyAggregateRecord).where(
            DailyAggregateRecord.system_sid == system_sid,
            DailyAggregateRecord.date == target_date,
        )
        record = self.session.execute(stmt).scalar_one_or_none()

        if record is None:
            record = DailyAggregateRecord(
                system_sid=system_sid,
                date=target_date,
                energy_kwh=energy_kwh,
                is_finalized=is_finalized,
            )
            self.session.add(record)
        else:
            record.energy_kwh = energy_kwh
            record.is_finalized = is_finalized

        self.session.commit()
        return record

    def get_daily_aggregates(
        self, system_sid: str, limit: int = 30
    ) -> List[DailyAggregateRecord]:
        """Retorna o histórico de agregados diários ordenados do mais recente para o mais antigo."""
        stmt = (
            select(DailyAggregateRecord)
            .where(DailyAggregateRecord.system_sid == system_sid)
            .order_by(DailyAggregateRecord.date.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_daily_aggregates_range(
        self,
        system_sid: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[DailyAggregateRecord]:
        """Retorna os agregados diários em ordem cronológica com filtro opcional por período."""
        stmt = select(DailyAggregateRecord).where(DailyAggregateRecord.system_sid == system_sid)
        if start_date:
            stmt = stmt.where(DailyAggregateRecord.date >= start_date)
        if end_date:
            stmt = stmt.where(DailyAggregateRecord.date <= end_date)
        stmt = stmt.order_by(DailyAggregateRecord.date.asc())
        return list(self.session.execute(stmt).scalars().all())


    def upsert_channel_telemetry(
        self,
        inverter_uid: str,
        channel: int,
        date_str: str,
        energy_today_kwh: float,
        power_w: Optional[float] = None,
        voltage_v: Optional[float] = None,
        current_a: Optional[float] = None,
        temperature_c: Optional[float] = None,
        frequency_hz: Optional[float] = None,
    ) -> InverterChannelTelemetryRecord:
        """Insere ou atualiza os dados elétricos e de produção de um canal DC."""
        stmt = select(InverterChannelTelemetryRecord).where(
            InverterChannelTelemetryRecord.inverter_uid == inverter_uid,
            InverterChannelTelemetryRecord.channel == channel,
            InverterChannelTelemetryRecord.date == date_str,
        )
        rec = self.session.execute(stmt).scalar_one_or_none()
        if rec is None:
            rec = InverterChannelTelemetryRecord(
                inverter_uid=inverter_uid,
                channel=channel,
                date=date_str,
                energy_today_kwh=energy_today_kwh,
                power_w=power_w,
                voltage_v=voltage_v,
                current_a=current_a,
                temperature_c=temperature_c,
                frequency_hz=frequency_hz,
            )
            self.session.add(rec)
        else:
            rec.energy_today_kwh = energy_today_kwh
            if power_w is not None:
                rec.power_w = power_w
            if voltage_v is not None:
                rec.voltage_v = voltage_v
            if current_a is not None:
                rec.current_a = current_a
            if temperature_c is not None:
                rec.temperature_c = temperature_c
            if frequency_hz is not None:
                rec.frequency_hz = frequency_hz

        self.session.commit()
        return rec

    def get_channel_telemetry_for_date(
        self, target_date: str
    ) -> List[InverterChannelTelemetryRecord]:
        """Retorna todas as leituras de canais para uma data específica."""
        stmt = (
            select(InverterChannelTelemetryRecord)
            .where(InverterChannelTelemetryRecord.date == target_date)
            .order_by(
                InverterChannelTelemetryRecord.inverter_uid,
                InverterChannelTelemetryRecord.channel,
            )
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_inverter_channel_telemetry(
        self, inverter_uid: str, target_date: Optional[str] = None
    ) -> List[InverterChannelTelemetryRecord]:
        """Retorna as leituras dos canais de um inversor específico."""
        stmt = select(InverterChannelTelemetryRecord).where(
            InverterChannelTelemetryRecord.inverter_uid == inverter_uid
        )
        if target_date:
            stmt = stmt.where(InverterChannelTelemetryRecord.date == target_date)
        stmt = stmt.order_by(InverterChannelTelemetryRecord.channel)
        return list(self.session.execute(stmt).scalars().all())

    def get_channel_telemetry_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        inverter_uid: Optional[str] = None,
    ) -> List[InverterChannelTelemetryRecord]:
        """Retorna telemetria de canais filtrada por período e/ou microinversor específico."""
        stmt = select(InverterChannelTelemetryRecord)
        if start_date:
            stmt = stmt.where(InverterChannelTelemetryRecord.date >= start_date)
        if end_date:
            stmt = stmt.where(InverterChannelTelemetryRecord.date <= end_date)
        if inverter_uid:
            stmt = stmt.where(InverterChannelTelemetryRecord.inverter_uid == inverter_uid)
        stmt = stmt.order_by(
            InverterChannelTelemetryRecord.date.asc(),
            InverterChannelTelemetryRecord.inverter_uid.asc(),
            InverterChannelTelemetryRecord.channel.asc(),
        )
        return list(self.session.execute(stmt).scalars().all())


    def save_anomalies(
        self, system_sid: str, anomalies: List[dict]
    ) -> List[AnomalyRecord]:
        """Persiste uma lista de anomalias detectadas pelo serviço de diagnóstico."""
        created = []
        for anom in anomalies:
            record = AnomalyRecord(
                system_sid=system_sid,
                inverter_uid=anom.get("inverter_uid"),
                channel=anom.get("channel"),
                anomaly_type=anom.get("anomaly_type", "UNKNOWN"),
                severity=anom.get("severity", "WARNING"),
                message=anom.get("message", ""),
                detected_value=anom.get("detected_value"),
                reference_value=anom.get("reference_value"),
            )
            self.session.add(record)
            created.append(record)
        self.session.commit()
        return created

    def get_latest_anomalies(
        self, system_sid: str, limit: int = 20
    ) -> List[AnomalyRecord]:
        """Retorna os alertas e anomalias mais recentes do sistema."""
        stmt = (
            select(AnomalyRecord)
            .where(AnomalyRecord.system_sid == system_sid)
            .order_by(AnomalyRecord.timestamp.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def record_alert_dispatch(
        self,
        system_sid: str,
        alert_key: str,
        severity: str,
        title: str,
        message: str,
        channel: str,
        success: bool = True,
        error_detail: Optional[str] = None,
    ) -> AlertLogRecord:
        """Registra a auditoria de um alerta enviado (ou tentativa) para controle de cooldown."""
        record = AlertLogRecord(
            system_sid=system_sid,
            alert_key=alert_key,
            severity=severity,
            title=title,
            message=message,
            channel=channel,
            success=success,
            error_detail=error_detail,
        )
        self.session.add(record)
        self.session.commit()
        return record

    def get_last_alert(
        self, system_sid: str, alert_key: str
    ) -> Optional[AlertLogRecord]:
        """Recupera o último registro de envio com sucesso de um alerta específico."""
        stmt = (
            select(AlertLogRecord)
            .where(
                AlertLogRecord.system_sid == system_sid,
                AlertLogRecord.alert_key == alert_key,
                AlertLogRecord.success == True,  # noqa: E712
            )
            .order_by(AlertLogRecord.dispatched_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def is_in_cooldown(
        self, system_sid: str, alert_key: str, cooldown_hours: int = 4
    ) -> bool:
        """Verifica se um alerta similar já foi despachado recentemente dentro da janela de cooldown."""
        last = self.get_last_alert(system_sid, alert_key)
        if not last:
            return False

        now = datetime.now(timezone.utc)
        last_time = last.dispatched_at
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)

        elapsed_hours = (now - last_time).total_seconds() / 3600.0
        return elapsed_hours < cooldown_hours

    def get_recent_alerts(
        self, system_sid: str, limit: int = 20
    ) -> List[AlertLogRecord]:
        """Retorna o histórico de alertas e notificações disparadas."""
        stmt = (
            select(AlertLogRecord)
            .where(AlertLogRecord.system_sid == system_sid)
            .order_by(AlertLogRecord.dispatched_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Recupera uma configuração persistente salva no banco SQLite."""
        stmt = select(AppSettingRecord).where(AppSettingRecord.key == key)
        record = self.session.execute(stmt).scalar_one_or_none()
        return record.value if record else default

    def set_setting(self, key: str, value: str) -> AppSettingRecord:
        """Salva ou atualiza uma configuração persistente no banco SQLite."""
        stmt = select(AppSettingRecord).where(AppSettingRecord.key == key)
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            record = AppSettingRecord(key=key, value=value)
            self.session.add(record)
        else:
            record.value = value
        self.session.commit()
        return record

    def get_all_settings(self) -> Dict[str, str]:
        """Retorna todas as configurações persistentes salvas como dicionário."""
        stmt = select(AppSettingRecord)
        records = self.session.execute(stmt).scalars().all()
        return {r.key: r.value for r in records}



