@echo off
REM ==============================================================================
REM SolarHub - Script de Inicialização Rápida (Windows)
REM ==============================================================================
TITLE SolarHub - Monitoramento Solar APsystems

echo ===================================================
echo             SolarHub (APsystems)
echo ===================================================
echo.

REM Verifica se o arquivo .env existe
if not exist .env (
    echo [AVISO] Arquivo .env nao encontrado!
    if exist .env.example (
        echo Copiando .env.example para .env...
        copy .env.example .env >nul
        echo [INFO] Arquivo .env criado. Configure suas credenciais antes de continuar.
    )
)

echo Escolha como deseja iniciar o SolarHub:
echo [1] Docker Compose (Recomendado - Isolado em container com Coletor e Web)
echo [2] Local (uv / Python no seu ambiente virtual)
echo [3] Executar testes automatizados (pytest)
echo [4] Sair
echo.
set /p choice="Digite sua opcao (1-4) [padrao: 1]: "

if "%choice%"=="" set choice=1

if "%choice%"=="1" (
    echo.
    echo Iniciando via Docker Compose...
    docker compose up -d
    echo.
    echo [OK] SolarHub rodando em background!
    echo Acesse o dashboard no seu navegador: http://localhost:8000
    echo Para ver os logs: docker compose logs -f
    echo Para parar: docker compose down
    pause
    exit /b 0
)

if "%choice%"=="2" (
    echo.
    echo Iniciando localmente via Python/uv...
    if exist .venv (
        call .venv\Scripts\activate.bat
    )
    echo Abrindo servidor web com coletor integrado em http://localhost:8000 ...
    python -m uvicorn solar_hub.interfaces.web.app:app --host 0.0.0.0 --port 8000 --reload
    exit /b 0
)

if "%choice%"=="3" (
    echo.
    echo Executando testes unitarios...
    if exist .venv (
        call .venv\Scripts\activate.bat
    )
    pytest
    pause
    exit /b 0
)

exit /b 0
