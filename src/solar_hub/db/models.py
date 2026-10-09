from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    Column,
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
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    create_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status_light: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    money_saved: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    system: Mapped["SystemRecord"] = relationship("SystemRecord", back_populates="daily_aggregates")


class ApiCallAuditRecord(Base):
    """Auditoria estrita de consumo de cota da API da APsystems (Livro-Razão de Requisições)."""
    __tablename__ = "api_call_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(10), default="GET")
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
