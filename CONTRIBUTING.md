# Contributing to SolarHub

Thank you for your interest in contributing to **SolarHub**! We welcome community contributions, bug reports, and feature proposals.

---

## 🌟 Core Architectural Principles

Before writing code, please keep in mind the fundamental design principles of SolarHub:

1. **Zero Local Policy Hardcoding (Global by Design):**
   * Never hardcode regional electric utility rules, net metering formulas, local feed-in tariffs, or monetary currency conversions in the product core.
   * SolarHub focuses exclusively on physical, electrical, and telemetry metrics (kWh, kW, W, V, A, Hz, °C, Health Score). Regional financial analysis belongs in local client scripts or external platforms (such as Home Assistant).

2. **Strict Quota Governance (*Budget Keeper*):**
   * The official APsystems OpenAPI limits accounts to **1,000 requests per month** (~33 calls/day).
   * Any new feature that makes HTTP calls to APsystems MUST be vetted by `BudgetKeeperService`. Batch endpoints (`/inverter/batch/energy/{eid}`) must always be preferred over individual inverter loops.

3. **Offline-First & Data Sovereignty:**
   * User telemetry is persisted in a local SQLite database.
   * Dashboards, CLI commands (`solar status`, `solar history`, `solar inverters`), Prometheus exports (`/metrics`), MQTT broadcasting, and data exports (`solar export`) MUST read from local SQLite without consuming API quota.

---

## 🛠️ Development Setup

### Prerequisites
* Python 3.11, 3.12, or 3.13
* [`uv`](https://docs.astral.sh/uv/) (recommended) or standard `pip` / `venv`
* Git

### Step-by-Step Setup

1. **Fork and Clone the Repository:**
   ```bash
   git clone https://github.com/your-username/solar-hub.git
   cd solar-hub
   ```

2. **Install Dependencies:**
   Using `uv` (fastest):
   ```bash
   uv sync --extra dev
   ```
   Or standard pip:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. **Configure Environment:**
   ```bash
   cp .env.example .env
   ```
   *Note: Tests use in-memory SQLite and mock fixtures, so live APsystems credentials are NOT required to run tests.*

---

## 🧪 Testing & Code Quality

Before opening a pull request, ensure all tests and linter checks pass:

1. **Run the Test Suite:**
   ```bash
   uv run pytest
   ```

2. **Run the Ruff Linter:**
   ```bash
   uv run ruff check .
   ```
   To automatically fix simple formatting and import sorting issues:
   ```bash
   uv run ruff check . --fix
   ```

---

## 🚀 Submitting a Pull Request

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Commit your changes with descriptive messages:
   ```bash
   git commit -m "feat(mqtt): add custom state topic prefix"
   ```
3. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
4. Open a Pull Request against the `main` branch.
5. Ensure the GitHub Actions CI pipeline passes all checks (Ruff, Pytest on Python 3.11-3.13, and Docker build).

Thank you for helping make SolarHub the best open-source telemetry platform for solar energy! ☀️
