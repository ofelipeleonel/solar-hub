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
from solar_hub.services.collector import CollectorService
from solar_hub.services.discovery import HardwareDiscoveryService
from solar_hub.services.notification import NotificationService

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
    notifier = NotificationService(
        repository=repo,
        system_sid=settings.apsystems_system_id,
        webhook_url=settings.alert_webhook_url,
        telegram_bot_token=settings.alert_telegram_bot_token,
        telegram_chat_id=settings.alert_telegram_chat_id,
        cooldown_hours=settings.alert_cooldown_hours,
        min_health_score=settings.alert_min_health_score,
        quota_warning_pct=settings.alert_quota_warning_pct,
        midday_check_enabled=settings.alert_midday_check,
        allow_private_webhooks=settings.allow_private_webhooks,
    )
    mqtt_service = None
    if settings.mqtt_enabled:
        from solar_hub.services.mqtt import HomeAssistantMqttService

        mqtt_service = HomeAssistantMqttService(
            repository=repo,
            budget=budget,
            system_sid=settings.apsystems_system_id,
            broker=settings.mqtt_broker,
            port=settings.mqtt_port,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
            discovery_prefix=settings.mqtt_discovery_prefix,
            topic_prefix=settings.mqtt_topic_prefix,
        )
    discovery = HardwareDiscoveryService(client=client, repository=repo)
    collector = CollectorService(
        client=client,
        repository=repo,
        budget=budget,
        sid=settings.apsystems_system_id,
        nightly_time=settings.nightly_sync_time,
        notifier=notifier,
        mqtt_service=mqtt_service,
    )
    return settings, session, repo, client, budget, discovery, collector




@app.command()
def discover():
    """
    Executa o mapeamento dinâmico de hardware (ECUs, inversores e canais DC)
    e persiste a topologia no banco de dados local.
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
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
    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        # Consulta do banco local
        system = repo.get_system(settings.apsystems_system_id)
        system_title = system.name if system and system.name else f"Usina {settings.apsystems_system_id}"
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
            f"[bold green]Lifetime:[/bold green] {summary.lifetime_kwh:,.2f} kWh",
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
        console.print(Panel(grid, title=f"Painel SolarHub - {system_title}", border_style="cyan"))

    finally:
        session.close()


@app.command()
def inverters():
    """
    Lista todos os microinversores cadastrados localmente no banco de dados (zero requisições de cota).
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
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
    settings, session, repo, client, budget, discovery, collector = get_services()
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


