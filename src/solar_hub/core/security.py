import ipaddress
import logging
import secrets
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)

from solar_hub.core.config import Settings

logger = logging.getLogger(__name__)

# Redes e faixas de IP proibidas para destinos de webhook (proteção contra SSRF e metadados de nuvem)
FORBIDDEN_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback IPv4
    ipaddress.ip_network("10.0.0.0/8"),       # Privada Classe A (RFC 1918)
    ipaddress.ip_network("172.16.0.0/12"),    # Privada Classe B (RFC 1918)
    ipaddress.ip_network("192.168.0.0/16"),   # Privada Classe C (RFC 1918)
    ipaddress.ip_network("169.254.0.0/16"),   # Link-Local / Cloud Instance Metadata (AWS, DO, Hetzner, GCP)
    ipaddress.ip_network("0.0.0.0/8"),        # Broadcast / rede local
    ipaddress.ip_network("::1/128"),          # Loopback IPv6
    ipaddress.ip_network("fc00::/7"),         # Unique Local IPv6
    ipaddress.ip_network("fe80::/10"),        # Link-Local IPv6
]

# Provedores conhecidos de metadados de cloud
CLOUD_METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.tencentyun.com",
    "100.100.100.200",
}


def is_safe_webhook_url(url_str: str, allow_private: bool = False) -> Tuple[bool, str]:
    """
    Valida rigorosamente a URL de webhook para prevenir ataques de
    Server-Side Request Forgery (SSRF) contra serviços locais da VPS e metadados de nuvem.
    """
    if not url_str or not url_str.strip():
        return False, "URL vazia ou não informada."

    clean_url = url_str.strip()
    try:
        parsed = urlparse(clean_url)
    except Exception as e:
        return False, f"URL malformada: {e}"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, f"Protocolo '{scheme}' não permitido. Use HTTP ou HTTPS."

    hostname = parsed.hostname
    if not hostname:
        return False, "Hostname ausente na URL."

    clean_host = hostname.lower()

    # Bloqueia explicitamente hosts de loopback e metadados conhecidos
    if clean_host in ("localhost", "127.0.0.1", "::1") or clean_host in CLOUD_METADATA_HOSTS:
        return False, "Destino aponta para endereço de loopback ou metadados de nuvem proibido."

    # Permite domínios reservados pela IANA para documentação e testes (RFC 2606 / RFC 6761)
    if clean_host in ("example.com", "example.org", "example.net") or clean_host.endswith(
        (".example", ".test", ".example.com", ".example.org", ".example.net")
    ):
        return True, "URL segura (domínio de teste RFC 2606)"

    # Resolução DNS para verificação dos endereços IP subjacentes
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        return False, f"Falha ao resolver o domínio '{hostname}': {e}"
    except Exception as e:
        return False, f"Erro ao verificar hostname '{hostname}': {e}"

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        # Loopback e Cloud Metadata são SEMPRE bloqueados (mesmo se allow_private for True)
        if ip.is_loopback or ip_str == "169.254.169.254" or ip.is_link_local:
            return False, f"O IP {ip_str} é restrito (loopback ou metadados de nuvem)."

        # Se requisições a redes privadas estiverem bloqueadas (padrão seguro em VPS)
        if not allow_private:
            if ip.is_private:
                return False, f"O IP {ip_str} pertence à rede privada interna e está bloqueado."

            for net in FORBIDDEN_PRIVATE_NETWORKS:
                if ip in net:
                    return False, f"O IP {ip_str} está contido na faixa de rede restrita {net}."

    return True, "URL segura"


# Configuração dos esquemas de autenticação suportados
security_basic = HTTPBasic(auto_error=False)
security_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)
security_bearer = HTTPBearer(auto_error=False)


def get_current_settings() -> Settings:
    """Helper para injeção de dependência das configurações."""
    return Settings()


def require_auth(
    credentials: Optional[HTTPBasicCredentials] = Security(security_basic),
    api_key_header: Optional[str] = Security(security_api_key),
    bearer_token: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    settings: Settings = Depends(get_current_settings),
) -> bool:
    """
    Dependência de segurança que valida credenciais de acesso caso configuradas no ambiente.
    Suporta:
    - HTTP Basic Auth (usuário e senha do .env: AUTH_USERNAME / AUTH_PASSWORD)
    - X-API-Key header (chave estática do .env: API_KEY)
    - Bearer Token (Authorization: Bearer <API_KEY>)

    Se nem AUTH_USERNAME nem API_KEY estiverem definidos, a autenticação permanece aberta (modo local).
    """
    # Se autenticação não estiver configurada no .env, permite acesso (modo desenvolvimento local)
    is_basic_configured = bool(settings.auth_username and settings.auth_password)
    is_apikey_configured = bool(settings.api_key)

    if not is_basic_configured and not is_apikey_configured:
        return True

    # 1. Validação via API Key no header X-API-Key
    if is_apikey_configured and api_key_header:
        if secrets.compare_digest(api_key_header, settings.api_key):
            return True

    # 2. Validação via Bearer Token (Authorization: Bearer <API_KEY>)
    if is_apikey_configured and bearer_token:
        if secrets.compare_digest(bearer_token.credentials, settings.api_key):
            return True

    # 3. Validação via HTTP Basic Auth
    if is_basic_configured and credentials:
        user_matches = secrets.compare_digest(credentials.username, settings.auth_username)
        pass_matches = secrets.compare_digest(credentials.password, settings.auth_password)
        if user_matches and pass_matches:
            return True

    # Falha na autenticação
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Acesso não autorizado. Forneça credenciais válidas.",
        headers={"WWW-Authenticate": 'Basic realm="SolarHub Protegido"'},
    )
