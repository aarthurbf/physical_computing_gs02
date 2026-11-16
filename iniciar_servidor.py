#!/usr/bin/env python3
"""Inicia a API FastAPI do Sereno SP e mostra como conectar o Wokwi."""

import os


def main():
    porta = int(os.getenv("PORT", "8000"))

    print(f"API Local:      http://localhost:{porta}")
    print(f"Swagger / Docs: http://localhost:{porta}/docs")
    print(f"Painel Web:     http://localhost:{porta}/painel")
    print("-" * 60)
    print("Para conectar o Wokwi, abra um túnel público:")
    print(f"  cloudflared tunnel --url http://localhost:{porta}")
    print(f"  ngrok http {porta}")
    print(f"  ssh -R 80:localhost:{porta} nokey@localhost.run")
    print("Depois configure API_URL e API_KEY em sketch.ino.")
    print("Ou use a ponte manual: python3 ponte_serial.py")
    print("-" * 60)

    try:
        import uvicorn
        uvicorn.run("api:app", host="0.0.0.0", port=porta, reload=True)
    except KeyboardInterrupt:
        print("\nServidor encerrado.")


if __name__ == "__main__":
    main()
