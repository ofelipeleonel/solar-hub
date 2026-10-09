from pathlib import Path
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from solar_hub.client.client import APsystemsClient
from solar_hub.core.config import Settings
from solar_hub.db.database import get_session_factory, init_db
from solar_hub.db.models import DailyAggregateRecord, InverterRecord, SystemRecord
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService

app = FastAPI(
    title="SolarHub Web Dashboard",
    description="Interface Web local, autônoma e leve para monitoramento solar APsystems. Inspirada pelo projeto open-source ez1-monitor.",
    version="0.1.0",
)

# Habilita CORS para testes locais
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


def get_repo_and_settings():
    settings = Settings()
    init_db(settings.database_url)
    session_factory = get_session_factory(settings.database_url)
    session = session_factory()
    repo = SolarRepository(session)
    budget = BudgetKeeperService(
        repository=repo,
        monthly_limit=settings.monthly_budget_limit,
        reserve_calls_daily=settings.reserve_daily_calls,
        window_start=settings.solar_window_start,
        window_end=settings.solar_window_end,
    )
    return settings, session, repo, budget


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    """Retorna o status geral da usina, telemetria de hoje e governança de cota."""
    settings, session, repo, budget = get_repo_and_settings()
    try:
        system = repo.get_system(settings.apsystems_system_id)
        budget_status = budget.get_status()
        
        # Pega o agregado de hoje no banco local
        today_agg = repo.get_daily_aggregates(settings.apsystems_system_id, limit=1)
        today_kwh = today_agg[0].energy_kwh if today_agg else 0.0
        money_today = today_agg[0].money_saved if today_agg else 0.0
        
        # Pega a soma acumulada de todos os registros
        total_energy = session.execute(
            select(func.sum(DailyAggregateRecord.energy_kwh)).where(DailyAggregateRecord.system_sid == settings.apsystems_system_id)
        ).scalar() or 0.0

        return {
            "sid": settings.apsystems_system_id,
            "system_name": system.name if system else f"Usina {settings.apsystems_system_id[-6:]}",
            "capacity_kwp": system.capacity_kwp if system else 0.0,
            "status_light": system.status_light if system else 1,
            "today_kwh": today_kwh,
            "today_money": money_today,
            "currency": settings.currency_symbol,
            "tariff_rate": settings.tariff_kwh_rate,
            "budget": {
                "calls_this_month": budget_status.calls_this_month,
                "monthly_limit": budget_status.monthly_limit,
                "remaining_month": budget_status.remaining_month,
                "calls_today": budget_status.calls_today,
                "daily_budget_target": budget_status.daily_budget_target,
                "is_solar_window": budget_status.is_solar_window,
                "reason": budget_status.reason,
            }
        }
    finally:
        session.close()


@app.get("/api/history")
def get_history(limit: int = 30) -> List[Dict[str, Any]]:
    """Retorna a série histórica de dias para renderização gráfica no Chart.js."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        records = repo.get_daily_aggregates(settings.apsystems_system_id, limit=limit)
        # Ordena de forma cronológica (mais antigo primeiro) para o gráfico
        ordered = sorted(records, key=lambda r: r.date)
        return [
            {
                "date": r.date,
                "energy_kwh": r.energy_kwh,
                "money_saved": r.money_saved or 0.0,
                "is_finalized": r.is_finalized,
            }
            for r in ordered
        ]
    finally:
        session.close()


@app.get("/api/inverters")
def get_inverters() -> List[Dict[str, Any]]:
    """Retorna a lista de microinversores cadastrados e sua topologia."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        invs = repo.get_inverters()
        return [
            {
                "uid": inv.uid,
                "ecu_eid": inv.ecu_eid,
                "model": inv.model,
                "channels_count": inv.channels_count,
                "alias": inv.alias or f"Microinversor {inv.uid[-4:]}",
            }
            for inv in invs
        ]
    finally:
        session.close()


@app.get("/api/hall-of-fame")
def get_hall_of_fame() -> Dict[str, Any]:
    """Retorna os recordes históricos (inspirado na funcionalidade Hall of Fame do ez1-monitor)."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        # Busca o melhor dia histórico registrado no banco
        stmt = (
            select(DailyAggregateRecord)
            .where(DailyAggregateRecord.system_sid == settings.apsystems_system_id)
            .order_by(DailyAggregateRecord.energy_kwh.desc())
            .limit(1)
        )
        best_day = session.execute(stmt).scalar_one_or_none()

        return {
            "best_day": {
                "date": best_day.date if best_day else "-",
                "energy_kwh": best_day.energy_kwh if best_day else 0.0,
                "money_saved": best_day.money_saved if best_day else 0.0,
            } if best_day else None
        }
    finally:
        session.close()


# Monta os arquivos estáticos
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(STATIC_DIR / "index.html")
