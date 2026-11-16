# Totem Sereno v2 — Physical Computing: IoT & IoB

- **Projeto:** Sereno SP (CitizenTech, Global Solution 2026)
- **Disciplina:** Physical Computing: IoT & IoB
- **Plataforma:** ESP32 DevKit no Wokwi
- **Link do projeto no Wokwi:** `https://wokwi.com/projects/480878956079749121`
- **Vídeo (até 4 min):** `https://youtu.be/EZkdQrkYYCs`

| Integrantes | RM |
|---|---|
| Arthur Bobadilla Franchi | RM555056 |
| Luan Orlandelli Ramos | RM554747 |
| Jorge Luis | RM554418 | 

## 1. O problema e o papel do circuito

O Sereno SP protege idosos (60+) e trabalhadores de rua de Santana (zona norte de São Paulo) do calor extremo. Eles não sabem com antecedência quando o risco sobe nem onde há sombra e água por perto.

O projeto tem três camadas:

| Camada | Pergunta que responde | Quem faz |
|---|---|---|
| Previsão | "Amanhã será perigoso?" | Modelo de ML (dados INMET A701) |
| **Medição local** | **"Quão perigoso está AGORA na minha praça?"** | **Totem Sereno (este circuito)** |
| Ação | "Onde me refresco?" | API + app (pontos de refresco) |

O totem é o "termômetro de praça". A estação do INMET fica no Mirante de Santana e não mostra o que acontece em uma praça com asfalto e pouca sombra. O totem mede a grandeza exata do problema (temperatura e umidade, ou seja, o **índice de calor**) no ponto onde a pessoa está e avisa **ali mesmo**, sem celular e sem internet. Isso atende quem não usa app.

### Inspiração: ponto de refresco com névoa

Cidades europeias usam colunas que lançam um jato de vapor de água fria no verão. O Totem Sereno segue essa ideia: **mede o calor local, avisa e deixa a pessoa se refrescar com um toque**. O jato é simulado com relé + LED azul.

## 2. Como o circuito se integra à solução (não é um projeto paralelo)

```
Totem ESP32 ──POST /api/leituras (JSON + X-Api-Key)──► API FastAPI ──► SQLite (sereno.db)
                                                         │
                                  gera Alerta se nível = PERIGO
                                                         │
                                                         ▼
                                        Painel Web / App (tempo real + mapa + ML)
```

- A leitura enviada pelo totem é a **mesma** que aparece no app (jornada de Dona Lúcia, passo 2 e 3 da Ficha).
- A API grava a leitura (`LeituraSensor`) e cria um `Alerta` quando o nível é `PERIGO` (feature F05 e casos de teste TC01 a TC03 do Azure Boards).
- O módulo Sereno Guard (Cybersecurity) audita o payload do totem. Por isso o JSON não leva nenhum dado pessoal.
- Os casos de teste do totem estão cobertos pela feature F05 e pela F01 (leitura atual no app).

## 3. Componentes e ligações

| Componente (Wokwi) | Pino do ESP32 | Função |
|---|---|---|
| DHT22 | Dados → GPIO15; VCC → 3V3; GND | Temperatura e umidade (ajustáveis no simulador) |
| LCD 16x2 I2C (0x27) | SDA → GPIO21; SCL → GPIO22; VCC → VIN (5 V); GND | Temperatura, índice de calor e mensagem curta |
| LED verde + 220 Ω | GPIO25 | Nível NORMAL |
| LED amarelo + 220 Ω | GPIO26 | Nível ATENÇÃO |
| LED vermelho + 220 Ω | GPIO27 | Nível PERIGO |
| Buzzer | GPIO13 | Aviso sonoro em PERIGO |
| Botão 1 (amarelo) | GPIO14 (INPUT_PULLUP) | Silencia o buzzer por 10 min |
| Botão 2 (azul, "Refrescar") | GPIO12 (INPUT_PULLUP) | Aciona a névoa por 8 s (intervalo de 30 s) e gera evento IoB |
| Módulo relé | IN → GPIO32; VCC → VIN; GND | Comanda a bomba/válvula de névoa (simulada) |
| LED azul + 220 Ω | GPIO33 | Névoa ativa |
| HC-SR04 | TRIG → GPIO5; ECHO → GPIO18; VCC → VIN; GND | Nível do reservatório (distância > 20 cm = vazio: bloqueia a névoa e mostra "Sem agua!") |

