#!/usr/bin/env python3
"""Lê as linhas [json] do monitor serial do Wokwi e envia à API com o cabeçalho X-Api-Key.

Uso:
  python3 ponte_serial.py              # cole as linhas da serial
  cat serial_log.txt | python3 ponte_serial.py
  python3 ponte_serial.py --teste      # envia uma leitura de teste

A chave é lida de --key ou da variável de ambiente API_KEY.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_API_URL = "http://localhost:8000/api/leituras"

def enviar_json(api_url: str, api_key: str, payload_str: str) -> bool:
    try:
        dados = json.loads(payload_str)
    except json.JSONDecodeError as e:
        print(f"JSON inválido: {e}")
        return False

    corpo = json.dumps(dados).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=corpo,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "User-Agent": "PonteSerial-SerenoSP/2.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp_body = resp.read().decode("utf-8")
            print(f"[{dados.get('totemCodigo', 'STN')}] HTTP {resp.status} -> {resp_body}")
            return True
    except urllib.error.HTTPError as e:
        print(f"Erro HTTP {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Falha de conexão com a API ({api_url}): {e}")
    return False

def extrair_json_da_linha(linha: str) -> str | None:
    linha = linha.strip()
    if not linha:
        return None
    if "[json]" in linha:
        linha = linha.split("[json]", 1)[1].strip()
    if linha.startswith("{") and linha.endswith("}"):
        return linha
    return None

def main():
    parser = argparse.ArgumentParser(description="Ponte Serial Wokwi -> API Sereno SP")
    parser.add_argument("--url", default=DEFAULT_API_URL, help="URL do endpoint de leituras da API")
    parser.add_argument("--key", default=os.getenv("API_KEY"), help="Chave X-Api-Key (padrão: variável API_KEY)")
    parser.add_argument("--teste", action="store_true", help="Envia um payload de teste e encerra")
    args = parser.parse_args()
    if not args.key:
        parser.error("informe --key ou defina a variável de ambiente API_KEY")

    if args.teste:
        print(f"Enviando leitura de teste para {args.url}...")
        teste_payload = (
            '{"totemCodigo":"STN01","temperatura":26.0,"umidade":55.0,'
            '"indiceCalor":26.2,"nivel":"NORMAL","usosRefugio":0,'
            '"aguaOk":true,"nevoaAtiva":false,"coletadaEm":"2026-11-17T12:00:00-03:00"}'
        )
        enviar_json(args.url, args.key, teste_payload)
        return

    print(f"Destino: {args.url}")
    print("Cole as linhas do Monitor Serial do Wokwi (ex: [json] {...}). Ctrl+C encerra.")

    try:
        for linha in sys.stdin:
            json_str = extrair_json_da_linha(linha)
            if json_str:
                enviar_json(args.url, args.key, json_str)
            else:
                if linha.strip():
                    print(f"Linha ignorada (sem JSON de totem): {linha.strip()[:60]}")
    except KeyboardInterrupt:
        print("\nPonte encerrada.")

if __name__ == "__main__":
    main()
