# ==============================================================================
# SolarHub - Production-ready, Multi-arch Minimal Container
# ==============================================================================
FROM python:3.12-slim

# Configurações de ambiente de runtime Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Cria pasta de dados para volume persistente
RUN mkdir -p /app/data

# Copia metadados e código-fonte
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Instalação limpa das dependências e do pacote SolarHub
RUN pip install --no-cache-dir .

# Usuário não-privilegiado (UID 1000) para segurança em produção
RUN groupadd -g 1000 solar && \
    useradd -u 1000 -g solar -s /bin/sh -m solar && \
    chown -R solar:solar /app

USER solar

# Porta HTTP padrão do Dashboard
EXPOSE 8000

# Verificação de integridade sem dependência externa (curl/wget)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/').read()" || exit 1

# Inicialização padrão: Servidor Web + Coletor em Background
CMD ["solar", "web", "--host", "0.0.0.0", "--port", "8000", "--with-daemon"]