Arquivos: `sketch.ino`, `diagram.json`, `libraries.txt`.

## 4. Lógica do firmware

1. Lê o DHT22 a cada 5 s na demonstração (`DEMO_MODE = true`) e a cada 60 s em uso real.
2. Se a leitura falhar, o LCD mostra "Sensor com falha" e o LED amarelo fica fixo. Nada é enviado à API.
3. Calcula o **índice de calor** pela fórmula de Rothfusz (NOAA), com conversão °C ↔ °F e os ajustes padrão para umidade baixa e alta.
4. Classifica o nível (faixas recomendadas pela equipe, inspiradas no serviço meteorológico dos EUA):

   | Nível | Índice de calor | LED | Buzzer |
   |---|---|---|---|
   | NORMAL | abaixo de 32 °C | verde | — |
   | ATENÇÃO | 32 a 40,9 °C | amarelo | — |
   | PERIGO | 41 °C ou mais | vermelho | bipe curto a cada 15 s, salvo se silenciado |

5. Conecta ao Wi-Fi `Wokwi-GUEST`, obtém a hora por NTP (fuso −03:00) e envia um POST JSON a cada 60 s **e a cada mudança de nível**.
6. Sem rede (ou com a API fora do ar), guarda as últimas 20 leituras e reenvia as mais antigas primeiro quando a conexão volta.

### Contrato JSON enviado à API

```json
{"totemCodigo":"STN01","temperatura":37.0,"umidade":60.0,"indiceCalor":51.4,"nivel":"PERIGO","usosRefugio":3,"aguaOk":true,"nevoaAtiva":false,"coletadaEm":"2026-11-17T13:05:00-03:00"}
```

Os campos `aguaOk` e `nevoaAtiva` são novos: **combinar com o P1** antes de entregar.

Cabeçalho: `X-Api-Key: <chave de teste>` · Valores de `nivel`: `NORMAL`, `ATENCAO`, `PERIGO` (sem acento).

## 5. Componente IoB (Internet of Behaviors)

O **botão 2, "Me refresquei aqui"**, registra um comportamento protetivo no próprio ponto público:

- Cada acionamento da névoa incrementa um **contador anônimo** (`usosRefugio`) enviado junto com a leitura.
- Nenhuma pessoa é identificada: não há nome, ID, foto nem localização individual.
- O dado alimenta o indicador do piloto do projeto: *quantas pessoas realmente usam o ponto de refresco quando o nível sobe*. Com isso, a prefeitura ou a equipe vê onde vale instalar mais sombra e água.
- O botão 1 (silenciar) também é uma interação comportamental: a pessoa decide se quer o som, e o totem respeita por 10 min.

## 6. Cenários de demonstração (valores calculados e conferidos)

No Wokwi, clique no DHT22 e altere temperatura e umidade durante a simulação.

| Cenário | Temp. | Umid. | Índice de calor | Nível | O que se vê |
|---|---|---|---|---|---|
| Manhã amena | 24 °C | 60% | 24,0 °C | NORMAL | LED verde |
| Tarde quente | 33 °C | 50% | 36,3 °C | ATENÇÃO | LED amarelo |
| Onda de calor | 37 °C | 60% | 51,4 °C | PERIGO | LED vermelho + buzzer |
| Silenciar | — | — | — | PERIGO | Botão 1: buzzer para por 10 min |
| Refrescar | — | — | — | — | Botão 2: relé e LED azul ligam por 8 s, LCD "Refresque-se!", contador sobe |
| Reservatório vazio | — | — | — | — | Ajuste o HC-SR04 para mais de 20 cm e aperte Refrescar: "Sem agua!" |
| Falha do sensor | — | — | — | — | Desconecte o fio de dados do DHT22: LCD "Sensor com falha" |

Obs.: o exemplo de JSON do documento de proposta (36,8 °C e 60% → 46,1 °C) não bate com a fórmula de Rothfusz, que dá ≈ 50,8 °C. O firmware usa o valor calculado.

## 6.1 Vários totens e painel gerencial

O Wokwi simula um ESP32 por projeto. A rede de totens é montada assim:

