# ☀️ SolarHub (for APsystems)

[![CI](https://github.com/seu-usuario/solar-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/seu-usuario/solar-hub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Docker: Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](Dockerfile)
[![Architecture: Offline--First](https://img.shields.io/badge/Architecture-Offline--First-success.svg)](#arquitetura-do-sistema)


> **Plataforma Open Source, autônoma e soberana de telemetria, diagnóstico e inteligência para usinas solares residenciais baseadas no ecossistema APsystems.**

Diferente de soluções proprietárias fechadas, o **SolarHub** foi projetado especificamente para superar as duas maiores limitações enfrentadas por proprietários de sistemas fotovoltaicos APsystems:
1. **O teto estrito da OpenAPI oficial de 1.000 requisições/mês (~33 chamadas/dia)**: evitamos o esgotamento de cota através de um mecanismo matemático (*Budget Keeper*) com armazenamento local desacoplado.
2. **Generalidade e Soberania de Dados**: mapeia dinamicamente qualquer usina (de 2 a 100+ placas, com microinversores **DS3, QS1, QT2 ou YC1000** e gateways **ECU-R ou ECU-C**), guardando seu histórico completo de geração e saúde elétrica em banco de dados local.

---

## ⚡ Principais Recursos

* **Auto-Descoberta de Topologia (Zero Configuração Manual de Hardware):** Identifica automaticamente quantas ECUs, quais modelos de inversores e quantos canais DC existem na usina com apenas 1 comando (`solar discover`).
* **Guardião Matemático de Cota (*Budget Keeper*):**
  * Bloqueia consultas noturnas desnecessárias (quando a geração solar é nula).
  * Distribui o orçamento de chamadas de forma inteligente durante o dia.
  * Mantém um "cofre de emergência" para consultas manuais e testes.
* **Soberania de Dados (Offline-First):** Seus dados são salvos em SQLite local. Dashboards, bots e consultas no terminal rodam a custo **zero de cota**.
* **Diagnóstico Multicanal & Detecção de Anomalias:** Suporta leitura independente por canal DC para detecção de sujeira, sombreamento, canais desconectados e estresse térmico em cada painel solar individual.
* **Sistema de Alertas & Notificações (Multicanal com Cooldown Anti-Spam):**
  * Disparos automáticos via **Webhooks genéricos** (Discord, Slack, Home Assistant, n8n) e **Telegram Bot**.
  * Alertas para anomalias elétricas graves, sobreaquecimento de microinversores, índice de saúde baixo, geração zero ao meio-dia e cota mensal quase esgotada.
  * Controle de **cooldown configurável** para evitar tempestades de mensagens repetidas.
* **Integração Home Assistant (MQTT Discovery Nativo):**
  * Descoberta automática de sensores no Home Assistant sem precisar escrever YAML: energia do dia, potência dos canais, saúde e temperatura dos inversores.
* **Métricas Prometheus (`/metrics`):**
  * Endpoint compatível com scraping padrão do Prometheus e painéis Grafana em tempo real a custo zero de cota.
* **Interface CLI Moderna:** Terminal interativo com tabelas formatadas (`rich`) para acompanhamento rápido de status, inversores, saldo da cota e histórico de alertas.



---

## 🏗️ Arquitetura do Sistema

```
                      +-----------------------------------+
                      |   Nuvem APsystems (OpenAPI v2)    |
                      |   Limite: 1.000 requisições/mês   |
                      +-----------------+-----------------+
                                        | (Assinatura HMAC-SHA256)
                                        v
+-------------------------------------------------------------------------+
|                              SOLARHUB CORE                              |
|                                                                         |
|  +--------------------+   +---------------------+   +----------------+  |
|  |   Budget Keeper    |-->|   APsystems Client  |-->| Auto-Discovery |  |
|  |  (Gestor de Cota)  |   |    (HTTPX + Auth)   |   |   (Topologia)  |  |
|  +--------------------+   +---------------------+   +----------------+  |
|                                      |                                  |
|                                      v                                  |
|                        +---------------------------+                    |
|                        |  Banco Local (SQLite)     |                    |
|                        |  - systems / ecus         |                    |
|                        |  - inverters (DS3/QT2...) |                    |
|                        |  - daily_aggregates       |                    |
|                        |  - api_call_audit         |                    |
|                        +-------------+-------------+                    |
+--------------------------------------|----------------------------------+
                                       |
                   +-------------------+-------------------+
                   | (Zero consumo de cota da APsystems)   |
                   v                                       v
         +-------------------+                   +-------------------+
         |    Terminal CLI   |                   |  Bot Telegram /   |
         |  (solar status)   |                   |  Home Assistant   |
         +-------------------+                   +-------------------+
```

---

## 🚀 Instalação Rápida

### 1. Clonar o Repositório
```bash
git clone https://github.com/seu-usuario/solar-hub.git
cd solar-hub
```

### 2. Configurar o Ambiente Seguro
Copie o modelo de variáveis de ambiente:
```bash
cp .env.example .env
```
Edite o arquivo `.env` com suas credenciais obtidas junto ao suporte da APsystems:
```ini
APSYSTEMS_APP_ID="seu_app_id_de_32_caracteres"
APSYSTEMS_APP_SECRET="seu_app_secret_de_12_caracteres"
APSYSTEMS_SYSTEM_ID="seu_sid_cadastrado_no_app_ema"
```

> 🔒 **Segurança:** O arquivo `.env` já está no `.gitignore` e **nunca** será comitado para o GitHub.

### 3. Execução com Docker Compose (Recomendado)
A forma mais simples e robusta para rodar em servidores residenciais, NAS ou Raspberry Pi:
```bash
docker compose up -d
```
Isso inicia o **Dashboard Web na porta 8000** (`http://localhost:8000`) e o **coletor inteligente em background**, mantendo os dados persistidos no diretório local `./data`.

Para executar comandos pontuais dentro do container Docker:
```bash
# Auto-descoberta de hardware
docker compose run --rm solar-hub solar discover

# Verificar status da usina e cota
docker compose run --rm solar-hub solar status

# Listar inversores conhecidos
docker compose run --rm solar-hub solar inverters
```

---

### 4. Execução Local Alternativa (Python / uv)
Caso prefira executar sem Docker diretamente no ambiente virtual:
```bash
pip install -e .
# ou usando uv:
uv pip install -e .
```

---

## 💻 Comandos da CLI

Após a instalação, o comando `solar` fica disponível no seu terminal:

### 1. Mapear Hardware da Usina
Identifica seus microinversores e salva a topologia no SQLite local:
```bash
solar discover
```

### 2. Painel de Status
Exibe a geração recente (hoje, mês, ano, lifetime) e o saldo da cota:
```bash
solar status
```

### 3. Listar Microinversores Cadastrados
Lista todos os inversores conhecidos e canais DC sem consumir nada da API:
```bash
solar inverters
```

### 5. Sincronizar Telemetria
Sincroniza os dados do dia corrente e salva no banco local:
```bash
solar sync
```

### 6. Executar Coletor em Background (Daemon)
Mantém a coleta automática a cada 30 min com fechamento noturno às 20h:
```bash
solar daemon
```

### 7. Consultar Histórico Local Offline
Exibe a tabela diária diretamente do SQLite (zero chamadas de API):
```bash
solar history
```

### 8. Telemetria Granular por Canal DC (Painel Solar)
Exibe a geração individual de cada canal e painel solar conectado aos microinversores:
```bash
solar channels
# Para forçar uma sincronização prévia com a API:
solar channels --sync
```

### 9. Diagnóstico Elétrico Fino do Inversor (V, A, W, °C, Hz)
Consulta instantânea de grandezas elétricas e térmicas de um microinversor específico:
```bash
solar telemetry <UID_DO_INVERSOR>
```

### 10. Motor de Diagnóstico e Detecção de Anomalias
Analisa desvios estatísticos entre placas (detecção de sujeira, sombreamento, canal desconectado e sobreaquecimento):
```bash
solar diagnose
# Para avaliar e disparar notificações imediatas se encontrar anomalias:
solar diagnose --notify
```

### 11. Testar Canais de Notificação (Webhook & Telegram)
Envia uma mensagem de teste imediata contornando o cooldown para validar URLs e tokens:
```bash
solar test-alert
```

### 12. Histórico Local de Alertas e Notificações
Exibe o registro de alertas disparados e seu status de entrega:
```bash
solar alerts
```

### 13. Exportar Dados Locais (CSV / JSON com Zero Cota)
Exporta séries históricas de geração ou telemetria multicanal diretamente do SQLite:
```bash
# Exportar geração diária em CSV para arquivo
solar export generation -f csv -o relatorio_solar.csv

# Exportar geração filtrando período em JSON
solar export generation -f json --start 2026-10-01 --end 2026-10-31

# Exportar telemetria de canais filtrada por microinversor
solar export channels -f csv --uid 401000001234 -o canais_inv1.csv
```

### 14. Publicar Estado no Broker MQTT (Home Assistant)
Registra as entidades de auto-descoberta e envia o estado atual para o broker MQTT:
```bash
solar mqtt-publish
```

### 15. Iniciar o Dashboard Web Local
Inicia o servidor web leve e responsivo (porta padrão 8000):
```bash
solar web
```

---

## 📡 Observabilidade & Smart Home (Home Assistant & Prometheus)

### 1. Home Assistant (MQTT Discovery)
Ao habilitar `MQTT_ENABLED=true` no `.env`, o **SolarHub** envia mensagens de auto-descoberta (`homeassistant/sensor/.../config`). Seus sensores aparecem imediatamente no painel de dispositivos do Home Assistant:
* **Entidades Criadas Automaticamente:**
  * `sensor.solar_energy_today` (dispositivo de energia compatível com o Energy Dashboard)
  * `sensor.solar_operational_health` (score 0-100%)
  * `sensor.solar_budget_remaining` (saldo mensal de chamadas da API)
  * Sensores individuais de potência e kWh por canal DC / painel solar.

### 2. Scraping Prometheus & Dashboards Grafana
O servidor expõe nativamente métricas no formato padrão do Prometheus:
```bash
curl http://localhost:8000/metrics
```
* **Métricas Disponíveis:**
  * `solar_today_kwh`
  * `solar_capacity_kwp`
  * `solar_health_score`
  * `solar_budget_calls_this_month`, `solar_budget_monthly_limit`, `solar_budget_remaining`
  * `solar_channel_energy_today_kwh{inverter_uid="...",channel="1"}`
  * `solar_channel_power_watts{inverter_uid="...",channel="1"}`
  * `solar_inverter_temperature_celsius{inverter_uid="..."}`

---

## 🌐 Dashboard Web Local (100% Offline & Self-Hosted)

O **SolarHub** inclui um Dashboard Web moderno, leve e totalmente self-hosted:
* **Zero CDNs ou Fontes Externas:** Chart.js embutido localmente, garantindo total privacidade e velocidade instantânea.
* **Hero Cards:** Geração do dia (kWh), microinversores ativos, potência instalada e saldo da cota mensal.
* **🏆 Hall of Fame:** Painel que destaca o recorde histórico de melhor dia de geração de todos os tempos.
* **Gráfico Interativo:** Curva diária de geração navegável e responsiva (desktop e celular).
* **Grid de Microinversores:** Mapeamento visual de cada inversor físico e seus canais DC.

Para iniciar, basta rodar:
```bash
solar web
```
E acessar `http://localhost:8000` no seu navegador.


---

## 🧪 Testes Automatizados

O projeto conta com suíte de testes unitários para a assinatura criptográfica, mapeamento de topologias, lógica de cota e rotas da API Web:

```bash
pytest
```

---

## 🙏 Agradecimentos & Inspiração de Produto

A arquitetura analítica offline-first, a experiência de usuário do Dashboard e conceitos visuais como o **Hall of Fame** (recordes históricos da usina) e agregação diária no SQLite foram diretamente inspirados pelo excelente projeto open source [ez1-monitor](https://github.com/TehcSimon/ez1-monitor) desenvolvido por **Simon (TehcSimon)**, disponibilizado sob a licença MIT. 

Estendemos nossos sinceros créditos e agradecimentos à comunidade e ao autor pelo modelo de qualidade e simplicidade que serviu de referência para a expansão do monitoramento de usinas residenciais com ECU e microinversores multicanais (DS3, QS1, QT2 e YC1000).

---

## 🤝 Como Contribuir

Contribuições são muito bem-vindas! Consulte o guia completo em [CONTRIBUTING.md](CONTRIBUTING.md) para diretrizes de desenvolvimento, arquitetura agnóstica de cota e padrões de código.

1. Faça um Fork do projeto
2. Crie sua branch de funcionalidade (`git checkout -b feature/nova-integracao`)
3. Execute a suíte de testes (`pytest`) e o linter (`ruff check .`)
4. Faça o commit das alterações (`git commit -m 'feat: adiciona nova funcionalidade'`)
5. Suba para o GitHub (`git push origin feature/nova-integracao`)
6. Abra um Pull Request


---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja [LICENSE](LICENSE) para mais detalhes.

