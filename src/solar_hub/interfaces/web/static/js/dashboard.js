let historyChart = null;

async function loadDashboard() {
  try {
    // 1. Carrega dados de status geral
    const statusRes = await fetch("/api/status");
    const status = await statusRes.json();

    document.getElementById("val-today-kwh").innerText = `${status.today_kwh.toFixed(2)} kWh`;
    document.getElementById("val-today-money").innerText = `${status.currency} ${status.today_money.toFixed(2)}`;
    document.getElementById("val-capacity").innerText = `${status.capacity_kwp.toFixed(2)} kWp`;
    document.getElementById("val-budget-remaining").innerText = `${status.budget.remaining_month} / ${status.budget.monthly_limit}`;
    document.getElementById("sub-budget").innerText = `Hoje: ${status.budget.calls_today} reqs | Janela Solar: ${status.budget.is_solar_window ? "Ativa" : "Noite"}`;
    document.getElementById("system-name").innerText = `${status.system_name} (ID: ${status.sid})`;

    // Status light
    const statusEl = document.getElementById("status-badge");
    if (status.status_light === 1) {
      statusEl.innerHTML = `<span class="status-dot"></span> Operação Normal`;
    } else {
      statusEl.innerHTML = `<span class="status-dot" style="background:#ef4444;box-shadow:0 0 8px #ef4444;"></span> Alerta (${status.status_light})`;
      statusEl.style.color = "#ef4444";
      statusEl.style.borderColor = "rgba(239,68,68,0.3)";
      statusEl.style.backgroundColor = "rgba(239,68,68,0.15)";
    }

    // 2. Carrega Hall of Fame (Melhor Dia de Todos os Tempos)
    const fameRes = await fetch("/api/hall-of-fame");
    const fame = await fameRes.json();
    if (fame.best_day) {
      document.getElementById("val-fame-kwh").innerText = `${fame.best_day.energy_kwh.toFixed(2)} kWh`;
      document.getElementById("sub-fame-date").innerText = `Recorde em ${fame.best_day.date} (${status.currency} ${fame.best_day.money_saved.toFixed(2)})`;
    }

    // 3. Carrega Inversores Cadastrados
    const invRes = await fetch("/api/inverters");
    const inverters = await invRes.json();
    const invGrid = document.getElementById("inverters-grid");
    invGrid.innerHTML = "";
    inverters.forEach(inv => {
      const item = document.createElement("div");
      item.className = "inverter-item";
      item.innerHTML = `
        <div class="inverter-title">${inv.alias}</div>
        <div class="inverter-detail">Modelo: <strong>${inv.model}</strong> (${inv.channels_count} canais DC)</div>
        <div class="inverter-detail" style="font-size:11px; margin-top:4px;">Serial: ${inv.uid}</div>
      `;
      invGrid.appendChild(item);
    });

    // 4. Carrega Histórico para Gráfico
    const histRes = await fetch("/api/history?limit=30");
    const historyData = await histRes.json();
    renderChart(historyData, status.currency);

  } catch (err) {
    console.error("Erro ao carregar telemetria do dashboard:", err);
  }
}

function renderChart(historyData, currency) {
  const ctx = document.getElementById("historyChart").getContext("2d");
  const labels = historyData.map(d => d.date);
  const values = historyData.map(d => d.energy_kwh);

  if (historyChart) {
    historyChart.destroy();
  }

  historyChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Energia Gerada (kWh)",
          data: values,
          backgroundColor: "rgba(245, 158, 11, 0.8)",
          borderColor: "#f59e0b",
          borderWidth: 1,
          borderRadius: 6,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return `${context.parsed.y.toFixed(2)} kWh`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#94a3b8" }
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(255, 255, 255, 0.08)" },
          ticks: {
            color: "#94a3b8",
            callback: function(val) { return val + " kWh"; }
          }
        }
      }
    }
  });
}

// Inicializa ao carregar e atualiza a cada 60s (offline no SQLite, 0 chamadas de cota)
document.addEventListener("DOMContentLoaded", () => {
  loadDashboard();
  setInterval(loadDashboard, 60000);
});
