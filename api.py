"""API REST do Sereno SP: recebe leituras dos totens, grava em SQLite e gera alertas de calor extremo."""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

load_dotenv()

DB_PATH = os.getenv("SERENO_DB_PATH", "sereno.db")
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("Defina a variável de ambiente API_KEY (veja .env.example)")
TZ_SP = timezone(timedelta(hours=-3))

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leituras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                totem_codigo TEXT NOT NULL,
                temperatura REAL NOT NULL,
                umidade REAL NOT NULL,
                indice_calor REAL NOT NULL,
                nivel TEXT NOT NULL,
                usos_refugio INTEGER DEFAULT 0,
                agua_ok INTEGER DEFAULT 1,
                nevoa_ativa INTEGER DEFAULT 0,
                coletada_em TEXT NOT NULL,
                recebido_em TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_leituras_totem ON leituras(totem_codigo, recebido_em);
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                totem_codigo TEXT NOT NULL,
                nivel TEXT NOT NULL,
                indice_calor REAL NOT NULL,
                temperatura REAL NOT NULL,
                umidade REAL NOT NULL,
                mensagem TEXT NOT NULL,
                criado_em TEXT NOT NULL
            );
        """)
        conn.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="Sereno SP - API de Telemetria e Totens",
    description="API para recepção de leituras IoT/IoB dos Totens Sereno e monitoramento do calor extremo em Santana, SP.",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LeituraPayload(BaseModel):
    totemCodigo: str = Field(..., examples=["STN01"], description="Código identificador do totem")
    temperatura: float = Field(..., examples=[37.0], description="Temperatura em °C")
    umidade: float = Field(..., examples=[60.0], description="Umidade relativa do ar em %")
    indiceCalor: float = Field(..., examples=[51.4], description="Índice de calor calculado em °C")
    nivel: str = Field(..., examples=["PERIGO"], description="Classificação: NORMAL, ATENCAO ou PERIGO")
    usosRefugio: int = Field(0, examples=[3], description="Contador de acionamentos do botão de refresco (IoB)")
    aguaOk: bool = Field(True, examples=[True], description="Status do reservatório de água do totem")
    nevoaAtiva: bool = Field(False, examples=[False], description="Status do relé/jato de névoa")
    coletadaEm: Optional[str] = Field(None, examples=["2026-11-17T13:05:00-03:00"], description="Data/hora ISO-8601 da leitura")

class LeituraResponse(BaseModel):
    totemCodigo: str
    temperatura: float
    umidade: float
    indiceCalor: float
    nivel: str
    usosRefugio: int
    aguaOk: bool
    nevoaAtiva: bool
    coletadaEm: str
    recebidoEm: Optional[str] = None

class AlertaResponse(BaseModel):
    id: int
    totemCodigo: str
    nivel: str
    indiceCalor: float
    temperatura: float
    umidade: float
    mensagem: str
    criadoEm: str

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html>
        <head><title>Sereno SP API</title></head>
        <body style="font-family: system-ui, sans-serif; padding: 2rem; max-width: 800px; margin: 0 auto; line-height: 1.5;">
            <h1>Sereno SP - API de Totens IoT & IoB</h1>
            <p>API ativa e pronta para receber telemetria do ESP32 Wokwi e alimentar o painel gerencial.</p>
            <ul>
                <li><a href="/docs">Documentação Interativa (Swagger / OpenAPI)</a></li>
                <li><a href="/painel">Abrir Painel Gerencial</a></li>
                <li><a href="/api/leituras/ultimas">Últimas Leituras (/api/leituras/ultimas)</a></li>
                <li><a href="/api/alertas">Alertas Gerados (/api/alertas)</a></li>
            </ul>
        </body>
    </html>
    """

@app.get("/health")
def health():
    return {"status": "ok", "service": "sereno-sp-api", "timestamp": datetime.now(TZ_SP).isoformat()}

@app.get("/painel")
def servir_painel():
    if os.path.exists("painel.html"):
        return FileResponse("painel.html")
    raise HTTPException(status_code=404, detail="Arquivo painel.html não encontrado")

