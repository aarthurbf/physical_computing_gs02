/*
  Totem Sereno v2 - Sereno SP (CitizenTech / Global Solution 2026)
  Physical Computing: IoT & IoB  |  ESP32 + DHT22 + LCD I2C + LEDs + buzzer + rele (nevoa) + HC-SR04 (agua)

  O que faz:
   1. Le temperatura e umidade (DHT22).
   2. Calcula o indice de calor (formula de Rothfusz / NOAA).
   3. Classifica: NORMAL (< 32 C), ATENCAO (32 a 40,9 C), PERIGO (>= 41 C).
   4. Avisa no local: LED verde/amarelo/vermelho, LCD e buzzer (bipe a cada 15 s em PERIGO).
   5. Botao 1 silencia o buzzer por 10 min.
   6. Botao 2 "Refrescar": aciona o jato de nevoa (rele + LED azul) por 8 s, com intervalo de 30 s
      e bloqueio se o reservatorio estiver vazio (HC-SR04). Cada acionamento e um evento
      ANONIMO de comportamento (IoB): contador usosRefugio no JSON.
   7. Envia JSON para a API .NET (POST /api/leituras, cabecalho X-Api-Key) a cada 60 s
      e a cada mudanca de nivel. Sem rede, guarda as ultimas 20 leituras e reenvia depois.

  Nenhum dado pessoal e coletado. O contador do botao 2 nao identifica ninguem.
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <time.h>
#include <math.h>

// Preencha API_URL (URL do tunel HTTPS) e API_KEY (mesma chave da API). Nao publique valores reais.
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";
const char* API_URL   = "https://SEU-TUNEL/api/leituras";
const char* API_KEY   = "SUA-CHAVE-DE-API";
const char* TOTEM_COD = "STN01";

const bool DEMO_MODE        = true;               // true: le e envia a cada 3 s; false: a cada 60 s
const bool SEND_ERROR_STATUS = false;             // enviar status de erro do sensor a API

const unsigned long READ_DEMO_MS   = 3000UL;      // taxa de leitura no modo demo
const unsigned long READ_REAL_MS   = 60000UL;
const unsigned long SEND_DEMO_MS   = 3000UL;      // taxa de envio no modo demo
const unsigned long SEND_REAL_MS   = 60000UL;
const unsigned long MIN_SEND_GAP   = 1500UL;      // intervalo minimo entre disparos por evento
const unsigned long BEEP_EVERY_MS  = 15000UL;
const unsigned long SILENCE_MS     = 10UL * 60UL * 1000UL;
const unsigned long WIFI_RETRY_MS  = 15000UL;
const unsigned long NEVOA_MS       = 8000UL;      // duracao do jato
const unsigned long NEVOA_COOLDOWN = 30000UL;     // intervalo entre jatos
const float AGUA_VAZIO_CM          = 20.0f;       // distancia sensor->agua acima disso = reservatorio vazio
const float HIST_C                 = 0.5f;        // histerese dos niveis

#define PIN_DHT     15
#define PIN_LED_G   25
#define PIN_LED_Y   26
#define PIN_LED_R   27
#define PIN_BUZZER  13
#define PIN_BTN_SIL 14   // silenciar
#define PIN_BTN_REF 12   // refrescar (aciona a nevoa)
#define PIN_RELE    32   // rele da bomba/valvula de nevoa
#define PIN_LED_B   33   // LED azul: nevoa ativa
#define PIN_TRIG    5    // HC-SR04: nivel do reservatorio
#define PIN_ECHO    18
// LCD I2C: SDA = 21, SCL = 22, endereco 0x27

DHT dht(PIN_DHT, DHT22);
LiquidCrystal_I2C lcd(0x27, 16, 2);

enum Nivel { NORMAL = 0, ATENCAO = 1, PERIGO = 2 };

struct Leitura {
  float temp;
  float umid;
  float indice;
  Nivel nivel;
  int   usos;
  bool  aguaOk;
  bool  nevoa;
  char  quando[32];
};

const int BUF_MAX = 20;
Leitura buf[BUF_MAX];
int bufCount = 0;          // quantas leituras pendentes
int bufHead  = 0;          // indice da mais antiga

Nivel nivelAtual = NORMAL;
Nivel nivelAnterior = NORMAL;
bool primeiraLeitura = true;
float ultTemp = NAN, ultUmid = NAN, ultIndice = NAN;
int  usosRefugio = 0;
bool sensorOk = true;
bool aguaOk = true;
bool nevoaAtiva = false;
unsigned long nevoaFim = 0, nevoaLivre = 0;
char msgTemp[17] = "";
unsigned long msgAte = 0;

unsigned long tLeitura = 0, tEnvio = 0, tBipe = 0, tWifi = 0, tUltimoEnvio = 0;
unsigned long silencioAte = 0;
bool silenciado = false;
bool enviarAgora = false;

bool apiConfigurada() {
  if (strlen(API_URL) == 0) return false;
  return strstr(API_URL, "SEU-TUNEL") == nullptr;
}

// Entrada e saida em graus Celsius. Formula de Rothfusz (NOAA) com ajustes.
float indiceDeCalorC(float tc, float rh) {
  float t = tc * 9.0f / 5.0f + 32.0f;                       // °F
  float hi = 0.5f * (t + 61.0f + ((t - 68.0f) * 1.2f) + (rh * 0.094f));  // formula simples
  if ((hi + t) / 2.0f >= 80.0f) {
    hi = -42.379f + 2.04901523f * t + 10.14333127f * rh
         - 0.22475541f * t * rh - 0.00683783f * t * t
         - 0.05481717f * rh * rh + 0.00122874f * t * t * rh
         + 0.00085282f * t * rh * rh - 0.00000199f * t * t * rh * rh;
    if (rh < 13.0f && t >= 80.0f && t <= 112.0f) {
      hi -= ((13.0f - rh) / 4.0f) * sqrtf((17.0f - fabsf(t - 95.0f)) / 17.0f);
    } else if (rh > 85.0f && t >= 80.0f && t <= 87.0f) {
      hi += ((rh - 85.0f) / 10.0f) * ((87.0f - t) / 5.0f);
    }
  }
  return (hi - 32.0f) * 5.0f / 9.0f;
}

// Histerese: sobe nos limites (32 / 41) e so desce 0,5 C abaixo, evitando LED piscando.
Nivel classificar(float ic, Nivel atual) {
  Nivel n = (ic >= 41.0f) ? PERIGO : (ic >= 32.0f) ? ATENCAO : NORMAL;
  if (n < atual) {
    float limite = (atual == PERIGO) ? 41.0f : 32.0f;
    if (ic > limite - HIST_C) n = atual;
  }
  return n;
}

const char* nomeNivel(Nivel n) {
  switch (n) {
    case PERIGO:  return "PERIGO";
    case ATENCAO: return "ATENCAO";
    default:      return "NORMAL";
  }
}

void horaIso(char* out, size_t n) {
  struct tm ti;
  if (getLocalTime(&ti, 50)) {
    strftime(out, n, "%Y-%m-%dT%H:%M:%S-03:00", &ti);
  } else {
    snprintf(out, n, "1970-01-01T00:00:00-03:00");   // sem NTP ainda
  }
}

void atualizarLeds(Nivel n) {
  digitalWrite(PIN_LED_G, n == NORMAL);
  digitalWrite(PIN_LED_Y, n == ATENCAO);
  digitalWrite(PIN_LED_R, n == PERIGO);
}

void mostrarLcd() {
  char l1[17], l2[17];
  bool temMsg = millis() < msgAte;
  if (!sensorOk) {
    snprintf(l1, sizeof(l1), "Sensor com falha");
    snprintf(l2, sizeof(l2), "Chame a prefeit.");
  } else {
    snprintf(l1, sizeof(l1), "T:%4.1fC U:%3.0f%%", ultTemp, ultUmid);
    const char* msg = (nivelAtual == PERIGO) ? "PERIGO" :
                      (nivelAtual == ATENCAO) ? "ATENCAO" : "OK";
    snprintf(l2, sizeof(l2), "IC:%4.1f %s", ultIndice, msg);
  }
  lcd.setCursor(0, 0); lcd.print("                ");
  lcd.setCursor(0, 0); lcd.print(l1);
  if (temMsg) snprintf(l2, sizeof(l2), "%-16s", msgTemp);
  lcd.setCursor(0, 1); lcd.print("                ");
  lcd.setCursor(0, 1); lcd.print(l2);
}

void tratarBuzzer() {
  unsigned long agora = millis();
  if (silenciado && (long)(agora - silencioAte) >= 0) {
    silenciado = false;
    Serial.println("[buzzer] silencio terminou");
  }
  if (sensorOk && nivelAtual == PERIGO && !silenciado && (agora - tBipe >= BEEP_EVERY_MS)) {
    tBipe = agora;
    tone(PIN_BUZZER, 1500, 300);
  }
}

void mensagem(const char* txt, unsigned long ms = 1500) {
  strncpy(msgTemp, txt, 16); msgTemp[16] = 0;
  msgAte = millis() + ms;
  mostrarLcd();
}

void lerAgua() {
  digitalWrite(PIN_TRIG, LOW); delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  long us = pulseIn(PIN_ECHO, HIGH, 30000);
  float cm = (us == 0) ? 999.0f : us / 58.0f;
  aguaOk = cm <= AGUA_VAZIO_CM;
}

void definirNevoa(bool on) {
  nevoaAtiva = on;
  digitalWrite(PIN_RELE, on);
  digitalWrite(PIN_LED_B, on);
}

void acionarNevoa() {
  unsigned long agora = millis();
  lerAgua();
  if (!aguaOk) { mensagem("Sem agua!"); Serial.println("[nevoa] bloqueada: reservatorio vazio"); return; }
  if (nevoaAtiva) return;
  if ((long)(agora - nevoaLivre) < 0) {
    char b[17]; snprintf(b, sizeof(b), "Aguarde %lus", (nevoaLivre - agora) / 1000 + 1);
    mensagem(b); return;
  }
  definirNevoa(true);
  nevoaFim = agora + NEVOA_MS;
  nevoaLivre = nevoaFim + NEVOA_COOLDOWN;
  usosRefugio++;                                     // evento anonimo de comportamento (IoB)
  enviarAgora = true;
  tone(PIN_BUZZER, 2000, 80);
  Serial.printf("[IoB] nevoa acionada (contador anonimo = %d)\n", usosRefugio);
  mensagem("Refresque-se!", NEVOA_MS);
}

void tratarNevoa() {
  if (nevoaAtiva && (long)(millis() - nevoaFim) >= 0) {
    definirNevoa(false);
    Serial.println("[nevoa] fim do jato");
    mostrarLcd();
  }
}

bool botaoPressionado(int pino, bool &anterior, unsigned long &tDebounce) {
  bool lido = (digitalRead(pino) == LOW);           // INPUT_PULLUP: pressionado = LOW
  bool evento = false;
  if (lido && !anterior && millis() - tDebounce > 200) {
    evento = true;
    tDebounce = millis();
  }
  anterior = lido;
  return evento;
}

void tratarBotoes() {
  static bool antSil = false, antRef = false;
  static unsigned long dbSil = 0, dbRef = 0;

  if (botaoPressionado(PIN_BTN_SIL, antSil, dbSil)) {
    silenciado = true;
    silencioAte = millis() + SILENCE_MS;
    noTone(PIN_BUZZER);
    Serial.println("[botao] buzzer silenciado por 10 min");
    mensagem("Som off 10 min");
  }
  if (botaoPressionado(PIN_BTN_REF, antRef, dbRef)) {
    acionarNevoa();
  }
}

void conectarWifi(bool bloquearNoSetup = false) {
  if (WiFi.status() == WL_CONNECTED) return;
  
  unsigned long agora = millis();
  if (!bloquearNoSetup && tWifi != 0 && (agora - tWifi < WIFI_RETRY_MS)) return;
  tWifi = agora;

  Serial.printf("[wifi] Conectando a '%s'...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);

  if (bloquearNoSetup) {
    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0 < 8000)) {
      delay(200);
      Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[wifi] Tentando conexao com scan automatico...");
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      t0 = millis();
      while (WiFi.status() != WL_CONNECTED && (millis() - t0 < 8000)) {
        delay(200);
        Serial.print(".");
      }
      Serial.println();
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.print("[wifi] CONECTADO COM SUCESSO! IP: ");
      Serial.println(WiFi.localIP());
      lcd.setCursor(0, 1);
      lcd.print("Wi-Fi OK        ");
    } else {
      Serial.printf("[wifi] Sem conexao (status=%d). Operando offline / serial.\n", WiFi.status());
      lcd.setCursor(0, 1);
      lcd.print("Wi-Fi OFF       ");
    }
  }
}

void diagnosticoRede() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[teste-internet] Pulado (Wi-Fi offline).");
    return;
  }
  
  HTTPClient http;
  http.setTimeout(4000);
  bool httpOk = false;
  
  if (http.begin("http://example.com")) {
    int code = http.GET();
    Serial.printf("[teste-internet] GET http://example.com -> %d %s\n", code, code > 0 ? "(Internet OK)" : "(Sem conexao)");
    httpOk = (code > 0);
    http.end();
  }

  struct tm ti;
  if (getLocalTime(&ti, 4000)) {
    char horaBuf[32];
    strftime(horaBuf, sizeof(horaBuf), "%Y-%m-%d %H:%M:%S", &ti);
    Serial.printf("[ntp] Hora sincronizada: %s (UTC-3)\n", horaBuf);
  } else {
    Serial.println("[ntp] Sem resposta do servidor NTP (usara data padrao)");
  }
}

void montarJson(const Leitura& l, char* out, size_t n) {
  snprintf(out, n,
    "{\"totemCodigo\":\"%s\",\"temperatura\":%.1f,\"umidade\":%.1f,"
    "\"indiceCalor\":%.1f,\"nivel\":\"%s\",\"usosRefugio\":%d,"
    "\"aguaOk\":%s,\"nevoaAtiva\":%s,\"coletadaEm\":\"%s\"}",
    TOTEM_COD, l.temp, l.umid, l.indice, nomeNivel(l.nivel), l.usos,
    l.aguaOk ? "true" : "false", l.nevoa ? "true" : "false", l.quando);
}

bool enviarLeitura(const Leitura& l) {
  char json[256];
  montarJson(l, json, sizeof(json));
  Serial.print("[json] ");
  Serial.println(json);                              // Sempre emitido na serial

  if (!apiConfigurada()) {
    Serial.println("[aviso-envio] API_URL nao configurada com URL real. Use ponte_serial.py ou configure o tunel.");
    return false;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[aviso-envio] Wi-Fi desconectado. Guardando leitura no buffer local.");
    return false;
  }

  HTTPClient http;
  http.setTimeout(5000);
  int code = -1;
  bool isHttps = (strncmp(API_URL, "https://", 8) == 0);

  if (isHttps) {
    WiFiClientSecure client;
    client.setInsecure();   // SOMENTE na simulacao: ignora checagem de certificado SSL
    if (http.begin(client, API_URL)) {
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Api-Key", API_KEY);
      code = http.POST((uint8_t*)json, strlen(json));
      http.end();
    }
  } else {
    WiFiClient client;
    if (http.begin(client, API_URL)) {
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Api-Key", API_KEY);
      code = http.POST((uint8_t*)json, strlen(json));
      http.end();
    }
  }

  if (code >= 200 && code < 300) {
    Serial.printf("[http] Enviado com sucesso! HTTP %d (T=%.1fC, U=%.1f%%, IC=%.1fC, Nivel=%s)\n",
                  code, l.temp, l.umid, l.indice, nomeNivel(l.nivel));
    return true;
  } else {
    Serial.printf("[http] Falha no POST -> HTTP %d (Verifique se o tunel e a API estao ativos)\n", code);
    return false;
  }
}

void guardarNoBuffer(const Leitura& l) {
  if (bufCount == BUF_MAX) {                         // cheio: descarta a mais antiga
    bufHead = (bufHead + 1) % BUF_MAX;
    bufCount--;
  }
  buf[(bufHead + bufCount) % BUF_MAX] = l;
  bufCount++;
  Serial.printf("[buffer] %d leitura(s) pendente(s)\n", bufCount);
}

void reenviarPendentes() {
  while (bufCount > 0 && WiFi.status() == WL_CONNECTED && apiConfigurada()) {
    if (!enviarLeitura(buf[bufHead])) break;         // falhou: tenta depois
    bufHead = (bufHead + 1) % BUF_MAX;
    bufCount--;
  }
}

void enviarOuGuardar(const Leitura& l) {
  reenviarPendentes();                               // primeiro as mais antigas
  if (bufCount == 0 && enviarLeitura(l)) return;
  guardarNoBuffer(l);
}

void lerSensor() {
  lerAgua();
  float t = dht.readTemperature();
  float h = dht.readHumidity();

  if (isnan(t) || isnan(h)) {
    sensorOk = false;
    Serial.println("[sensor] FALHA na leitura do DHT22");
    atualizarLeds(NORMAL);
    digitalWrite(PIN_LED_Y, HIGH);                   // amarelo fixo = atencao ao equipamento
    digitalWrite(PIN_LED_G, LOW);
    mostrarLcd();
    if (SEND_ERROR_STATUS) {
      char quando[32]; horaIso(quando, sizeof(quando));
      char json[200];
      snprintf(json, sizeof(json),
        "{\"totemCodigo\":\"%s\",\"status\":\"ERRO_SENSOR\",\"coletadaEm\":\"%s\"}", TOTEM_COD, quando);
      Serial.print("[json] "); Serial.println(json);
    }
    return;
  }

  sensorOk = true;
  ultTemp = t; ultUmid = h;
  ultIndice = indiceDeCalorC(t, h);
  nivelAnterior = nivelAtual;
  nivelAtual = classificar(ultIndice, nivelAnterior);

  Serial.printf("[leitura] T=%.1fC U=%.1f%% IC=%.1fC nivel=%s\n",
                ultTemp, ultUmid, ultIndice, nomeNivel(nivelAtual));

  atualizarLeds(nivelAtual);
  mostrarLcd();

  if (nivelAtual == PERIGO && nivelAnterior != PERIGO) {
    tBipe = millis() - BEEP_EVERY_MS;                // primeiro bipe imediato
  }

  static float ultTempEnviada = -999.0f, ultUmidEnviada = -999.0f;
  if (!primeiraLeitura) {
    if (nivelAtual != nivelAnterior || fabsf(t - ultTempEnviada) >= 0.3f || fabsf(h - ultUmidEnviada) >= 1.0f) {
      enviarAgora = true;
      ultTempEnviada = t;
      ultUmidEnviada = h;
    }
  } else {
    ultTempEnviada = t;
    ultUmidEnviada = h;
  }
  primeiraLeitura = false;
}

void enviarSePreciso() {
  unsigned long agora = millis();
  unsigned long intervaloEnvio = DEMO_MODE ? SEND_DEMO_MS : SEND_REAL_MS;
  bool porTempo = (agora - tEnvio >= intervaloEnvio);
  bool porEvento = enviarAgora && (agora - tUltimoEnvio >= MIN_SEND_GAP);

  if (!sensorOk || isnan(ultTemp)) return;
  if (!(porTempo || porEvento)) return;

  Leitura l;
  l.temp = ultTemp; l.umid = ultUmid; l.indice = ultIndice;
  l.nivel = nivelAtual; l.usos = usosRefugio;
  l.aguaOk = aguaOk; l.nevoa = nevoaAtiva;
  horaIso(l.quando, sizeof(l.quando));
  enviarOuGuardar(l);

  tEnvio = agora;
  tUltimoEnvio = agora;
  enviarAgora = false;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_Y, OUTPUT);
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_BTN_SIL, INPUT_PULLUP);
  pinMode(PIN_BTN_REF, INPUT_PULLUP);
  pinMode(PIN_RELE, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  definirNevoa(false);

  dht.begin();
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("Sereno SP");
  lcd.setCursor(0, 1); lcd.print("Totem STN01...");

  atualizarLeds(NORMAL); delay(250);
  atualizarLeds(ATENCAO); delay(250);
  atualizarLeds(PERIGO); delay(250);
  atualizarLeds(NORMAL);

  conectarWifi(true);
  configTime(-3 * 3600, 0, "pool.ntp.org", "time.google.com");   // America/Sao_Paulo (UTC-3)
  diagnosticoRede();

  Serial.println("=== Totem Sereno STN01 Iniciado ===");
  if (!apiConfigurada()) {
    Serial.println("[aviso] API_URL ainda contem 'SEU-TUNEL'.");
    Serial.println("   -> Para enviar direto do Wokwi: abra um tunel publico (cloudflared/ngrok/ssh) e cole a URL HTTPS em API_URL.");
    Serial.println("   -> Para enviar localmente sem tunel: execute 'python3 ponte_serial.py' e cole a saida [json].");
  } else {
    Serial.printf("Destino configurado: %s\n", API_URL);
  }
  delay(800);
  unsigned long intervaloEnvio = DEMO_MODE ? SEND_DEMO_MS : SEND_REAL_MS;
  tEnvio = millis() - intervaloEnvio;                // envia logo apos a primeira leitura
  lerSensor();
  tLeitura = millis();
}

void loop() {
  conectarWifi();
  tratarBotoes();
  tratarBuzzer();
  tratarNevoa();
  static bool msgAtiva = false;
  if (msgAtiva && millis() >= msgAte) { msgAtiva = false; mostrarLcd(); }
  if (millis() < msgAte) msgAtiva = true;

  unsigned long intervalo = DEMO_MODE ? READ_DEMO_MS : READ_REAL_MS;
  if (millis() - tLeitura >= intervalo) {
    tLeitura = millis();
    lerSensor();
  }
  enviarSePreciso();
  delay(20);
}
