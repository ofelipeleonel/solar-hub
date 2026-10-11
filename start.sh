#!/usr/bin/env bash
# ==============================================================================
# SolarHub - Quick Start Script (Linux / macOS)
# ==============================================================================
set -e

echo "==================================================="
echo "            SolarHub (APsystems)"
echo "==================================================="
echo ""

# Check for .env file
if [ ! -f .env ]; then
    echo "[AVISO] Arquivo .env não encontrado!"
    if [ -f .env.example ]; then
        echo "Copiando .env.example para .env..."
        cp .env.example .env
        echo "[INFO] Arquivo .env criado. Configure suas credenciais."
    fi
fi

# Detect docker
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "Iniciando via Docker Compose..."
    docker compose up -d
    echo ""
    echo "[OK] SolarHub rodando em background!"
    echo "Acesse o dashboard em: http://localhost:8000"
    echo "Logs: docker compose logs -f"
    echo "Parar: docker compose down"
else
    echo "Docker não detectado ou indisponível. Iniciando localmente via Python..."
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi
    uvicorn solar_hub.interfaces.web.app:app --host 0.0.0.0 --port 8000
fi
