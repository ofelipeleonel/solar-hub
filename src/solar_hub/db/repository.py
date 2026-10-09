from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from solar_hub.db.models import (
    ApiCallAuditRecord,
    DailyAggregateRecord,
    EcuRecord,
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
        timezone: str = "America/Sao_Paulo",
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
            timestamp=datetime.utcnow(),
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
        now = datetime.utcnow()
        start_of_month = datetime(now.year, now.month, 1)
        stmt = select(func.count(ApiCallAuditRecord.id)).where(
            ApiCallAuditRecord.timestamp >= start_of_month
        )
        return self.session.execute(stmt).scalar() or 0

    def count_api_calls_today(self) -> int:
        """Conta quantas requisições foram efetuadas hoje."""
        now = datetime.utcnow()
        start_of_day = datetime(now.year, now.month, now.day)
        stmt = select(func.count(ApiCallAuditRecord.id)).where(
            ApiCallAuditRecord.timestamp >= start_of_day
        )
        return self.session.execute(stmt).scalar() or 0

    def upsert_daily_aggregate(
        self,
        system_sid: str,
        target_date: str,
        energy_kwh: float,
        money_saved: Optional[float] = None,
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
                money_saved=money_saved,
                is_finalized=is_finalized,
            )
            self.session.add(record)
        else:
            record.energy_kwh = energy_kwh
            if money_saved is not None:
                record.money_saved = money_saved
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