- **STN01:** o ESP32 real do Wokwi (este projeto).
- **STN02 a STN05:** `simulador_totens.py` envia, com o **mesmo contrato JSON**, leituras **simuladas** de 4 pontos fictícios de Santana (sol direto, praça arborizada, ponto de ônibus, calçada comercial), seguindo uma curva de calor ao longo do dia.
- O painel (P1/app) lê todos pela API, mostra o mapa com a cor do nível e calcula a média/previsão (ML). Isso fica com os integrantes responsáveis por essas disciplinas.

```bash
# Enviar leituras para a API local (padrão http://localhost:8000/api/leituras)
python3 simulador_totens.py

# Apenas imprimir no terminal (sem enviar)
python3 simulador_totens.py --dry-run

# Enviar para uma URL específica de túnel
python3 simulador_totens.py --url https://SEU-TUNEL/api/leituras --key $API_KEY
```

Declarar na apresentação: **só o STN01 roda no ESP32 simulado; STN02 a STN05 e as coordenadas são dados fictícios.**

## 7. Conexão do Wokwi com a internet e com a API

Conforme a [documentação do Wokwi](https://docs.wokwi.com/guides/esp32-wifi):

- O Wokwi oferece a rede aberta **`Wokwi-GUEST`** (sem senha, canal 6). O firmware usa `WiFi.begin("Wokwi-GUEST", "", 6)`: informar o canal evita o scan e economiza cerca de 4 s.
- O ESP32 recebe IP `10.10.0.2` e sai para a internet pelo **Public Gateway**, que funciona por padrão. Ele **só alcança serviços públicos**. Não alcança `localhost`, a VM da equipe nem a rede local. Isso só existe no **Private Gateway** (Wokwi Club, pago) com o host `host.wokwi.internal`.
- Ping (ICMP) não funciona na simulação. Para testar a internet, o firmware faz um `GET http://example.com`.
- O tráfego do Public Gateway é monitorado: não envie dados reais ou sensíveis.

**Teste de conexão (monitor serial):**

| Mensagem | Significado |
|---|---|
| `[wifi] CONECTADO. IP: 10.10.0.2` | Wi-Fi do simulador OK |
| `[teste-internet] GET http://example.com -> 200 (internet OK)` | Internet OK |
| `[ntp] hora sincronizada` | NTP OK (o JSON sai com a data real) |
| `[wifi] sem conexao` | Veja a tabela de problemas abaixo |
| `[aviso] API_URL nao configurada` | Wi-Fi pode estar OK, mas **nada é enviado**: falta o túnel (isso não é falha de internet) |

**Como a leitura chega à API da VM (em ordem de preferência):**

1. **Túnel HTTPS público** (cloudflared/ngrok) para a API. Cole a URL em `API_URL`. Um túnel é público, então a chave `X-Api-Key` e o CORS ficam por conta do grupo.
2. **Private Gateway** (se alguém tiver plano pago): use `http://host.wokwi.internal:PORTA/api/leituras`.
3. **Ponte manual:** o totem imprime `[json] ...` na serial e um script envia as mesmas leituras. Declarar no vídeo.

**Problemas comuns**

| Sintoma | Causa provável | Solução |
|---|---|---|
| Não conecta ao Wi-Fi | Placa sem Wi-Fi (só o ESP32 tem) ou SSID digitado errado | Use `esp32-devkit-v1` e `Wokwi-GUEST` sem senha |
| Wi-Fi OK, mas nada chega à API | `API_URL` ainda é `SEU-TUNEL`, ou aponta para `localhost`/IP da VM | Use túnel público |
| `[http] POST -> -1` | Túnel fora do ar, URL errada ou timeout | Teste a URL no navegador e no Swagger |
| `[http] POST -> 401` | Chave `X-Api-Key` diferente da API | Alinhar com o `.env` da API |
| JSON com data 1970 | NTP sem resposta | Aguarde ou reinicie a simulação |
| Wokwi lento ao conectar | Scan de canais | Já resolvido com o canal 6 |

Segurança: o firmware usa `setInsecure()` (não valida o certificado do túnel) **somente na simulação**. Nenhuma chave real deve ser versionada: use `.env` (ignorado pelo git) e substitua `API_KEY` no `sketch.ino` apenas localmente.

## 8. Dados e privacidade

- Não há dados pessoais no totem: apenas temperatura, umidade, índice de calor, nível, contador anônimo e horário.
- Todos os valores do vídeo são **simulados** no Wokwi (sensor e rede). Nada foi medido em campo.

## 9. ODS

- **ODS 3:** alerta local reduz a exposição de idosos ao calor perigoso.
- **ODS 10:** funciona sem celular nem internet para quem tem menos meios de se proteger.
- **ODS 11:** transforma uma praça em ponto de informação e refúgio.
- **ODS 13:** gera dados locais de calor para adaptação climática.

## 10. Como executar o projeto completo

### Passo 1: Instalar as dependências da API

```bash
pip install -r requirements.txt
```

### Passo 2: Configurar a chave e iniciar a API Backend e o Painel

Copie `.env.example` para `.env` e defina `API_KEY` (a API não inicia sem ela). Use o mesmo valor em `API_KEY` do `sketch.ino` e em `--key` (ou na variável `API_KEY`) de `ponte_serial.py` e `simulador_totens.py`.

```bash
cp .env.example .env
```

```bash
python3 iniciar_servidor.py
```
O servidor iniciará em `http://localhost:8000`.
- **Painel Gerencial:** `http://localhost:8000/painel`
- **Swagger / OpenAPI:** `http://localhost:8000/docs`
- **Healthcheck:** `http://localhost:8000/health`

### Passo 3: Conectar o ESP32 do Wokwi à API

Escolha uma das duas opções:

#### Opção A — Via Túnel Público HTTPS (Recomendado para simulação 100% online)
Como o Public Gateway do Wokwi não acessa `localhost` diretamente, abra um túnel público para a porta 8000:
- **Cloudflare Tunnel (grátis, sem cadastro):**
  ```bash
  cloudflared tunnel --url http://localhost:8000
  ```
- **SSH localhost.run (sem instalar nada):**
  ```bash
  ssh -R 80:localhost:8000 nokey@localhost.run
  ```
- **Ngrok:**
  ```bash
  ngrok http 8000
  ```
Copie a URL HTTPS gerada (ex: `https://exemplo.trycloudflare.com`) e cole em `sketch.ino`:
```cpp
const char* API_URL = "https://exemplo.trycloudflare.com/api/leituras";
```
Inicie a simulação no Wokwi. As leituras do **STN01** chegarão automaticamente à API e aparecerão no painel!

#### Opção B — Via Ponte Serial (Sem precisar de túnel)
1. Deixe a URL padrão no `sketch.ino` (o firmware imprimirá `[json] {...}` no Serial Monitor).
2. Execute a ponte serial em outro terminal:
   ```bash
   python3 ponte_serial.py
   ```
3. Copie as linhas do Monitor Serial do Wokwi e cole no terminal da ponte (ou canalize via pipe). A ponte enviará via HTTP para `http://localhost:8000/api/leituras`.

### Passo 4: Simular a rede completa de totens (STN02 a STN05)

Em outro terminal, inicie o gerador de telemetria dos demais pontos de Santana:
```bash
python3 simulador_totens.py
```

### Passo 5: Acompanhar no Painel Gerencial

Abra `http://localhost:8000/painel` (ou abra [`painel.html`](painel.html) no navegador) e selecione o botão **"API real"**. Você verá todos os totens (STN01 do Wokwi + STN02..STN05), seus níveis no mapa de Santana, indicadores de refúgio e o gráfico preditivo de ML!

### Executar Testes Automatizados da API

```bash
pytest test_api.py -v
```

## 11. Limitações e próximos passos

- Simulação: o DHT22 do Wokwi não sofre o efeito de sol direto nem de superfície quente; em campo é preciso abrigo ventilado.
- O contrato da API ainda não prevê status de erro do sensor (`SEND_ERROR_STATUS = false` por isso).
- Próximos passos: mais totens em praças e pontos de ônibus, alimentação solar, comunicação LoRa onde não há Wi-Fi.

## 12. Uso de IA

O uso de IA na geração do firmware e deste README está registrado em `prompts.md` na raiz do repositório. Todos os integrantes devem conseguir explicar cada linha do código.
