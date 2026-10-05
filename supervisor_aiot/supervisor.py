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
INTERVALO_REVISION_SEGUNDOS = 3.0

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
                response_mime_type="application/json"
            )
        )
        return json.loads(respuesta.text)
    except Exception as error:
        print(f"[ERROR] Falló la consulta a la API de Gemini: {error}")
        return {
            "alerta": True,
            "accion_rele": True,
            "diagnostico": "Protocolo de emergencia activado por tiempo de espera agotado en la API del supervisor."
        }


async def ciclo_supervision_continua():
    global mitigacion_activa
    print("[SUPERVISOR] Tarea centinela iniciada. Monitoreando Nodo 01 en Firebase...")

    while True:
        try:
            respuesta = requests.get(ENDPOINT_TELEMETRIA, timeout=3)
            
            if respuesta.status_code == 200 and respuesta.json():
                telemetria = respuesta.json()
                temp = float(telemetria.get("temperatura", 0.0))
                hum = float(telemetria.get("humedad", 0.0))

                # Caso A: Temperatura crítica detectada
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

        except requests.RequestException as err_red:
            print(f"[ERROR DE RED] {err_red}")
        except Exception as err_gen:
            print(f"[ERROR GENERAL] {err_gen}")

        await asyncio.sleep(INTERVALO_REVISION_SEGUNDOS)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    tarea = asyncio.create_task(ciclo_supervision_continua())
    yield
    tarea.cancel()


app = FastAPI(
    title="Supervisor AIoT - IES 9-010",
    description="Supervisor cognitivo industrial que conecta Firebase RTDB con Google Gemini.",
    version="1.0.0",
    lifespan=ciclo_de_vida
)


@app.get("/")
def estado_servicio():
    return {
        "estado": "en_linea",
        "servicio": "Supervisor Autónomo AIoT",
        "mitigacion_activa": mitigacion_activa,
        "nodo_monitoreado": RUTA_NODO
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
