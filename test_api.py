"""Testes unitários e de integração para a API do Sereno SP."""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

TEST_KEY = "test-key"
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SERENO_DB_PATH"] = temp_db.name
os.environ["API_KEY"] = TEST_KEY

from api import app, init_db

init_db()
client = TestClient(app)

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "sereno-sp-api"

def test_post_leitura_unauthorized():
    payload = {
        "totemCodigo": "STN01",
        "temperatura": 25.0,
        "umidade": 60.0,
        "indiceCalor": 25.0,
        "nivel": "NORMAL",
        "usosRefugio": 0,
        "aguaOk": True,
        "nevoaAtiva": False
    }
    res = client.post("/api/leituras", json=payload)
    assert res.status_code == 401

    res = client.post("/api/leituras", json=payload, headers={"X-Api-Key": "chave-errada"})
    assert res.status_code == 401

def test_post_leitura_normal():
    payload = {
        "totemCodigo": "STN01",
        "temperatura": 24.5,
        "umidade": 60.0,
        "indiceCalor": 24.5,
        "nivel": "NORMAL",
        "usosRefugio": 0,
        "aguaOk": True,
        "nevoaAtiva": False,
        "coletadaEm": "2026-11-17T10:00:00-03:00"
    }
    res = client.post("/api/leituras", json=payload, headers={"X-Api-Key": TEST_KEY})
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "sucesso"
    assert data["alertaGerado"] is False

def test_post_leitura_perigo_cria_alerta():
    payload = {
        "totemCodigo": "STN01",
        "temperatura": 38.0,
        "umidade": 65.0,
        "indiceCalor": 53.2,
        "nivel": "PERIGO",
        "usosRefugio": 4,
        "aguaOk": True,
        "nevoaAtiva": True,
        "coletadaEm": "2026-11-17T14:30:00-03:00"
    }
    res = client.post("/api/leituras", json=payload, headers={"X-Api-Key": TEST_KEY})
    assert res.status_code == 201
    data = res.json()
    assert data["alertaGerado"] is True

    res_alertas = client.get("/api/alertas")
    assert res_alertas.status_code == 200
    alertas = res_alertas.json()
    assert len(alertas) >= 1
    assert alertas[0]["totemCodigo"] == "STN01"
    assert alertas[0]["nivel"] == "PERIGO"

def test_get_ultimas_leituras():
    payload2 = {
        "totemCodigo": "STN02",
        "temperatura": 32.0,
        "umidade": 50.0,
        "indiceCalor": 34.0,
        "nivel": "ATENCAO",
        "usosRefugio": 1,
        "aguaOk": True,
        "nevoaAtiva": False
    }
    client.post("/api/leituras", json=payload2, headers={"X-Api-Key": TEST_KEY})

    res = client.get("/api/leituras/ultimas")
    assert res.status_code == 200
    ultimas = res.json()
    assert len(ultimas) >= 2
    codigos = [item["totemCodigo"] for item in ultimas]
    assert "STN01" in codigos
    assert "STN02" in codigos

def test_get_historico_leituras():
    res = client.get("/api/leituras?limit=10")
    assert res.status_code == 200
    leituras = res.json()
    assert len(leituras) >= 2

    res_stn01 = client.get("/api/leituras?totem=STN01")
    assert res_stn01.status_code == 200
    assert all(item["totemCodigo"] == "STN01" for item in res_stn01.json())

def test_painel_endpoint():
    res = client.get("/painel")
    assert res.status_code == 200
    assert "Painel Sereno SP" in res.text

if __name__ == "__main__":
    pytest.main(["-v", __file__])