@app.command()
def sync(
    force: bool = typer.Option(
        False, "--force", "-f", help="Força a sincronização ignorando restrições de horário solar."
    )
):
    """
    Executa uma sincronização manual pontual e grava no banco SQLite local.
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        console.print("[cyan]Sincronizando telemetria de geração...[/cyan]")
        res = collector.sync_current(force=force)
        console.print(Panel(
            f"[bold green]{res.message}[/bold green]\n"
            f"Data: {res.target_date}\n"
            f"Geração Hoje: [bold]{res.energy_today_kwh:.2f} kWh[/bold]\n"
            f"Geração Lifetime: {res.lifetime_kwh:,.2f} kWh",
            title="Resultado da Sincronização",
            border_style="green",
        ))
    except Exception as e:
        console.print(f"[bold red]Falha na sincronização:[/bold red] {e}")
    finally:
        session.close()


@app.command()
def daemon(
    interval: int = typer.Option(
        30, "--interval", "-i", help="Intervalo em minutos entre coletas diurnas (padrão: 30)."
    )
):
    """
    Inicia o coletor em modo Daemon (background contínuo) com inteligência solar.
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
    console.print(Panel(
        f"[bold green]SolarHub Coletor Daemon Ativo[/bold green]\n"
        f"Usina ID: [cyan]{settings.apsystems_system_id}[/cyan]\n"
        f"Janela Solar: {settings.solar_window_start} às {settings.solar_window_end}\n"
        f"Intervalo Diurno: {interval} minutos\n"
        f"Fechamento Noturno: {settings.nightly_sync_time}\n"
        f"Pressione [bold red]Ctrl+C[/bold red] para encerrar a qualquer momento.",
        title="Daemon de Ingestão Resiliente",
        border_style="green",
    ))
    try:
        collector.run_daemon(interval_minutes=interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Daemon interrompido pelo usuário.[/yellow]")
    finally:
        session.close()


@app.command()
def history(
    limit: int = typer.Option(15, "--limit", "-l", help="Quantidade de dias históricos a exibir.")
):
    """
    Exibe o histórico de geração diária do banco SQLite local (Zero cota consumida).
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        records = repo.get_daily_aggregates(settings.apsystems_system_id, limit=limit)
        if not records:
            console.print("[yellow]Nenhum registro histórico consolidado encontrado ainda. Execute 'solar sync' primeiro.[/yellow]")
            return

        table = Table(title=f"Histórico Local de Geração (Últimos {len(records)} dias)", show_header=True)
        table.add_column("Data", style="cyan")
        table.add_column("Energia Gerada", justify="right", style="green")
        table.add_column("Status", justify="center")

        for r in records:
            status_badge = "[bold green]Definitivo[/bold green]" if r.is_finalized else "[italic cyan]Parcial[/italic cyan]"
            table.add_row(
                r.date,
                f"{r.energy_kwh:.2f} kWh",
                status_badge,
            )

        console.print(table)
    finally:
        session.close()


@app.command()
def channels(
    sync: bool = typer.Option(False, "--sync", "-s", help="Sincroniza com a API antes de listar (consome 1 chamada por ECU)."),
    target_date: Optional[str] = typer.Option(None, "--date", help="Data no formato YYYY-MM-DD (padrão: hoje)."),
):
    """
    Lista a geração individual de cada canal DC / painel solar no banco local.
    """
    from datetime import date

    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        today_str = target_date or date.today().isoformat()
        if sync:
            console.print("[cyan]Sincronizando dados dos canais DC via lote da ECU...[/cyan]")
            count = collector.sync_channels(target_date=today_str)
            console.print(f"[bold green]{count} canais sincronizados com sucesso![/bold green]")

        records = repo.get_channel_telemetry_for_date(today_str)
        if not records:
            console.print(
                f"[yellow]Nenhum registro de canal encontrado para {today_str}. "
                "Execute 'solar channels --sync' para sincronizar com a usina.[/yellow]"
            )
            return

        table = Table(title=f"Telemetria por Canal DC ({today_str})", show_header=True)
        table.add_column("Inversor (UID)", style="cyan")
        table.add_column("Canal", justify="center", style="blue")
        table.add_column("Energia Hoje", justify="right", style="green")
        table.add_column("Potência DC", justify="right")
        table.add_column("Tensão DC", justify="right")
        table.add_column("Corrente DC", justify="right")

        for r in records:
            p_str = f"{r.power_w:.1f} W" if r.power_w is not None else "-"
            v_str = f"{r.voltage_v:.1f} V" if r.voltage_v is not None else "-"
            i_str = f"{r.current_a:.2f} A" if r.current_a is not None else "-"
            table.add_row(
                r.inverter_uid,
                str(r.channel),
                f"{r.energy_today_kwh:.2f} kWh",
                p_str,
                v_str,
                i_str,
            )

        console.print(table)
    finally:
        session.close()


@app.command()
def telemetry(
    uid: str = typer.Argument(..., help="Número de série (UID) do microinversor a consultar."),
):
    """
    Consulta a telemetria elétrica instantânea fina de um microinversor (V, A, W, °C, Hz).
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        console.print(f"[cyan]Consultando telemetria elétrica detalhada do inversor {uid}...[/cyan]")
        data = collector.fetch_inverter_telemetry(uid)
        snap = data.get_latest_snapshot()

        table = Table(title=f"Diagnóstico Elétrico - Inversor {uid} (Horário: {snap['time']})", show_header=True)
        table.add_column("Canal DC", justify="center", style="cyan")
        table.add_column("Potência (W)", justify="right", style="green")
        table.add_column("Tensão DC (V)", justify="right", style="yellow")
        table.add_column("Corrente DC (A)", justify="right", style="magenta")

        for ch in [1, 2, 3, 4]:
            p = snap["dc_power_w"].get(ch)
            v = snap["dc_voltage_v"].get(ch)
            i = snap["dc_current_a"].get(ch)
            if any(x is not None for x in [p, v, i]):
                table.add_row(
                    str(ch),
                    f"{p:.1f} W" if p is not None else "-",
                    f"{v:.1f} V" if v is not None else "-",
                    f"{i:.2f} A" if i is not None else "-",
                )

        console.print(table)

        summary_panel = Panel(
            f"[bold]Potência AC Total:[/bold] {snap['ac_power_w'] or '-'} W\n"
            f"[bold]Tensão AC da Rede:[/bold] {snap['ac_voltage_v'] or '-'} V\n"
            f"[bold]Frequência da Rede:[/bold] {snap['frequency_hz'] or '-'} Hz\n"
            f"[bold]Temperatura Interna:[/bold] {snap['temperature_c'] or '-'} °C",
            title="Grandezas de Saída AC & Saúde Térmica",
            border_style="blue",
        )
        console.print(summary_panel)
    except Exception as e:
        console.print(f"[bold red]Erro ao consultar telemetria:[/bold red] {e}")
    finally:
        session.close()


@app.command()
def diagnose(
    sync: bool = typer.Option(False, "--sync", "-s", help="Sincroniza os canais com a API antes do diagnóstico."),
    target_date: Optional[str] = typer.Option(None, "--date", help="Data no formato YYYY-MM-DD (padrão: hoje)."),
    notify: bool = typer.Option(False, "--notify", "-n", help="Dispara notificações caso anomalias sejam identificadas."),
):
    """
    Executa o motor de diagnóstico e detecção de anomalias por painel solar e microinversor.
    """
    from datetime import date

    from solar_hub.services.diagnostic import DiagnosticService

    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        today_str = target_date or date.today().isoformat()
        if sync:
            console.print("[cyan]Sincronizando telemetria de canais antes do diagnóstico...[/cyan]")
            collector.sync_channels(target_date=today_str)

        diag_service = DiagnosticService(repository=repo)
        report = diag_service.diagnose_and_persist(settings.apsystems_system_id, today_str)

        badge_color = "green" if report.health_score >= 90 else "yellow" if report.health_score >= 60 else "red"
        status_panel = Panel(
            f"[bold {badge_color}]Índice de Saúde Operacional: {report.health_score}% ({report.status})[/bold {badge_color}]\n"
            f"• Canais Monitorados: [bold]{report.channels_evaluated}[/bold]\n"
            f"• Produção Média por Canal: [bold]{report.average_channel_kwh:.2f} kWh[/bold]\n"
            f"• Anomalias Identificadas: [bold]{len(report.anomalies)}[/bold]",
            title="Relatório de Diagnóstico de Desempenho",
            border_style=badge_color,
        )
        console.print(status_panel)

        if report.anomalies:
            table = Table(title="Anomalias e Alertas Detectados", show_header=True)
            table.add_column("Severidade", justify="center")
            table.add_column("Tipo", style="cyan")
            table.add_column("Inversor", style="blue")
            table.add_column("Canal", justify="center")
            table.add_column("Diagnóstico", style="white")

            for anom in report.anomalies:
                sev_badge = (
                    "[bold red]CRÍTICO[/bold red]"
                    if anom.severity == "CRITICAL"
                    else "[bold yellow]ALERTA[/bold yellow]"
                )
                table.add_row(
                    sev_badge,
                    anom.anomaly_type,
                    anom.inverter_uid or "-",
                    str(anom.channel or "-"),
                    anom.message,
                )
            console.print(table)

        if report.recommendations:
            rec_text = "\n".join(f"• {rec}" for rec in report.recommendations)
            console.print(Panel(rec_text, title="Recomendações de Ação e Manutenção", border_style="cyan"))

        # Despacho opcional de notificações
        if notify and collector.notifier:
            if collector.notifier.has_active_channel:
                console.print("[cyan]Avaliando e disparando notificações para os canais configurados...[/cyan]")
                dispatched = collector.notifier.check_diagnostics(report)
                console.print(f"[bold green]{len(dispatched)} alertas avaliados/despachados com sucesso.[/bold green]")
            else:
                console.print("[yellow]Aviso: --notify solicitado, porém nenhum canal configurado no .env.[/yellow]")

    finally:
        session.close()


@app.command(name="test-alert")
def test_alert():
    """
    Envia uma notificação de teste para verificar a conectividade dos canais configurados (Webhook / Telegram).
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
    notifier = collector.notifier
    try:
        if not notifier or not notifier.has_active_channel:
            console.print(
                "[yellow]Nenhum canal de notificação configurado no arquivo .env!\n"
                "Defina ALERT_WEBHOOK_URL ou ALERT_TELEGRAM_BOT_TOKEN + ALERT_TELEGRAM_CHAT_ID.[/yellow]"
            )
            return

        console.print("[cyan]Disparando notificação de teste imediata (bypass de cooldown)...[/cyan]")
        result = notifier.send_test_alert()

        channels_info = []
        for ch, success in result["channels"].items():
            status_str = "[bold green]OK (Entregue)[/bold green]" if success else "[bold red]FALHA[/bold red]"
            channels_info.append(f"• Canal {ch.upper()}: {status_str}")

        channels_text = "\n".join(channels_info) if channels_info else "Nenhum canal configurado respondeu."
        panel_color = "green" if result["success"] else "red"

        console.print(Panel(
            f"[bold]Resultado do Teste de Alerta:[/bold]\n{channels_text}",
            title="Diagnóstico de Notificações SolarHub",
            border_style=panel_color,
        ))
    finally:
        session.close()


@app.command(name="alerts")
def alerts(
    limit: int = typer.Option(15, "--limit", "-l", help="Quantidade de alertas recentes a exibir."),
):
    """
    Exibe o histórico de alertas e notificações disparadas pelo SolarHub (com status e cooldown).
    """
    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        records = repo.get_recent_alerts(settings.apsystems_system_id, limit=limit)
        if not records:
            console.print("[yellow]Nenhum alerta registrado até o momento no banco local.[/yellow]")
            return

        table = Table(title=f"Histórico de Alertas Recentes ({len(records)} eventos)", show_header=True)
        table.add_column("Horário (UTC)", style="cyan")
        table.add_column("Severidade", justify="center")
        table.add_column("Canal", style="magenta")
        table.add_column("Alerta", style="white")
        table.add_column("Status", justify="center")

        for r in records:
            sev_badge = (
                "[bold red]CRÍTICO[/bold red]"
                if r.severity == "CRITICAL"
                else "[bold yellow]ALERTA[/bold yellow]"
                if r.severity == "WARNING"
                else "[bold blue]INFO[/bold blue]"
            )
            status_badge = "[bold green]Enviado[/bold green]" if r.success else f"[bold red]Erro ({r.error_detail or '-'})[/bold red]"
            table.add_row(
                r.dispatched_at.strftime("%Y-%m-%d %H:%M:%S") if r.dispatched_at else "-",
                sev_badge,
                r.channel,
                f"[bold]{r.title}[/bold]: {r.message[:80]}...",
                status_badge,
            )

        console.print(table)
    finally:
        session.close()


@app.command(name="export")
def export(
    target: str = typer.Argument("generation", help="Alvo de exportação: 'generation' (agregados diários) ou 'channels' (telemetria multicanal)."),
    format: str = typer.Option("csv", "--format", "-f", help="Formato de exportação: 'csv' ou 'json'."),
    start_date: Optional[str] = typer.Option(None, "--start", "-s", help="Data inicial no formato YYYY-MM-DD."),
    end_date: Optional[str] = typer.Option(None, "--end", "-e", help="Data final no formato YYYY-MM-DD."),
    inverter_uid: Optional[str] = typer.Option(None, "--uid", "-u", help="Filtrar por UID do microinversor (apenas para channels)."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Caminho do arquivo de saída (ex: ./export.csv). Se omitido, imprime no terminal."),
):
    """
    Exporta dados analíticos do banco SQLite em CSV ou JSON com ZERO consumo de cota da APsystems.
    """
    from pathlib import Path

    from solar_hub.services.export import ExportService

    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        service = ExportService(repository=repo, system_sid=settings.apsystems_system_id)
        out_path = Path(output) if output else None

        if target.lower() in ("generation", "daily", "geracao"):
            content = service.export_generation(
                export_format=format,
                start_date=start_date,
                end_date=end_date,
                output_file=out_path,
            )
            count = len(repo.get_daily_aggregates_range(settings.apsystems_system_id, start_date, end_date))
            target_desc = f"{count} registros diários de geração"
        elif target.lower() in ("channels", "canais", "panels"):
            content = service.export_channels(
                export_format=format,
                start_date=start_date,
                end_date=end_date,
                inverter_uid=inverter_uid,
                output_file=out_path,
            )
            count = len(repo.get_channel_telemetry_range(start_date, end_date, inverter_uid))
            target_desc = f"{count} registros de telemetria por canal"
        else:
            console.print(f"[bold red]Alvo inválido:[/bold red] '{target}'. Escolha entre 'generation' ou 'channels'.")
            raise typer.Exit(code=1)

        if out_path:
            console.print(
                f"[bold green]Sucesso![/bold green] {target_desc} exportados para [cyan]{out_path.resolve()}[/cyan] "
                f"(Formato: {format.upper()}, Cota API: 0 chamadas)."
            )
        else:
            print(content)
    finally:
        session.close()


@app.command(name="mqtt-publish")
def mqtt_publish():
    """
    Publica entidades de auto-descoberta e telemetria atual no broker MQTT (Home Assistant Discovery).
    """
    from solar_hub.services.mqtt import HomeAssistantMqttService

    settings, session, repo, client, budget, discovery, collector = get_services()
    try:
        mqtt_service = collector.mqtt_service
        if not mqtt_service:
            mqtt_service = HomeAssistantMqttService(
                repository=repo,
                budget=budget,
                system_sid=settings.apsystems_system_id,
                broker=settings.mqtt_broker,
                port=settings.mqtt_port,
                username=settings.mqtt_username,
                password=settings.mqtt_password,
                discovery_prefix=settings.mqtt_discovery_prefix,
                topic_prefix=settings.mqtt_topic_prefix,
            )

        console.print(f"[cyan]Conectando ao broker MQTT em {settings.mqtt_broker}:{settings.mqtt_port}...[/cyan]")
        res = mqtt_service.publish_all()
        if res.get("success"):
            console.print(Panel(
                f"[bold green]Publicação MQTT concluída com sucesso![/bold green]\n"
                f"• Sensores descobertos (Home Assistant): [bold]{res['sensors_discovered']}[/bold]\n"
                f"• Tópico de estado: [cyan]{res['state_topic']}[/cyan]\n"
                f"• Broker: [yellow]{settings.mqtt_broker}:{settings.mqtt_port}[/yellow]",
                title="Integração Home Assistant MQTT",
                border_style="green",
            ))
        else:
            console.print(f"[bold red]Falha na publicação MQTT:[/bold red] {res.get('error')}")
    finally:
        session.close()


@app.command()
def web(

    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Endereço de escuta do servidor web."),
    port: int = typer.Option(8000, "--port", "-p", help="Porta TCP do servidor web."),
    with_daemon: bool = typer.Option(
        False, "--with-daemon", "-d", help="Inicia automaticamente o coletor em background junto com a interface web."
    ),
):
    """
    Inicia o Dashboard Web Local embutido (100% offline e self-hosted).
    """
    import os

    import uvicorn

    if with_daemon:
        os.environ["ENABLE_DAEMON"] = "true"

    daemon_status = "[bold green]Ativo (Background)[/bold green]" if with_daemon else "[dim]Desativado (Modo somente leitura)[/dim]"

    console.print(Panel(
        f"[bold green]SolarHub Web Dashboard Ativo![/bold green]\n"
        f"Acesse no navegador: [bold cyan]http://{host}:{port}[/bold cyan]\n"
        f"• Persistência em SQLite (Zero requisições de cota para abrir telas)\n"
        f"• Coletor em Segundo Plano: {daemon_status}\n"
        f"• Chart.js local e offline (Zero rastreamento externo)\n"
        f"• Hall of Fame e UX inspirados no projeto open source [yellow]ez1-monitor[/yellow]\n"
        f"Pressione [bold red]Ctrl+C[/bold red] para encerrar.",
        title="Dashboard Web Local",
        border_style="green",
    ))
    uvicorn.run("solar_hub.interfaces.web.app:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()


