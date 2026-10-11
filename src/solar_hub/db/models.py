from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SystemRecord(Base):
    """Registro da Usina Solar Fotovoltaica (Entidade Raiz)."""
    __tablename__ = "systems"

    sid: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    capacity_kwp: Mapped[float] = mapped_column(Float, default=0.0)
    system_type: Mapped[int] = mapped_column(Integer, default=1)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    create_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status_light: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relacionamentos
    ecus: Mapped[List["EcuRecord"]] = relationship("EcuRecord", back_populates="system", cascade="all, delete-orphan")
    daily_aggregates: Mapped[List["DailyAggregateRecord"]] = relationship(
        "DailyAggregateRecord", back_populates="system", cascade="all, delete-orphan"
    )


class EcuRecord(Base):
    """Gateway de Comunicação (ECU-R, ECU-C, ECU-B)."""
    __tablename__ = "ecus"

    eid: Mapped[str] = mapped_column(String(64), primary_key=True)
    system_sid: Mapped[str] = mapped_column(String(64), ForeignKey("systems.sid"), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relacionamentos
    system: Mapped["SystemRecord"] = relationship("SystemRecord", back_populates="ecus")
    inverters: Mapped[List["InverterRecord"]] = relationship(
        "InverterRecord", back_populates="ecu", cascade="all, delete-orphan"
    )


class InverterRecord(Base):
    """Microinversor individual (YC1000, DS3, QT2, QS1, etc.)."""
    __tablename__ = "inverters"

    uid: Mapped[str] = mapped_column(String(64), primary_key=True)
    ecu_eid: Mapped[str] = mapped_column(String(64), ForeignKey("ecus.eid"), nullable=False)
    model: Mapped[str] = mapped_column(String(64), default="Unknown")
    channels_count: Mapped[int] = mapped_column(Integer, default=4)
    alias: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relacionamentos
    ecu: Mapped["EcuRecord"] = relationship("EcuRecord", back_populates="inverters")


class DailyAggregateRecord(Base):
    """Resumo diário consolidado para navegação ultrarrápida (estilo ez1-monitor / analytics)."""
    __tablename__ = "daily_aggregates"
    __table_args__ = (UniqueConstraint("system_sid", "date", name="uq_system_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_sid: Mapped[str] = mapped_column(String(64), ForeignKey("systems.sid"), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # Formato: YYYY-MM-DD
    energy_kwh: Mapped[float] = mapped_column(Float, default=0.0)
    peak_power_w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    system: Mapped["SystemRecord"] = relationship("SystemRecord", back_populates="daily_aggregates")


class ApiCallAuditRecord(Base):
    """Auditoria estrita de consumo de cota da API da APsystems (Livro-Razão de Requisições)."""
    __tablename__ = "api_call_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(10), default="GET")
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class InverterChannelTelemetryRecord(Base):
    """Telemetria granular de produção e grandezas elétricas por canal DC."""
    __tablename__ = "inverter_channel_telemetry"
    __table_args__ = (
        UniqueConstraint("inverter_uid", "channel", "date", name="uq_inverter_channel_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inverter_uid: Mapped[str] = mapped_column(String(64), ForeignKey("inverters.uid"), nullable=False, index=True)
    channel: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..4
    date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    energy_today_kwh: Mapped[float] = mapped_column(Float, default=0.0)
    power_w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    voltage_v: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_a: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    frequency_hz: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AnomalyRecord(Base):
    """Registro de anomalias e alertas de diagnóstico elétrico detectados."""
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_sid: Mapped[str] = mapped_column(String(64), ForeignKey("systems.sid"), nullable=False, index=True)
    inverter_uid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    channel: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    anomaly_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="WARNING")  # INFO, WARNING, CRITICAL
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reference_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AlertLogRecord(Base):
    """Histórico e auditoria de alertas e notificações disparadas."""
    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_sid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    alert_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="WARNING")  # INFO, WARNING, CRITICAL
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)  # webhook, telegram, etc.
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class AppSettingRecord(Base):
    """Configurações persistentes da aplicação modificáveis via interface Web."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


