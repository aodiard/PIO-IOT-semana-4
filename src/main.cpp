#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <DHT.h>

// --- Credenciales y Endpoints de Firebase ---
const char *ssid = "Wokwi-GUEST";
const char *password = "";

const String RTDB_URL = "Completar con la URL de su proyecto";
const String TELEMETRIA_PATH = RTDB_URL + "/nodos/nodo_01/telemetria.json";
const String CONTROL_PATH = RTDB_URL + "/nodos/nodo_01/control/rele_estado.json";
const String ACK_PATH = RTDB_URL + "/nodos/nodo_01/telemetria/rele_confirmado.json";

// --- Asignación de Hardware ---
#define DHTPIN 4
#define DHTTYPE DHT22
#define RELAY_PIN 2

DHT dht(DHTPIN, DHTTYPE);

// --- Temporizadores No Bloqueantes (millis) ---
unsigned long lastTelemetryTime = 0;
const unsigned long telemetryInterval = 5000; // Enviar telemetría cada 5 segundos

unsigned long lastPollControl = 0;
const unsigned long pollInterval = 1000; // Consultar orden web cada 1 segundo

bool lastKnownState = false;

// Tarea 1: Envío de Telemetría Ambiental (Edge ➔ Cloud)
void enviarTelemetria()
{
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  if (isnan(h) || isnan(t))
  {
    Serial.println("[ERROR] Falla en la lectura del sensor DHT22.");
    return;
  }

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient https;

  if (https.begin(client, TELEMETRIA_PATH))
  {
    https.addHeader("Content-Type", "application/json");

    // Ensamblado del JSON de métricas
    String payload = "{\"temperatura\":" + String(t, 1) +
                     ",\"humedad\":" + String(h, 1) +
                     ",\"dispositivo_id\":\"esp32_nodo_01\"}";

    int httpCode = https.PATCH(payload);
    if (httpCode > 0)
    {
      Serial.printf("[TELEMETRÍA] Enviada: %.1f °C | %.1f %%\n", t, h);
    }
    else
    {
      Serial.printf("[HTTP ERROR] Falló PATCH telemetría: %s\n", https.errorToString(httpCode).c_str());
    }
    https.end();
  }
}

// Tarea 2: Consulta de Consignas y Confirmación Acknowledge (Cloud ➔ Edge ➔ Cloud)
void revisarControl()
{
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient https;

  if (https.begin(client, CONTROL_PATH))
  {
    int httpCode = https.GET();
    if (httpCode == 200)
    {
      String res = https.getString();
      bool ordenEncendido = (res == "true");

      // Se ejecuta solo cuando el usuario cambia el estado en la web
      if (ordenEncendido != lastKnownState)
      {
        lastKnownState = ordenEncendido;
        digitalWrite(RELAY_PIN, ordenEncendido ? HIGH : LOW);
        Serial.printf("[CONTROL] Actuador GPIO 2 conmutado a: %s\n", ordenEncendido ? "HIGH (ENCENDIDO)" : "LOW (APAGADO)");

        // Principio de Acknowledge: Notificar a la nube que el pin ya conmutó
        HTTPClient httpsAck;
        if (httpsAck.begin(client, ACK_PATH))
        {
          httpsAck.addHeader("Content-Type", "application/json");
          int ackCode = httpsAck.PUT(ordenEncendido ? "true" : "false");
          if (ackCode > 0)
          {
            Serial.println("[ACK] Confirmación física enviada a Firebase.");
          }
          httpsAck.end();
        }
      }
    }
    https.end();
  }
}

void setup()
{
  Serial.begin(115200);

  // Configuración del actuador (LED o Relé)
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  dht.begin();

  Serial.print("\n[RED] Conectando a Wi-Fi Wokwi-GUEST");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED)
  {
    delay(200);
    Serial.print(".");
  }
  Serial.println("\n[RED] Conexión establecida con éxito.");
  Serial.print("[RED] Dirección IP asignada: ");
  Serial.println(WiFi.localIP());
}

void loop()
{
  unsigned long currentMillis = millis();

  // Ciclo 1: Ingesta periódica de telemetría (cada 5s)
  if (currentMillis - lastTelemetryTime >= telemetryInterval)
  {
    lastTelemetryTime = currentMillis;
    enviarTelemetria();
  }

  // Ciclo 2: Monitoreo ágil de la consigna de control (cada 1s)
  if (currentMillis - lastPollControl >= pollInterval)
  {
    lastPollControl = currentMillis;
    revisarControl();
  }
}