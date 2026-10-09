import base64
import hashlib
import hmac
import time
import uuid
from typing import Dict, Optional


def generate_signature(
    app_id: str,
    app_secret: str,
    request_path: str,
    method: str = "GET",
    timestamp: Optional[str] = None,
    nonce: Optional[str] = None,
    signature_method: str = "HmacSHA256"
) -> tuple[str, str, str]:
    """
    Calcula a assinatura criptográfica HMAC-SHA256 para autenticação na OpenAPI da APsystems.
    
    Regra da APsystems:
    RequestPath = Último segmento do path da URL (ex: 'details/AZ123' -> 'AZ123')
    stringToSign = X-CA-Timestamp + '/' + X-CA-Nonce + '/' + X-CA-AppId + '/' + RequestPath + '/' + HTTPMethod + '/' + X-CA-Signature-Method
    
    Retorna: (signature_base64, timestamp, nonce)
    """
    ts = timestamp or str(int(time.time() * 1000))
    nc = nonce or uuid.uuid4().hex
    
    # Extrai estritamente o último segmento se for fornecido um path composto
    clean_path = request_path.rstrip("/").split("/")[-1] if "/" in request_path else request_path
    
    string_to_sign = f"{ts}/{nc}/{app_id}/{clean_path}/{method.upper()}/{signature_method}"
    
    if signature_method == "HmacSHA256":
        digest = hmac.new(
            app_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256
        ).digest()
    elif signature_method == "HmacSHA1":
        digest = hmac.new(
            app_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1
        ).digest()
    else:
        raise ValueError(f"Método de assinatura não suportado: {signature_method}")

    signature = base64.b64encode(digest).decode("utf-8")
    return signature, ts, nc


def build_auth_headers(
    app_id: str,
    app_secret: str,
    request_path: str,
    method: str = "GET",
    timestamp: Optional[str] = None,
    nonce: Optional[str] = None
) -> Dict[str, str]:
    """
    Gera o dicionário completo de cabeçalhos HTTP exigidos pela APsystems.
    """
    signature, ts, nc = generate_signature(
        app_id=app_id,
        app_secret=app_secret,
        request_path=request_path,
        method=method,
        timestamp=timestamp,
        nonce=nonce,
        signature_method="HmacSHA256"
    )
    
    return {
        "X-CA-AppId": app_id,
        "X-CA-Timestamp": ts,
        "X-CA-Nonce": nc,
        "X-CA-Signature-Method": "HmacSHA256",
        "X-CA-Signature": signature,
        "Accept": "application/json",
        "User-Agent": "SolarHub-Client/0.1.0"
    }
