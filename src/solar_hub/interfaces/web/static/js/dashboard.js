let historyChart = null;

// ==============================================================================
// Sanitização de Segurança Anti-XSS (DOM-based / Stored XSS Prevention)
// ==============================================================================

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ==============================================================================
// Dashboard Core & Telemetria
// ==============================================================================

async function loadDashboard() {
  try {
    // 1. Carrega dados de status geral e governança de cota
    const statusRes = await fetch("/api/status");
    const status = await statusRes.json();

    // Geração de Hoje (evita mostrar o último dia histórico quando não há coleta para hoje)
    const todayEl = document.getElementById("val-today-kwh");
    const subTodayEl = document.getElementById("sub-today");

    if (status.has_today_data) {
      todayEl.innerText = `${status.today_kwh.toFixed(2)} kWh`;
      if (subTodayEl) subTodayEl.innerText = "Produção solar acumulada no dia";
    } else {
      todayEl.innerText = "-- kWh";
      if (subTodayEl) {
        if (status.last_recorded_date) {
          subTodayEl.innerText = `Sem coleta hoje. Último: ${status.last_recorded_date} (${status.last_recorded_kwh.toFixed(2)} kWh)`;
        } else {
          subTodayEl.innerText = "Aguardando primeira coleta de hoje";
        }
      }
    }

    document.getElementById("val-inverters").innerText = `${status.total_inverters} unidades`;
    document.getElementById("val-capacity").innerText = `${status.capacity_kwp.toFixed(2)} kWp`;

    // Banner de Alerta e Governança de Cota
    const bannerEl = document.getElementById("quota-warning-banner");
    const budgetValEl = document.getElementById("val-budget-remaining");
    const subBudgetEl = document.getElementById("sub-budget");

    if (status.budget && (status.budget.quota_exhausted || status.budget.remaining_month === 0)) {
      if (bannerEl) bannerEl.style.display = "flex";
      budgetValEl.innerText = "0 / 1000";
      budgetValEl.style.color = "var(--accent-red)";
      subBudgetEl.innerText = "Cota OpenAPI Esgotada na Nuvem (Código 2005) 🔒";
    } else {
      if (bannerEl) bannerEl.style.display = "none";
      budgetValEl.innerText = `${status.budget.remaining_month} / ${status.budget.monthly_limit}`;
      budgetValEl.style.color = "";
      subBudgetEl.innerText = `Hoje: ${status.budget.calls_today} reqs | Janela: ${status.budget.is_solar_window ? "Ativa ☀️" : "Noite 🌙"}`;
    }

    document.getElementById("system-name").innerText = `${status.system_name} (ID: ${status.sid})`;

    // Status light
    const statusEl = document.getElementById("status-badge");
    if (status.status_light === 1) {
      statusEl.innerHTML = `<span class="status-dot"></span> Operação Normal`;
      statusEl.style.color = "var(--accent-green)";
      statusEl.style.borderColor = "rgba(16, 185, 129, 0.3)";
      statusEl.style.backgroundColor = "rgba(16, 185, 129, 0.15)";
    } else {
      statusEl.innerHTML = `<span class="status-dot" style="background:#ef4444;box-shadow:0 0 8px #ef4444;"></span> Alerta (${status.status_light})`;
      statusEl.style.color = "var(--accent-red)";
      statusEl.style.borderColor = "rgba(239,68,68,0.3)";
      statusEl.style.backgroundColor = "rgba(239,68,68,0.15)";
    }

    // 2. Carrega Hall of Fame (Melhor Dia Histórico - inspirado em ez1-monitor)
    const fameRes = await fetch("/api/hall-of-fame");
    const fame = await fameRes.json();
    if (fame.best_day) {
      document.getElementById("val-fame-kwh").innerText = `${fame.best_day.energy_kwh.toFixed(2)} kWh`;
      document.getElementById("sub-fame-date").innerText = `Recorde registrado em ${fame.best_day.date}`;
    }

    // 3. Carrega Inversores Cadastrados (sanitizados contra XSS)
    const invRes = await fetch("/api/inverters");
    const inverters = await invRes.json();
    const invGrid = document.getElementById("inverters-grid");
    invGrid.innerHTML = "";
    inverters.forEach(inv => {
      const item = document.createElement("div");
      item.className = "inverter-item";
      item.innerHTML = `
        <div class="inverter-title">${escapeHtml(inv.alias)}</div>
        <div class="inverter-detail">Modelo: <strong>${escapeHtml(inv.model)}</strong> (${Number(inv.channels_count)} canais DC)</div>
        <div class="inverter-detail" style="font-size:11px; margin-top:4px;">Serial: ${escapeHtml(inv.uid)}</div>
      `;
      invGrid.appendChild(item);
    });

    // 4. Carrega Histórico para Gráfico
    const histRes = await fetch("/api/history?limit=30");
    const historyData = await histRes.json();
    renderChart(historyData);

    // 5. Carrega Diagnóstico de Saúde e Telemetria de Canais
    const diagRes = await fetch("/api/diagnostics");
    const diag = await diagRes.json();
    const diagBadge = document.getElementById("diagnostic-badge");
    if (diag.health_score >= 90) {
      diagBadge.innerText = `Saúde: ${diag.health_score}% (${diag.status})`;
      diagBadge.style.background = "rgba(34,197,94,0.15)";
      diagBadge.style.color = "#22c55e";
    } else if (diag.health_score >= 60) {
      diagBadge.innerText = `Atenção: ${diag.health_score}% (${diag.status})`;
      diagBadge.style.background = "rgba(245,158,11,0.15)";
      diagBadge.style.color = "#f59e0b";
    } else {
      diagBadge.innerText = `Crítico: ${diag.health_score}% (${diag.status})`;
      diagBadge.style.background = "rgba(239,68,68,0.15)";
      diagBadge.style.color = "#ef4444";
    }

    const recEl = document.getElementById("diagnostic-recommendations");
    if (diag.recommendations && diag.recommendations.length > 0) {
      recEl.innerHTML = diag.recommendations.map(r => `• ${escapeHtml(r)}`).join("<br>");
    } else {
      recEl.innerText = "Nenhuma anomalia detectada. Painéis operando em perfeito equilíbrio.";
    }

    const channelsGrid = document.getElementById("channels-grid");
    channelsGrid.innerHTML = "";
    if (diag.channel_details && diag.channel_details.length > 0) {
      diag.channel_details.forEach(ch => {
        const card = document.createElement("div");
        card.className = "channel-card";
        const tagClass = ch.status === "DEAD" ? "channel-tag-dead" : (ch.status === "UNDERPERFORMING" ? "channel-tag-warning" : "channel-tag-normal");
        const statusLabel = ch.status === "DEAD" ? "Sem Geração" : (ch.status === "UNDERPERFORMING" ? `${ch.deviation_pct}%` : "Normal");

        card.innerHTML = `
          <div class="channel-card-header">
            <span class="channel-title">Inv ${escapeHtml(ch.inverter_uid.slice(-4))} • C${Number(ch.channel)}</span>
            <span class="channel-tag ${tagClass}">${escapeHtml(statusLabel)}</span>
          </div>
          <div class="channel-energy-val">${ch.energy_today_kwh.toFixed(2)} kWh</div>
          <div class="channel-metrics">
            <span>${ch.power_w ? ch.power_w.toFixed(0) + ' W' : '-'}</span>
            <span>${ch.voltage_v ? ch.voltage_v.toFixed(1) + ' V' : '-'}</span>
            <span>${ch.current_a ? ch.current_a.toFixed(1) + ' A' : '-'}</span>
          </div>
        `;
        channelsGrid.appendChild(card);
      });
    } else {
      channelsGrid.innerHTML = `<div style="grid-column: 1/-1; color: var(--text-muted); font-size: 13px;">Clique em "Sincronizar" acima para coletar a telemetria detalhada de canais DC.</div>`;
    }

    // 6. Carrega Alertas Disparados
    await loadAlerts();

  } catch (err) {
    console.error("Erro ao carregar telemetria do dashboard:", err);
  }
}

