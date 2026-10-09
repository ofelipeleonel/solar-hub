# Documentação de Contexto da API APsystems (OpenAPI v2)

Este documento sintetiza as especificações técnicas, mecanismos de autenticação, modelos de dados, restrições contratuais e boas práticas da **OpenAPI da APsystems** (Altenergy Power System Inc.), com base no manual de usuário (`Apsystems_OpenAPI_User_Manual_End_User_EN.pdf`) e no termo de licenciamento (`API_License_Terms_and_Conditions_English.pdf`).

---

## 1. Visão Geral do Sistema e Arquitetura

O ecossistema de monitoramento solar da APsystems (plataforma **EMA - Energy Monitoring & Analysis**) organiza os equipamentos na seguinte hierarquia:

```
[System (Sistema / Instalação - sid)]
  └── [ECU (Energy Communication Unit - eid)]
        ├── [Meters (Medidores de consumo/injeção - se houver)]
        ├── [Storage (Baterias de armazenamento - se houver)]
        └── [Inverters (Microinversores - uid: DS3, QS1, QT2, etc.)]
              └── [Canais DC (Canal 1 a 4: painéis solares individuais)]
```

* **System (`sid`)**: ID único do sistema fotovoltaico residencial cadastrado na EMA.
* **ECU (`eid`)**: Gateway local da APsystems que se comunica via Zigbee com os microinversores e via Wi-Fi/Ethernet com a nuvem EMA.
* **Microinversores (`uid`)**: Dispositivos nos painéis que convertem a energia de corrente contínua (DC) em alternada (AC). Cada inversor possui canais independentes (ex: 2 canais no DS3, 4 canais no QS1/QT2).
* **Meters & Storage**: Módulos opcionais para leitura bidirecional da rede elétrica (consumo x importação x exportação) e bancos de baterias.

---

## 2. Autenticação e Requisições

* **Base URL**: `https://api.apsystemsema.com:9282`
* **Protocolo**: HTTPS / REST / JSON
* **Método de Autenticação**: Assinatura criptográfica por requisição (**HMAC-SHA256** ou HMAC-SHA1).

### 2.1 Obtenção das Credenciais
Para obter acesso à OpenAPI, é necessário enviar um e-mail de solicitação para `apisupport@apsystems.com` informando:
1. Quem é você (identificação da conta EMA do cliente final);
2. Por que quer registrar uma conta de OpenAPI (ex: monitoramento residencial próprio);
3. O que pretende fazer com os dados.

Após aprovação, são fornecidos:
* **App Id**: String alfanumérica de 32 caracteres (identificador imutável).
* **App Secret**: Senha alfanumérica de 12 caracteres (usada como chave secreta HMAC).

### 2.2 Headers Obrigatórios em Todas as Requisições
| Header | Tipo | Descrição |
| :--- | :--- | :--- |
| `X-CA-AppId` | String | O seu `App Id` (32 caracteres). |
| `X-CA-Timestamp` | String | Timestamp Unix atual no momento da chamada. |
| `X-CA-Nonce` | String | UUID aleatório de 32 caracteres (evita ataques de replay). |
| `X-CA-Signature-Method` | String | `"HmacSHA256"` (recomendado) ou `"HmacSHA1"`. |
| `X-CA-Signature` | String | Assinatura calculada codificada em **Base64**. |

### 2.3 Algoritmo de Cálculo da Assinatura (`Signature`)
1. **Identificar o `RequestPath`**: Apenas o **último segmento** do path da URL.
   * *Exemplo*: se a URL for `/user/api/v2/systems/details/AZ12649A3DFF`, o `RequestPath` será `AZ12649A3DFF`.
2. **Construir a `stringToSign`**:
   ```
   stringToSign = X-CA-Timestamp + "/" + X-CA-Nonce + "/" + X-CA-AppId + "/" + RequestPath + "/" + HTTPMethod + "/" + X-CA-Signature-Method
   ```
3. **Calcular o HMAC**:
   * Usar a chave secreta (`App Secret`).
   * Aplicar algoritmo HMAC-SHA256 nos bytes UTF-8 da `stringToSign`.
   * Converter o hash resultante em Base64.

---

## 3. Catálogo de Endpoints e Dados Disponíveis

### 3.1 Informações do Sistema e Topologia (`System Details API`)

#### 3.1.1 Detalhes Gerais da Usina
* **Endpoint**: `GET /user/api/v2/systems/details/{sid}`
* **Dados Retornados**:
  * `sid`: Identificador do sistema.
  * `create_date`: Data de comissionamento no portal EMA (`yyyy-MM-dd`).
  * `capacity`: Potência nominal instalada do sistema (em kW).
  * `type`: Tipo de instalação (`1`: Fotovoltaico padrão, `2`: Apenas baterias, `3`: Híbrido PV + Baterias).
  * `timezone`: Fuso horário configurado na ECU (ex: `"America/Sao_Paulo"`).
  * `ecu`: Lista de IDs de ECUs vinculadas ao sistema.
  * `light`: Status de saúde da usina:
    * `1` (Verde): Operando normalmente.
    * `2` (Amarelo): Alarmes detectados em algum microinversor ou não registrado.
    * `3` (Vermelho): Falha de comunicação/rede na ECU.
    * `4` (Cinza): Nenhum dado enviado até o momento.
  * `authorization_code`: Token que permite gerar páginas de exibição iframe embutíveis.

