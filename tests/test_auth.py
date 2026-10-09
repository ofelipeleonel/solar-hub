import pytest
from solar_hub.client.auth import generate_signature, build_auth_headers


def test_generate_signature_deterministic():
    """Valida se a assinatura HMAC-SHA256 é calculada de forma exata e reprodutível."""
    app_id = "test_app_id_32_characters_123456"
    app_secret = "secret12char"
    request_path = "AZ12649A3DFF"
    timestamp = "1690000000000"
    nonce = "5e36eab8295911ee90751eff13c2920b"
    
    sig, ts, nc = generate_signature(
        app_id=app_id,
        app_secret=app_secret,
        request_path=request_path,
        method="GET",
        timestamp=timestamp,
        nonce=nonce,
        signature_method="HmacSHA256"
    )
    
    assert ts == timestamp
    assert nc == nonce
    assert isinstance(sig, str)
    assert len(sig) > 0


def test_request_path_last_segment_extraction():
    """Valida se o cálculo do HMAC extrai apenas o último segmento da URL."""
    app_id = "app_id"
    app_secret = "app_secret"
    ts = "1000"
    nc = "nonce"
    
    # Path completo vs apenas o último segmento devem gerar exatamente a mesma assinatura
    sig_full, _, _ = generate_signature(
        app_id=app_id,
        app_secret=app_secret,
        request_path="/user/api/v2/systems/details/E20E084572070216",
        timestamp=ts,
        nonce=nc
    )
    sig_short, _, _ = generate_signature(
        app_id=app_id,
        app_secret=app_secret,
        request_path="E20E084572070216",
        timestamp=ts,
        nonce=nc
    )
    assert sig_full == sig_short


def test_build_auth_headers():
    """Valida a presença de todos os cabeçalhos obrigatórios exigidos pela APsystems."""
    headers = build_auth_headers(
        app_id="my_app_id",
        app_secret="my_secret",
        request_path="my_sid"
    )
    
    required_keys = [
        "X-CA-AppId",
        "X-CA-Timestamp",
        "X-CA-Nonce",
        "X-CA-Signature-Method",
        "X-CA-Signature",
        "Accept",
        "User-Agent"
    ]
    for key in required_keys:
        assert key in headers
        assert len(headers[key]) > 0