function renderChart(historyData) {
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
        legend: { display: false },
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

// ==============================================================================
// Alertas & Histórico de Disparos
// ==============================================================================

async function loadAlerts() {
  try {
    const res = await fetch("/api/alerts?limit=10");
    const alerts = await res.json();
    const listEl = document.getElementById("alerts-list");

    if (!alerts || alerts.length === 0) {
      listEl.innerHTML = `<div style="color: var(--text-muted); font-size: 13px; padding: 12px 0;">Nenhum alerta recente disparado. Sistema em operação perfeitamente estável.</div>`;
      return;
    }

    listEl.innerHTML = "";
    alerts.forEach(item => {
      const el = document.createElement("div");
      el.className = "alert-item";

      const badgeClass = item.severity === "CRITICAL" ? "badge-critical" : (item.severity === "WARNING" ? "badge-warning" : "badge-info");
      const timeStr = item.dispatched_at ? new Date(item.dispatched_at).toLocaleString("pt-BR") : "-";

      el.innerHTML = `
        <div class="alert-left">
          <span class="alert-badge ${badgeClass}">${escapeHtml(item.severity)}</span>
          <div>
            <div class="alert-title">${escapeHtml(item.title)}</div>
            <div class="alert-msg">${escapeHtml(item.message)}</div>
          </div>
        </div>
        <div class="alert-right">
          <span class="alert-channel">${escapeHtml(item.channel.toUpperCase())}</span>
          <span class="alert-time">${timeStr}</span>
        </div>
      `;
      listEl.appendChild(el);
    });
  } catch (err) {
    console.error("Erro ao carregar alertas:", err);
  }
}

// ==============================================================================
// Modais & Gerenciamento de Janelas
// ==============================================================================

function openModal(id) {
  const dlg = document.getElementById(id);
  if (dlg) {
    dlg.showModal();
    if (id === "modal-settings") {
      loadSettings();
    } else if (id === "modal-export") {
      loadExportSummary();
    }
  }
}

function closeModal(id) {
  const dlg = document.getElementById(id);
  if (dlg) {
    dlg.close();
  }
}

// ==============================================================================
// Configurações & Integrações (Telegram, Webhook, MQTT)
// ==============================================================================

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();

    const tokenInput = document.getElementById("cfg-telegram-token");
    tokenInput.value = "";
    tokenInput.placeholder = data.has_telegram ? "Token configurado (deixe vazio para manter)" : "Ex: 123456789:ABCdef...";

    document.getElementById("cfg-telegram-chat").value = data.telegram_chat_id || "";
    document.getElementById("cfg-webhook-url").value = data.webhook_url || "";
    document.getElementById("cfg-cooldown").value = data.alert_cooldown_hours || 4;
    document.getElementById("cfg-min-health").value = data.alert_min_health_score || 80;

    document.getElementById("cfg-mqtt-enabled").checked = Boolean(data.mqtt_enabled);
    document.getElementById("cfg-mqtt-broker").value = data.mqtt_broker || "localhost";
    document.getElementById("cfg-mqtt-port").value = data.mqtt_port || 1883;
    document.getElementById("cfg-mqtt-user").value = data.mqtt_username || "";
    document.getElementById("cfg-mqtt-pass").value = "";
  } catch (err) {
    console.error("Erro ao carregar configurações:", err);
    showToast("Erro ao carregar configurações salvas.", "error");
  }
}