#### 3.1.2 Lista de Inversores e ECUs
* **Endpoint**: `GET /user/api/v2/systems/inverters/{sid}`
* **Dados Retornados**:
  * Lista de ECUs (`eid`, `type`, `timezone`) com os microinversores vinculados:
    * `uid`: Número de série / ID único do microinversor.
    * `type`: Modelo do inversor (ex: `"DS3"`, `"QT2D"`, `"YC600"`, etc.).

#### 3.1.3 Lista de Medidores (Meters)
* **Endpoint**: `GET /user/api/v2/systems/meters/{sid}`
* **Dados Retornados**: Array com IDs dos medidores inteligentes cadastrados.

---

### 3.2 Dados Agregados do Sistema (`System-level Data API`)

#### 3.2.1 Resumo Acumulado
* **Endpoint**: `GET /user/api/v2/systems/summary/{sid}`
* **Dados Retornados** (em kWh):
  * `today`: Geração acumulada do dia.
  * `month`: Geração acumulada no mês corrente.
  * `year`: Geração acumulada no ano corrente.
  * `lifetime`: Geração total acumulada desde o comissionamento da usina.

#### 3.2.2 Energia Histórica por Período
* **Endpoint**: `GET /user/api/v2/systems/energy/{sid}`
* **Parâmetros de Consulta**:
  * `energy_level`: `"hourly"`, `"daily"`, `"monthly"` ou `"yearly"`.
  * `date_range`: Formato dependente do nível:
    * Para `"hourly"`: `yyyy-MM-dd` (retorna array de 24 valores em kWh, das horas 0 às 23).
    * Para `"daily"`: `yyyy-MM` (retorna array de N valores correspondentes aos dias do mês).
    * Para `"monthly"`: `yyyy` (retorna array de 12 meses).
    * Para `"yearly"`: Não requerido (retorna array de anos desde a instalação).

---

### 3.3 Dados a Nível de ECU (`ECU-level Data API`)
Permite inspecionar a geração direta agregada por gateway:
* `GET /user/api/v2/systems/{sid}/devices/ecu/summary/{eid}`: Resumo acumulado da ECU.
* `GET /user/api/v2/systems/{sid}/devices/ecu/energy/{eid}`:
  * Suporta `energy_level = "minutely"` com `date_range = yyyy-MM-dd`.
  * Retorna listas detalhadas minuto a minuto do dia:
    * `time`: Horários no formato `HH:mm`.
    * `power`: Potência instantânea em Watts (W) a cada intervalo.
    * `energy`: Energia gerada em kWh no intervalo.
    * `today`: Total acumulado do dia em kWh.

---

### 3.4 Dados de Balanço de Rede / Medidor (`Meter-level Data API`)
*Aplicável quando a instalação possui o módulo APsystems Energy Meter ou medidor compatível.*
* **Endpoints**:
  * Resumo: `GET /user/api/v2/systems/{sid}/devices/meter/summary/{eid}`
  * Período: `GET /user/api/v2/systems/{sid}/devices/meter/period/{eid}`
* **Métricas Chave**:
  * `consumed`: Energia total consumida pela residência (kWh ou W).
  * `produced`: Energia total gerada pelo sistema solar fotovoltaico.
  * `imported`: Energia puxada da rede elétrica da concessionária.
  * `exported`: Energia excedente injetada na rede da concessionária (geração de créditos).

---

### 3.5 Telemetria Granular de Microinversores (`Inverter-level Data API`) - **O Ponto Mais Valioso**

Esta categoria fornece os dados mais ricos e detalhados da usina, permitindo diagnósticos a nível de painel solar individual.

#### 3.5.1 Resumo por Canal do Inversor
* **Endpoint**: `GET /user/api/v2/systems/{sid}/devices/inverter/summary/{uid}`
* **Dados Retornados**:
  * `d1`, `d2`, `d3`, `d4`: Energia gerada hoje pelo canal 1, 2, 3 e 4 (kWh).
  * `m1`, `m2`, `m3`, `m4`: Energia gerada no mês pelos canais 1 a 4.
  * `y1`, `y2`, `y3`, `y4`: Energia gerada no ano pelos canais 1 a 4.
  * `t1`, `t2`, `t3`, `t4`: Energia vitalícia (lifetime) de cada canal.

