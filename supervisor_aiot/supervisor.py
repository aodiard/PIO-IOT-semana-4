"""
Project: AIoT Supervision System - Unit 4
Script Name: supervisor.py
Version: 1.1.0

Parameters:
    - GEMINI_API_KEY: Google Gemini API authentication key provided via environment variable.
"""

import os
import json
import asyncio
import requests
from contextlib import asynccontextmanager
from fastapi import FastAPI
from google import genai
from google.genai import types

# ---------------------------------------------------------
# Configuración del Nodo Industrial (Semana 1 a 4)
# ---------------------------------------------------------
FIREBASE_URL = "Completar con la URL de su proyecto"
RUTA_NODO = f"{FIREBASE_URL}/nodos/nodo_01"

ENDPOINT_TELEMETRIA = f"{RUTA_NODO}/telemetria.json"
ENDPOINT_CONTROL = f"{RUTA_NODO}/control/rele_estado.json"
ENDPOINT_AUDITORIA = f"{RUTA_NODO}/auditoria_ia.json"

UMBRAL_TEMPERATURA_CRITICA = 35.0

mitigacion_activa = False

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("Falta la variable de entorno: GEMINI_API_KEY debe estar configurada.")

cliente_ia = genai.Client(api_key=API_KEY)


def consultar_supervisor_gemini(temperatura: float, humedad: float) -> dict:
    prompt = f"""
    Eres un sistema de control supervisorio autónomo para una planta industrial.
    Telemetría actual del Nodo 01:
    - Temperatura: {temperatura} °C
    - Humedad: {humedad} %
    - Umbral de Seguridad: {UMBRAL_TEMPERATURA_CRITICA} °C

    Analiza esta anomalía térmica y genera una directiva operativa inmediata.
    Responde ESTRICTAMENTE con un objeto JSON válido siguiendo este esquema:
    {{
        "alerta": true,
        "accion_rele": true,
        "diagnostico": "Explicación técnica breve del motivo de la mitigación"
    }}
    """

    try:
        respuesta = cliente_ia.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                tools=[]
            )
        )
        return json.loads(respuesta.text)
    except Exception as error:
        print(f"[ERROR] Falló la consulta a la API de Gemini: {error}")
        return {
            "alerta": True,
            "accion_rele": True,
            "diagnostico": "Protocolo de emergencia activado por fallo en la API."
        }


def procesar_evento_telemetria(datos_telemetria: dict):
    global mitigacion_activa
    if not isinstance(datos_telemetria, dict):
        return

    temp = float(datos_telemetria.get("temperatura", 0.0))
    hum = float(datos_telemetria.get("humedad", 0.0))

    # Caso A: Anomalía térmica detectada
    if temp >= UMBRAL_TEMPERATURA_CRITICA and not mitigacion_activa:
        print(f"\n[EVENTO STREAM] ⚠️ Temperatura crítica detectada: {temp} °C. Consultando a Gemini...")
        decision = consultar_supervisor_gemini(temp, hum)
        print(f"[AUDITORÍA GEMINI] Dictamen recibido: {decision}")

        if decision.get("accion_rele") is True:
            requests.put(ENDPOINT_CONTROL, json=True, timeout=3)
            requests.patch(ENDPOINT_AUDITORIA, json=decision, timeout=3)
            mitigacion_activa = True
            print("[ACCIÓN] ✅ Activación de relé enviada a Firebase (Mitigación activa).")

    # Caso B: Regreso a parámetros seguros
    elif temp < UMBRAL_TEMPERATURA_CRITICA and mitigacion_activa:
        print(f"\n[EVENTO STREAM] Temperatura normalizada ({temp} °C). Desactivando relé...")
        requests.put(ENDPOINT_CONTROL, json=False, timeout=3)
        
        registro_restablecimiento = {
            "alerta": False,
            "accion_rele": False,
            "diagnostico": f"Parámetros nominales restablecidos ({temp} °C)."
        }
        requests.patch(ENDPOINT_AUDITORIA, json=registro_restablecimiento, timeout=3)
        mitigacion_activa = False
        print("[ACCIÓN] 🔄 Nodo restablecido a modo reposo.")


def escuchar_stream_firebase():
    """Conexión persistente SSE (Server-Sent Events) sin polling cíclico."""
    headers = {"Accept": "text/event-stream"}
    print("[SUPERVISOR] Abriendo canal SSE en tiempo real con Firebase...")
    
    with requests.get(ENDPOINT_TELEMETRIA, headers=headers, stream=True, timeout=90) as stream_resp:
        for linea in stream_resp.iter_lines(decode_unicode=True):
            if linea and linea.startswith("data:"):
                payload_str = linea[5:].strip()
                if payload_str and payload_str != "null":
                    try:
                        evento = json.loads(payload_str)
                        # Firebase envía los datos bajo la clave 'data' en eventos SSE
                        datos = evento.get("data") if isinstance(evento, dict) and "data" in evento else evento
                        if isinstance(datos, dict):
                            procesar_evento_telemetria(datos)
                    except json.JSONDecodeError:
                        pass


async def ciclo_supervision_continua():
    print("[SUPERVISOR] Tarea centinela reactiva iniciada.")
    while True:
        try:
            # Ejecuta la escucha bloqueante en un hilo sin congelar el event loop de asyncio
            await asyncio.to_thread(escuchar_stream_firebase)
        except Exception as err:
            print(f"[RECONEXIÓN STREAM] Conexión reiniciada: {err}")
            await asyncio.sleep(2)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    tarea = asyncio.create_task(ciclo_supervision_continua())
    yield
    tarea.cancel()


app = FastAPI(
    title="Supervisor AIoT - IES 9-010",
    description="Supervisor cognitivo industrial 100% reactivo conectado por SSE a Firebase.",
    version="1.1.0",
    lifespan=ciclo_de_vida
)


@app.get("/")
def estado_servicio():
    return {
        "estado": "en_linea",
        "modo": "streaming_sse_event_driven",
        "servicio": "Supervisor Autónomo AIoT",
        "mitigacion_activa": mitigacion_activa,
        "nodo_monitoreado": RUTA_NODO
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