async function saveSettings() {
  const saveBtn = document.getElementById("btn-save-settings");
  saveBtn.disabled = true;
  saveBtn.innerText = "Salvando...";

  try {
    const payload = {};

    const token = document.getElementById("cfg-telegram-token").value.trim();
    if (token) {
      payload.telegram_bot_token = token;
    }

    payload.telegram_chat_id = document.getElementById("cfg-telegram-chat").value.trim();
    payload.webhook_url = document.getElementById("cfg-webhook-url").value.trim();
    payload.alert_cooldown_hours = parseInt(document.getElementById("cfg-cooldown").value, 10) || 4;
    payload.alert_min_health_score = parseInt(document.getElementById("cfg-min-health").value, 10) || 80;

    payload.mqtt_enabled = document.getElementById("cfg-mqtt-enabled").checked;
    payload.mqtt_broker = document.getElementById("cfg-mqtt-broker").value.trim();
    payload.mqtt_port = parseInt(document.getElementById("cfg-mqtt-port").value, 10) || 1883;
    payload.mqtt_username = document.getElementById("cfg-mqtt-user").value.trim();

    const mqttPass = document.getElementById("cfg-mqtt-pass").value;
    if (mqttPass) {
      payload.mqtt_password = mqttPass;
    }

    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const result = await res.json();
    if (res.ok && result.success) {
      showToast("Configurações salvas no banco de dados com sucesso!", "success");
      closeModal("modal-settings");
    } else {
      showToast("Erro ao salvar: " + (result.message || "Erro desconhecido"), "error");
    }
  } catch (err) {
    console.error("Falha ao salvar configurações:", err);
    showToast("Falha de conexão ao salvar configurações.", "error");
  } finally {
    saveBtn.disabled = false;
    saveBtn.innerText = "💾 Salvar Configurações";
  }
}

async function testNotification() {
  const btn = document.getElementById("btn-test-alert");
  btn.disabled = true;
  btn.innerText = "Enviando teste...";

  try {
    const res = await fetch("/api/alerts/test", { method: "POST" });
    const result = await res.json();

    if (result.success) {
      showToast("Alerta de teste enviado com sucesso! Verifique seu Telegram ou Discord.", "success");
      loadAlerts();
    } else {
      showToast("Aviso no envio: " + (result.message || "Nenhum canal ativo configurado"), "warning");
    }
  } catch (err) {
    console.error("Erro no teste de notificação:", err);
    showToast("Erro de rede ao disparar teste de notificação.", "error");
  } finally {
    btn.disabled = false;
    btn.innerText = "🧪 Testar Notificação Agora";
  }
}