#### 3.5.2 Telemetria Minuto a Minuto de Cada Inversor
* **Endpoint**: `GET /user/api/v2/systems/{sid}/devices/inverter/energy/{uid}`
* **Parâmetro**: `energy_level = "minutely"`, `date_range = "yyyy-MM-dd"`.
* **Dados Retornados em Alta Resolução**:
  * `t`: Lista de horários (`HH:mm`).
  * **Corrente Contínua (DC) por Entrada/Painel**:
    * `dc_p1`, `dc_p2`, `dc_p3`, `dc_p4`: Potência DC de cada canal (W).
    * `dc_v1`, `dc_v2`, `dc_v3`, `dc_v4`: Tensão DC de cada canal (Volts).
    * `dc_i1`, `dc_i2`, `dc_i3`, `dc_i4`: Corrente DC de cada canal (Amperes).
    * `dc_e1`, `dc_e2`, `dc_e3`, `dc_e4`: Energia DC acumulada por canal (kWh).
  * **Corrente Alternada (AC) de Saída**:
    * `ac_p`: Potência AC ativa entregue pelo microinversor à casa/rede (W).
    * `ac_v1`, `ac_v2`, `ac_v3`: Tensão da rede elétrica AC por fase (Volts).
    * `ac_f`: Frequência da rede elétrica (Hz - nominalmente 60 Hz no Brasil).
    * `ac_t`: **Temperatura interna do microinversor (°C)**.

#### 3.5.3 Leitura em Lote do Dia (Batch)
* **Endpoint**: `GET /user/api/v2/systems/{sid}/devices/inverter/batch/energy/{eid}`
* Permite obter a telemetria do dia inteiro para todos os inversores de uma ECU em uma única chamada.

---

### 3.6 Armazenamento e Baterias (`Storage-level Data API`)
Se a instalação incluir sistema de armazenamento de energia (ESS):
* `GET /user/api/v2/systems/{sid}/devices/storage/latest/{eid}`:
  * `soc`: Nível de carga da bateria (% State of Charge).
  * `charge`: Potência instantânea de carregamento (W).
  * `discharge`: Potência instantânea de descarga (W).
  * `mode`: Modo de operação do sistema de baterias.

---

## 4. Termos de Uso, Licenciamento e Restrições Importantes

Com base no documento legal `API_License_Terms_and_Conditions_English.pdf`:

1. **Finalidade Permitida**:
   * Uso interno e pessoal pelo próprio proprietário da usina para monitoramento, manutenção e gestão de consumo.
   * Não é permitido revender nem comercializar dados obtidos da API para terceiros.
2. **Restrição de Redistribuição de Dados Brutos (Cláusula 2.1.a.ii)**:
   * Proíbe explicitamente distribuir dados históricos a terceiros em formato facilmente manipulável ou exportável (como tabelas filtráveis, arquivos `.csv`, `.xls`, `.txt`, `.pdf`). Para seu próprio uso pessoal/armazenamento local privado, não há impedimento.
3. **Limite de Requisições da Conta (Cota Mensal: 1.000 requisições/mês)**:
   * **Restrição Crítica**: O plano contratado/concedido possui limite de **1.000 chamadas por mês**.
   * Isso equivale a uma média de aproximadamente **~33 requisições por dia**.
   * Caso o limite seja ultrapassado, a API retorna o erro `2005` (*The access limit of the application account was exceeded*).

4. **Estratégia Recomendada de Orçamento de Chamadas (Call Budgeting)**:
   * **Arquitetura Orientada a Cache Local (Regra de Ouro)**: NUNCA faça chamadas à API diretamente pelo frontend de dashboards ou por interações do usuário. Adote o padrão de ingestão em lote:
     $$\text{API APsystems} \xrightarrow{\text{Cron/Worker}} \text{Banco Local (SQLite/PostgreSQL)} \xrightarrow{\text{Livre}} \text{Dashboards / Automações}$$
   * **Janela Solar Ativa**: Como à noite não há irradiação nem produção fotovoltaica, **suspenda as requisições noturnas**.
   * **Orçamento Sugerido para 33 requisições/dia**:
     * **Horário Solar (06:30 às 18:30 - 12h)**: 1 chamada a cada 25 ou 30 minutos $\rightarrow$ **~24 a 28 chamadas/dia**.
     * **Fechamento Noturno (20:00)**: 1 chamada consolidada diária para gravar os totais definitivos $\rightarrow$ **1 chamada/dia**.
     * **Margem de Segurança / Consultas Manuais**: ~4 a 8 chamadas/dia de folga para testes ou chamadas pontuais.
     * **Total**: ~29 a 30 chamadas/dia = **~900 requisições/mês** (abaixo do teto de 1.000).
   * **Priorizar Endpoints Batch**: Usar sempre `GET /user/api/v2/systems/{sid}/devices/inverter/batch/energy/{eid}` para coletar todos os inversores de uma só vez, em vez de fazer chamadas individuais por microinversor.

---

## 5. Principais Insights e Oportunidades Extraídos dos Dados

A presença de **tensão, corrente e potência por canal individual**, somada à **temperatura do inversor**, **tensão/frequência da rede da concessionária** e **métricas de balanço de energia**, torna a API da APsystems muito superior a sistemas de string convencionais. 

Com o teto de **1.000 requisições/mês**, a melhor abordagem técnica é uma arquitetura com **coletor periódico leve + banco local (ex: SQLite ou DuckDB)**, permitindo dashboards e automações em tempo real consultando o banco local sem consumir a cota da API.
