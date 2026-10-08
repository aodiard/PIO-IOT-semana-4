"""
Project: AIoT Supervision System
Script Name: supervisor.py
Date: 2026-01-28
Version: 1.2.0
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
FIREBASE_URL ="Completar con la URL de su proyecto" 
RUTA_NODO = f"{FIREBASE_URL}/nodos/nodo_01"

ENDPOINT_TELEMETRIA = f"{RUTA_NODO}/telemetria.json"
ENDPOINT_CONTROL = f"{RUTA_NODO}/control/rele_estado.json"
ENDPOINT_AUDITORIA = f"{RUTA_NODO}/auditoria_ia.json"

UMBRAL_TEMPERATURA_CRITICA = 35.0

mitigacion_activa = False
ultima_humedad_conocida = 50.0  # Valor por defecto si se edita manualmente solo la temperatura en consola

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("Falta la variable de entorno: GEMINI_API_KEY debe estar configurada.")

cliente_ia = genai.Client(api_key=API_KEY)


def consultar_supervisor_gemini(temperatura: float, humedad: float) -> dict:
    """
    Envía la telemetría a Google Gemini para evaluar la anomalía térmica
    y generar una directiva estructurada de mitigación.
    """
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
                tools=[]  # Desactiva la advertencia de function calling automático
            )
        )
        return json.loads(respuesta.text)
    except Exception as error:
        print(f"[ERROR] Falló la consulta a la API de Gemini: {error}")
        return {
            "alerta": True,
            "accion_rele": True,
            "diagnostico": "Protocolo de emergencia activado por tiempo de espera o fallo en el supervisor."
        }


def procesar_cambio_temperatura(temp: float, hum: float):
    """
    Evalúa la temperatura recibida (sea del ESP32 o por edición manual en consola)
    y gestiona el ciclo de mitigación o restablecimiento.
    """
    global mitigacion_activa
    print(f"[STREAM] Telemetría evaluada -> Temp: {temp} °C | Hum: {hum} %")

    # Caso A: Anomalía térmica detectada
    if temp >= UMBRAL_TEMPERATURA_CRITICA and not mitigacion_activa:
        print(f"\n[ALERTA] ⚠️ Temperatura crítica detectada: {temp} °C. Consultando a Gemini...")
        decision = consultar_supervisor_gemini(temp, hum)
        print(f"[AUDITORÍA GEMINI] Dictamen recibido: {decision}")

        if decision.get("accion_rele") is True:
            requests.put(ENDPOINT_CONTROL, json=True, timeout=3)
            requests.patch(ENDPOINT_AUDITORIA, json=decision, timeout=3)
            mitigacion_activa = True
            print("[ACCIÓN] ✅ Activación de relé enviada a Firebase (Mitigación activa).")

    # Caso B: Regreso a parámetros seguros
    elif temp < UMBRAL_TEMPERATURA_CRITICA and mitigacion_activa:
        print(f"\n[INFO] Temperatura normalizada ({temp} °C). Desactivando relé...")
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
    """
    Conexión persistente SSE (Server-Sent Events) sin polling cíclico.
    Maneja tanto objetos JSON completos como mutaciones atómicas en la consola.
    """
    global ultima_humedad_conocida
    headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache"
    }
    print(f"[SUPERVISOR] Conectando canal SSE a: {ENDPOINT_TELEMETRIA}")
    
    with requests.get(ENDPOINT_TELEMETRIA, headers=headers, stream=True, timeout=None) as stream_resp:
        if stream_resp.status_code != 200:
            print(f"[ERROR CONEXIÓN] Código HTTP {stream_resp.status_code}: {stream_resp.text}")
            return

        print("[SUPERVISOR] ✅ Canal SSE activo y escuchando eventos en tiempo real...")

        for linea in stream_resp.iter_lines(chunk_size=1, decode_unicode=True):
            if not linea:
                continue

            if linea.startswith("data:"):
                payload_str = linea[5:].strip()
                if not payload_str or payload_str == "null":
                    continue

                try:
                    payload = json.loads(payload_str)
                    path = payload.get("path", "/")
                    data = payload.get("data")

                    # Caso 1: Envío completo del ESP32 o carga inicial (path == "/")
                    if isinstance(data, dict):
                        temp = data.get("temperatura")
                        hum = data.get("humedad")
                        if hum is not None:
                            ultima_humedad_conocida = float(hum)
                        if temp is not None:
                            procesar_cambio_temperatura(float(temp), ultima_humedad_conocida)

                    # Caso 2: Edición manual en consola de Firebase (path == "/temperatura")
                    elif path == "/temperatura" and data is not None:
                        procesar_cambio_temperatura(float(data), ultima_humedad_conocida)

                    # Caso 3: Edición manual de humedad en consola (path == "/humedad")
                    elif path == "/humedad" and data is not None:
                        ultima_humedad_conocida = float(data)

                except json.JSONDecodeError:
                    pass


async def ciclo_supervision_continua():
    """
    Tarea centinela en segundo plano que mantiene el streaming SSE activo.
    """
    print("[SUPERVISOR] Tarea centinela reactiva iniciada.")
    while True:
        try:
            # Ejecuta la lectura bloqueante del stream en un hilo sin congelar el loop de asyncio
            await asyncio.to_thread(escuchar_stream_firebase)
        except Exception as err:
            print(f"[RECONEXIÓN STREAM] Conexión reiniciada: {err}")
            await asyncio.sleep(2)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """
    Administra el ciclo de vida del servicio FastAPI, iniciando y deteniendo tareas limpiamente.
    """
    tarea = asyncio.create_task(ciclo_supervision_continua())
    yield
    tarea.cancel()


app = FastAPI(
    title="Supervisor AIoT - IES 9-010",
    description="Supervisor cognitivo industrial 100% reactivo conectado por SSE a Firebase.",
    version="1.2.0",
    lifespan=ciclo_de_vida
)


@app.get("/")
def estado_servicio():
    """
    Endpoint de diagnóstico para validar el estado operativo del supervisor.
    """
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