async function publishMqtt() {
  const btn = document.getElementById("btn-mqtt-publish");
  btn.disabled = true;
  btn.innerText = "Publicando...";

  try {
    const res = await fetch("/api/mqtt/publish", { method: "POST" });
    const result = await res.json();

    if (result.success) {
      showToast(result.message || "Sensores e telemetria publicados no Home Assistant!", "success");
    } else {
      showToast("Falha MQTT: " + (result.message || "Verifique as configurações do broker"), "warning");
    }
  } catch (err) {
    console.error("Erro na publicação MQTT:", err);
    showToast("Erro de rede ao conectar com o broker MQTT.", "error");
  } finally {
    btn.disabled = false;
    btn.innerText = "📡 Publicar MQTT Agora";
  }
}

// ==============================================================================
// Sincronização Sob Demanda
// ==============================================================================

async function triggerSync() {
  const btn = document.getElementById("btn-sync");
  const btnText = btn.querySelector(".btn-text");
  btn.disabled = true;
  btnText.innerText = "Sincronizando...";

  try {
    const res = await fetch("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: false, sync_channels: true })
    });
    const result = await res.json();

    if (result.success) {
      showToast(`Sincronização concluída! Geração hoje: ${result.today_kwh.toFixed(2)} kWh`, "success");
      await loadDashboard();
    } else {
      showToast("Aviso: " + (result.message || "Sincronização não permitida pelo Budget Keeper"), "warning");
    }
  } catch (err) {
    console.error("Erro na sincronização manual:", err);
    showToast("Erro de conexão ao sincronizar com a usina.", "error");
  } finally {
    btn.disabled = false;
    btnText.innerText = "Sincronizar";
  }
}

// ==============================================================================
// Recuperação Histórica Retroativa (Backfill - 1 Requisição OpenAPI)
// ==============================================================================

async function triggerBackfill() {
  const btnHeader = document.getElementById("btn-backfill");
  const btnChart = document.getElementById("btn-chart-backfill");

  const originalHeaderText = btnHeader ? btnHeader.innerHTML : "";
  const originalChartText = btnChart ? btnChart.innerHTML : "";

  if (btnHeader) {
    btnHeader.disabled = true;
    btnHeader.innerText = "Recuperando mês...";
  }
  if (btnChart) {
    btnChart.disabled = true;
    btnChart.innerText = "Recuperando...";
  }

  try {
    const res = await fetch("/api/backfill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: false })
    });
    const result = await res.json();

    if (result.success) {
      showToast(`Sucesso! ${result.records_synced} dias históricos foram sincronizados com apenas 1 requisição.`, "success");
      await loadDashboard();
    } else if (result.quota_exhausted) {
      showToast(result.message, "error");
      await loadDashboard();
    } else {
      showToast("Aviso: " + (result.message || "Não foi possível recuperar o histórico."), "warning");
    }
  } catch (err) {
    console.error("Erro no backfill histórico:", err);
    showToast("Erro de conexão ao recuperar histórico da usina.", "error");
  } finally {
    if (btnHeader) {
      btnHeader.disabled = false;
      btnHeader.innerHTML = originalHeaderText;
    }
    if (btnChart) {
      btnChart.disabled = false;
      btnChart.innerHTML = originalChartText;
    }
  }
}

// ==============================================================================
// Exportação de Dados
// ==============================================================================

async function loadExportSummary() {
  try {
    const res = await fetch("/api/export/summary");
    const data = await res.json();

    document.getElementById("exp-total-days").innerText = data.total_days_recorded || 0;
    document.getElementById("exp-total-kwh").innerText = `${(data.total_energy_kwh || 0).toFixed(2)} kWh`;
  } catch (err) {
    console.error("Erro ao carregar resumo de exportação:", err);
  }
}

// ==============================================================================
// Sistema de Toasts Flutuantes
// ==============================================================================

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  const iconMap = {
    success: "✅",
    info: "ℹ️",
    warning: "⚠️",
    error: "❌"
  };

  toast.innerHTML = `<span>${iconMap[type] || "ℹ️"}</span><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ==============================================================================
// Inicialização de Eventos
// ==============================================================================

document.addEventListener("DOMContentLoaded", () => {
  // Inicialização de botões
  document.getElementById("btn-sync").addEventListener("click", triggerSync);
  const btnBackfill = document.getElementById("btn-backfill");
  if (btnBackfill) btnBackfill.addEventListener("click", triggerBackfill);
  const btnChartBackfill = document.getElementById("btn-chart-backfill");
  if (btnChartBackfill) btnChartBackfill.addEventListener("click", triggerBackfill);

  document.getElementById("btn-open-settings").addEventListener("click", () => openModal("modal-settings"));
  document.getElementById("btn-open-export").addEventListener("click", () => openModal("modal-export"));

  // Carrega dashboard inicial
  loadDashboard();

  // Atualização periódica a cada 60s (offline no SQLite, 0 chamadas de cota)
  setInterval(loadDashboard, 60000);
});
