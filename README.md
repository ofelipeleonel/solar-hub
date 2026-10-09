# ☀️ SolarHub (for APsystems)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Architecture: Offline--First](https://img.shields.io/badge/Architecture-Offline--First-success.svg)](#arquitetura-e-gestão-de-cota)

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
* **Diagnóstico Multicanal:** Suporta leitura independente por canal DC para detecção de sujeira, sombreamento e degradação em cada painel solar individual.
* **Interface CLI Moderna:** Terminal interativo com tabelas formatadas (`rich`) para acompanhamento rápido de status, inversores e saldo da cota.

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

### 3. Instalar Dependências
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
Exibe a geração recente (hoje, mês, lifetime, economia estimada) e o saldo da cota:
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

### 8. Iniciar o Dashboard Web Local
Inicia o servidor web leve e responsivo (porta padrão 8000):
```bash
solar web
```

---

## 🌐 Dashboard Web Local (100% Offline & Self-Hosted)

O **SolarHub** inclui um Dashboard Web moderno, leve e totalmente self-hosted:
* **Zero CDNs ou Fontes Externas:** Chart.js embutido localmente, garantindo total privacidade e velocidade instantânea.
* **Hero Cards:** Geração do dia (kWh), economia financeira estimada na moeda local, potência instalada e saldo da cota mensal.
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

Contribuições são muito bem-vindas!
1. Faça um Fork do projeto
2. Crie sua branch de funcionalidade (`git checkout -b feature/nova-integracao`)
3. Faça o commit das alterações (`git commit -m 'feat: adiciona nova funcionalidade'`)
4. Suba para o GitHub (`git push origin feature/nova-integracao`)
5. Abra um Pull Request

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja [LICENSE](LICENSE) para mais detalhes.