@app.post("/api/leituras", status_code=status.HTTP_201_CREATED)
def receber_leitura(
    payload: LeituraPayload,
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key")
):
    """Recebe leitura de telemetria enviada pelo Totem ESP32 ou simulador."""
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API inválida ou ausente no cabeçalho X-Api-Key"
        )

    agora_iso = datetime.now(TZ_SP).strftime("%Y-%m-%dT%H:%M:%S-03:00")
    data_coleta = payload.coletadaEm or agora_iso
    nivel_normalizado = payload.nivel.upper().replace("Ç", "C").replace("Ã", "A")

    alerta_gerado = False

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO leituras (
                totem_codigo, temperatura, umidade, indice_calor, nivel,
                usos_refugio, agua_ok, nevoa_ativa, coletada_em, recebido_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.totemCodigo,
            payload.temperatura,
            payload.umidade,
            payload.indiceCalor,
            nivel_normalizado,
            payload.usosRefugio,
            1 if payload.aguaOk else 0,
            1 if payload.nevoaAtiva else 0,
            data_coleta,
            agora_iso
        ))

        if nivel_normalizado == "PERIGO":
            alerta_gerado = True
            msg = f"Calor extremo detectado no totem {payload.totemCodigo}: {payload.temperatura:.1f}°C, índice de calor {payload.indiceCalor:.1f}°C."
            cursor.execute("""
                INSERT INTO alertas (
                    totem_codigo, nivel, indice_calor, temperatura, umidade, mensagem, criado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                payload.totemCodigo,
                nivel_normalizado,
                payload.indiceCalor,
                payload.temperatura,
                payload.umidade,
                msg,
                agora_iso
            ))

        conn.commit()

    return {
        "status": "sucesso",
        "totemCodigo": payload.totemCodigo,
        "nivel": nivel_normalizado,
        "alertaGerado": alerta_gerado,
        "recebidoEm": agora_iso
    }

@app.get("/api/leituras/ultimas", response_model=List[LeituraResponse])
def obter_ultimas_leituras():
    """Retorna a última leitura de cada totem cadastrado/ativo no sistema."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.totem_codigo, l.temperatura, l.umidade, l.indice_calor, l.nivel,
                   l.usos_refugio, l.agua_ok, l.nevoa_ativa, l.coletada_em, l.recebido_em
            FROM leituras l
            INNER JOIN (
                SELECT totem_codigo, MAX(id) as max_id
                FROM leituras
                GROUP BY totem_codigo
            ) ult ON l.id = ult.max_id
            ORDER BY l.totem_codigo ASC;
        """)
        rows = cursor.fetchall()

    return [
        LeituraResponse(
            totemCodigo=row["totem_codigo"],
            temperatura=row["temperatura"],
            umidade=row["umidade"],
            indiceCalor=row["indice_calor"],
            nivel=row["nivel"],
            usosRefugio=row["usos_refugio"],
            aguaOk=bool(row["agua_ok"]),
            nevoaAtiva=bool(row["nevoa_ativa"]),
            coletadaEm=row["coletada_em"],
            recebidoEm=row["recebido_em"]
        )
        for row in rows
    ]

@app.get("/api/leituras", response_model=List[LeituraResponse])
def listar_historico_leituras(
    totem: Optional[str] = Query(None, description="Filtrar por código do totem"),
    limit: int = Query(50, ge=1, le=500, description="Quantidade máxima de leituras")
):
    """Lista histórico recente de leituras para auditoria ou gráficos."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if totem:
            cursor.execute("""
                SELECT totem_codigo, temperatura, umidade, indice_calor, nivel,
                       usos_refugio, agua_ok, nevoa_ativa, coletada_em, recebido_em
                FROM leituras
                WHERE totem_codigo = ?
                ORDER BY id DESC
                LIMIT ?
            """, (totem, limit))
        else:
            cursor.execute("""
                SELECT totem_codigo, temperatura, umidade, indice_calor, nivel,
                       usos_refugio, agua_ok, nevoa_ativa, coletada_em, recebido_em
                FROM leituras
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        rows = cursor.fetchall()

    return [
        LeituraResponse(
            totemCodigo=row["totem_codigo"],
            temperatura=row["temperatura"],
            umidade=row["umidade"],
            indiceCalor=row["indice_calor"],
            nivel=row["nivel"],
            usosRefugio=row["usos_refugio"],
            aguaOk=bool(row["agua_ok"]),
            nevoaAtiva=bool(row["nevoa_ativa"]),
            coletadaEm=row["coletada_em"],
            recebidoEm=row["recebido_em"]
        )
        for row in rows
    ]

@app.get("/api/alertas", response_model=List[AlertaResponse])
def listar_alertas(limit: int = Query(20, ge=1, le=100)):
    """Lista os últimos alertas de calor extremo registrados no sistema."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, totem_codigo, nivel, indice_calor, temperatura, umidade, mensagem, criado_em
            FROM alertas
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()

    return [
        AlertaResponse(
            id=row["id"],
            totemCodigo=row["totem_codigo"],
            nivel=row["nivel"],
            indiceCalor=row["indice_calor"],
            temperatura=row["temperatura"],
            umidade=row["umidade"],
            mensagem=row["mensagem"],
            criadoEm=row["criado_em"]
        )
        for row in rows
    ]

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
