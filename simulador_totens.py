#!/usr/bin/env python3
"""Simula os totens STN02..STN05 (o STN01 é o ESP32 do Wokwi) enviando leituras à API.

Uso:
  python3 simulador_totens.py --dry-run
  python3 simulador_totens.py --url https://.../api/leituras --key <API_KEY>

A chave é lida de --key ou da variável de ambiente API_KEY.
Os dados e as coordenadas são fictícios.
"""
import argparse, json, math, os, random, time, urllib.request
from datetime import datetime, timezone, timedelta

TOTENS = [
    ("STN02", "Terminal (sol direto)", -23.4985, -46.6250, +2.0, -5),
    ("STN03", "Praca arborizada",      -23.5010, -46.6290, -1.5, +5),
    ("STN04", "Ponto de onibus",       -23.4960, -46.6230, +1.0, 0),
    ("STN05", "Calcada comercial",     -23.5030, -46.6270, +1.5, -3),
]

def indice_calor_c(tc, rh):
    t = tc * 9 / 5 + 32
    hi = 0.5 * (t + 61 + (t - 68) * 1.2 + rh * 0.094)
    if (hi + t) / 2 >= 80:
        hi = (-42.379 + 2.04901523*t + 10.14333127*rh - 0.22475541*t*rh - 0.00683783*t*t
              - 0.05481717*rh*rh + 0.00122874*t*t*rh + 0.00085282*t*rh*rh - 0.00000199*t*t*rh*rh)
        if rh < 13 and 80 <= t <= 112: hi -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
        elif rh > 85 and 80 <= t <= 87: hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return (hi - 32) * 5 / 9

def nivel(ic): return "PERIGO" if ic >= 41 else "ATENCAO" if ic >= 32 else "NORMAL"

def base_clima(minuto):
    f = (math.sin(minuto / 6 - math.pi / 2) + 1) / 2
    return 29 + 9 * f, 70 - 25 * f

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/api/leituras", help="URL do endpoint /api/leituras")
    ap.add_argument("--key", default=os.getenv("API_KEY"), help="Chave X-Api-Key (padrão: variável API_KEY)")
    ap.add_argument("--intervalo", type=float, default=5); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ciclos", type=int, default=0, help="0 = infinito"); ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    if not a.dry_run and not a.key:
        ap.error("informe --key ou defina a variável de ambiente API_KEY")
    if a.seed is not None: random.seed(a.seed)
    usos = {c[0]: 0 for c in TOTENS}; n = 0
    tz = timezone(timedelta(hours=-3))
    while a.ciclos == 0 or n < a.ciclos:
        t0, u0 = base_clima(n)
        for cod, nome, lat, lng, dt, du in TOTENS:
            t = round(t0 + dt + random.uniform(-0.4, 0.4), 1)
            u = round(max(15, min(95, u0 + du + random.uniform(-2, 2))), 1)
            ic = round(indice_calor_c(t, u), 1)
            lv = nivel(ic)
            if lv != "NORMAL" and random.random() < 0.25: usos[cod] += 1
            body = {"totemCodigo": cod, "temperatura": t, "umidade": u, "indiceCalor": ic, "nivel": lv,
                    "usosRefugio": usos[cod], "aguaOk": random.random() > 0.03, "nevoaAtiva": False,
                    "coletadaEm": datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S-03:00")}
            js = json.dumps(body, separators=(",", ":"))
            if a.dry_run or not a.url:
                print(f"{nome:24s} {js}")
            else:
                req = urllib.request.Request(a.url, js.encode(), {"Content-Type": "application/json", "X-Api-Key": a.key})
                try: print(cod, urllib.request.urlopen(req, timeout=5).status)
                except Exception as e: print(cod, "falhou:", e)
        n += 1
        if a.ciclos == 0 or n < a.ciclos: time.sleep(a.intervalo)

if __name__ == "__main__":
    main()
