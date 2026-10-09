from datetime import datetime
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from solar_hub.client.client import APsystemsClient
from solar_hub.core.config import Settings
from solar_hub.db.database import get_session_factory, init_db
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService
from solar_hub.services.discovery import HardwareDiscoveryService

app = typer.Typer(
    name="solar",
    help="SolarHub: Plataforma soberana de monitoramento solar APsystems com gestão estrita de cota.",
    add_completion=False,
)
console = Console()


def get_services():
    """Inicializa as dependências com base no .env."""
    settings = Settings()
    init_db(settings.database_url)
    session_factory = get_session_factory(settings.database_url)
    session = session_factory()
    repo = SolarRepository(session)
    client = APsystemsClient(
        app_id=settings.apsystems_app_id,
        app_secret=settings.apsystems_app_secret,
        base_url=settings.apsystems_base_url,
    )
    budget = BudgetKeeperService(
        repository=repo,
        monthly_limit=settings.monthly_budget_limit,
        reserve_calls_daily=settings.reserve_daily_calls,
        window_start=settings.solar_window_start,
        window_end=settings.solar_window_end,
    )
    discovery = HardwareDiscoveryService(client=client, repository=repo)
    return settings, session, repo, client, budget, discovery


@app.command()
def discover():
    """
    Executa o mapeamento dinâmico de hardware (ECUs, inversores e canais DC)
    e persiste a topologia no banco de dados local.
    """
    settings, session, repo, client, budget, discovery = get_services()
    try:
        console.print("[bold yellow]Iniciando auto-descoberta de hardware na APsystems...[/bold yellow]")
        res = discovery.discover_and_sync(settings.apsystems_system_id)

        table = Table(title="Topologia Descoberta da Usina", show_header=True)
        table.add_column("Propriedade", style="cyan")
        table.add_column("Valor", style="green")

        table.add_row("System ID (sid)", res.sid)
        table.add_row("Capacidade Instalada", f"{res.capacity_kwp:.2f} kWp")
        table.add_row("Data de Comissionamento", res.create_date)
        table.add_row("Status de Saúde (Light)", "Normal (Verde)" if res.status_light == 1 else f"Alerta ({res.status_light})")
        table.add_row("Gateways ECU", f"{res.ecus_count} ({', '.join(res.ecu_ids)})")
        table.add_row("Total de Microinversores", str(res.inverters_count))
        table.add_row("Painéis Estimados (Canais DC)", str(res.estimated_total_panels))

        models_str = ", ".join(f"{count}x {model}" for model, count in res.inverters_by_model.items())
        table.add_row("Modelos Encontrados", models_str)

        console.print(table)
        console.print("[bold green]Topologia salva com sucesso no banco de dados local![/bold green]")
    finally:
        session.close()


@app.command()
def status():
    """
    Exibe o painel de status da usina e o consumo de cota da API.
    """
    settings, session, repo, client, budget, discovery = get_services()
    try:
        # Consulta do banco local
        system = repo.get_system(settings.apsystems_system_id)
        budget_status = budget.get_status()

        # Resumo consolidado da API
        summary = client.get_system_summary(settings.apsystems_system_id)
        repo.record_api_call(
            endpoint=f"/user/api/v2/systems/summary/{settings.apsystems_system_id}",
            method="GET",
            notes="Status Check",
        )

        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_column()

        # Cartão de Energia
        energy_panel = Panel(
            f"[bold cyan]Hoje:[/bold cyan] {summary.today_kwh:.2f} kWh\n"
            f"[bold cyan]Mês:[/bold cyan] {summary.month_kwh:.2f} kWh\n"
            f"[bold cyan]Ano:[/bold cyan] {summary.year_kwh:.2f} kWh\n"
            f"[bold green]Lifetime:[/bold green] {summary.lifetime_kwh:,.2f} kWh\n"
            f"[bold yellow]Economia Estimada:[/bold yellow] {settings.currency_symbol} {summary.lifetime_kwh * settings.tariff_kwh_rate:,.2f}",
            title="Telemetria de Geração",
            border_style="green",
        )

        # Cartão do Budget Keeper
        budget_panel = Panel(
            f"[bold]Consumo no Mês:[/bold] {budget_status.calls_this_month} / {budget_status.monthly_limit} reqs\n"
            f"[bold]Restante no Mês:[/bold] [green]{budget_status.remaining_month}[/green] reqs\n"
            f"[bold]Chamadas Hoje:[/bold] {budget_status.calls_today} reqs (Meta diária segura: ~{budget_status.daily_budget_target})\n"
            f"[bold]Janela Solar:[/bold] {'Ativa (Dia)' if budget_status.is_solar_window else 'Inativa (Noite)'}\n"
            f"[bold]Diagnóstico:[/bold] {budget_status.reason}",
            title="Budget Keeper (Cota OpenAPI)",
            border_style="blue",
        )

        grid.add_row(energy_panel, budget_panel)
        console.print(Panel(grid, title=f"Painel SolarHub - Usina {settings.apsystems_system_id}", border_style="cyan"))
    finally:
        session.close()


@app.command()
def inverters():
    """
    Lista todos os microinversores cadastrados localmente no banco de dados (zero requisições de cota).
    """
    settings, session, repo, client, budget, discovery = get_services()
    try:
        invs = repo.get_inverters()
        if not invs:
            console.print("[yellow]Nenhum inversor encontrado localmente. Execute 'solar discover' primeiro.[/yellow]")
            return

        table = Table(title=f"Microinversores Cadastrados ({len(invs)} unidades)", show_header=True)
        table.add_column("UID (Serial)", style="cyan")
        table.add_column("ECU Vinculada", style="blue")
        table.add_column("Modelo", style="green")
        table.add_column("Canais DC", justify="right")
        table.add_column("Alias", style="magenta")

        total_channels = 0
        for inv in invs:
            table.add_row(
                inv.uid,
                inv.ecu_eid,
                inv.model,
                str(inv.channels_count),
                inv.alias or "-",
            )
            total_channels += inv.channels_count

        console.print(table)
        console.print(f"[bold green]Total: {len(invs)} inversores, {total_channels} canais DC / painéis monitorados.[/bold green]")
    finally:
        session.close()


@app.command()
def budget():
    """
    Exibe o relatório detalhado de consumo da cota de 1.000 requisições/mês.
    """
    settings, session, repo, client, budget, discovery = get_services()
    try:
        st = budget.get_status()
        console.print(Panel(
            f"[bold]Chamadas no Mês:[/bold] {st.calls_this_month} / {st.monthly_limit}\n"
            f"[bold]Saldo Restante no Mês:[/bold] {st.remaining_month}\n"
            f"[bold]Chamadas Realizadas Hoje:[/bold] {st.calls_today}\n"
            f"[bold]Orçamento Diário Recomendado:[/bold] {st.daily_budget_target} reqs/dia\n"
            f"[bold]Janela Solar Ativa:[/bold] {'Sim' if st.is_solar_window else 'Não'}\n"
            f"[bold]Status Operacional:[/bold] {st.reason}",
            title="Relatório do Guardião de Cota (Budget Keeper)",
            border_style="yellow"
        ))
    finally:
        session.close()


if __name__ == "__main__":
    app()
