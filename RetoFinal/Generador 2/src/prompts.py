"""
prompts.py — los cuatro prompts que generan los recursos didácticos.

Cada función recibe el diccionario de una unidad (con 'titulo', 'objetivos',
'contenido', 'actividades') y devuelve un dict ya parseado desde el JSON
que responde Gemini. Usa response_schema para forzar la estructura, así
el exportador y el evaluador siempre reciben el mismo formato.

Todas aceptan un parámetro opcional 'instrucciones_extra': texto libre
que se agrega al final del prompt base, pensado para que la app web (o
tú desde la terminal) puedan afinar el resultado sin tocar código — por
ejemplo "usa un tono más informal" o "enfócate en ejemplos con hardware
real".

Cada llamada a Gemini queda registrada en MongoDB (colección
"prompts_usados"): el prompt exacto enviado, si tuvo éxito o no, y el
resultado. Esto documenta automáticamente el ciclo de prueba/refinamiento
de las semanas 2-3, sin que tengas que copiar nada a mano.

Si se agota la cuota gratuita de Gemini (error 429 persistente tras varios
reintentos), se levanta CuotaAgotadaError en vez de un traceback crudo,
para que tanto la CLI como la app web puedan manejarlo con un mensaje
claro sin caerse del todo.

Nota sobre el modelo: el SDK "google-generativeai" y los modelos gemini-1.5
están descontinuados. Este archivo usa el SDK actual "google-genai" con
gemini-flash-latest. Si más adelante hay un modelo más nuevo disponible en tu
cuenta de Google AI Studio, solo cambia MODEL_NAME.
"""
import os
import json
import time
from datetime import datetime, timezone

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from dotenv import load_dotenv

from db import get_db

load_dotenv()

MODEL_NAME = "gemini-flash-latest"
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Pausa entre llamadas consecutivas para no chocar con el límite de
# peticiones por minuto del tier gratuito de Gemini.
PAUSA_ENTRE_LLAMADAS_SEG = 3
# Reintentos ante error 429 (cuota excedida) o 503 (servidor saturado).
MAX_REINTENTOS = 5


class CuotaAgotadaError(Exception):
    """Se agotó la cuota gratuita de Gemini tras varios reintentos.
    Los scripts de terminal la capturan y cierran limpio con sys.exit();
    la app web la captura y muestra un aviso sin caerse."""
    pass


MENSAJE_CUOTA_AGOTADA = (
    "Se agotó la cuota gratuita de la API de Gemini. "
    "Nada se perdió — todo lo ya generado quedó guardado en MongoDB. "
    "Espera a que se reinicie tu cuota (normalmente al día siguiente, "
    "hora del Pacífico de EE.UU.) y vuelve a intentarlo: "
    "lo ya generado no se regenera ni se duplica."
)


def _registrar_prompt_usado(metadata: dict, prompt: str, exitoso: bool,
                             resultado: dict = None, error: str = None):
    """Guarda en MongoDB cada prompt enviado a Gemini, para documentar
    qué se probó y qué resultado dio (semana 2-3: 'registro de primeras
    observaciones')."""
    try:
        db = get_db()
        db.prompts_usados.insert_one({
            **metadata,
            "prompt_enviado": prompt.strip(),
            "exitoso": exitoso,
            "resultado": resultado,
            "error": error,
            "modelo": MODEL_NAME,
            "generado_en": datetime.now(timezone.utc),
        })
    except Exception as e:
        # No queremos que un fallo al registrar tumbe la generación en sí.
        print(f"    (Aviso: no se pudo registrar el prompt en MongoDB: {e})")


def _generar_json(prompt: str, schema: dict, metadata: dict) -> dict:
    """Llama a Gemini pidiendo salida JSON forzada por schema y la parsea.
    Reintenta con espera progresiva si Gemini responde 429 o 503.
    Registra el intento (éxito o fallo) en MongoDB.
    Si se agota la cuota tras todos los reintentos, levanta
    CuotaAgotadaError (quien la llame decide qué hacer)."""
    ultimo_error = None
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            respuesta = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.4,
                ),
            )
            time.sleep(PAUSA_ENTRE_LLAMADAS_SEG)
            resultado = json.loads(respuesta.text)
            _registrar_prompt_usado(metadata, prompt, exitoso=True, resultado=resultado)
            return resultado
        except genai_errors.ClientError as e:
            codigo = getattr(e, "code", None)
            ultimo_error = str(e)
            if codigo in (429, 503) and intento < MAX_REINTENTOS:
                espera = 15 * intento  # espera progresiva: 15s, 30s, 45s...
                print(f"    (Gemini respondió {codigo}, reintentando en {espera}s "
                      f"— intento {intento}/{MAX_REINTENTOS})")
                time.sleep(espera)
                continue

            _registrar_prompt_usado(metadata, prompt, exitoso=False, error=ultimo_error)
            if codigo == 429:
                raise CuotaAgotadaError(MENSAJE_CUOTA_AGOTADA) from e
            raise


def _con_instrucciones_extra(prompt: str, instrucciones_extra: str) -> str:
    """Agrega instrucciones adicionales opcionales (de la web o de la CLI) al final del prompt base."""
    if instrucciones_extra and instrucciones_extra.strip():
        prompt += f"\n\n    INSTRUCCIONES ADICIONALES DEL USUARIO:\n    {instrucciones_extra.strip()}\n    "
    return prompt


def generar_resumen(unidad: dict, codigo_asignatura: str = None, instrucciones_extra: str = "") -> dict:
    """Resumen ejecutivo de dos párrafos. -> {'parrafo_1':..., 'parrafo_2':...}"""
    prompt = f"""
    Eres un experto en diseño instruccional universitario.
    Unidad: '{unidad['titulo']}'.

    OBJETIVOS DE LA UNIDAD:
    {unidad.get('objetivos', '')}

    CONTENIDO DE LA UNIDAD:
    {unidad['contenido']}

    Genera un resumen ejecutivo de exactamente dos párrafos para un
    estudiante universitario que ya leyó el material y quiere repasar los
    conceptos clave. Cubre los tres conceptos más importantes del contenido.
    No uses párrafos de más de cuatro líneas. No inventes información que
    no esté en el material.
    """
    prompt = _con_instrucciones_extra(prompt, instrucciones_extra)
    schema = {
        "type": "object",
        "properties": {
            "parrafo_1": {"type": "string"},
            "parrafo_2": {"type": "string"},
        },
        "required": ["parrafo_1", "parrafo_2"],
    }
    metadata = {
        "tipo": "resumen",
        "numero_unidad": unidad["numero"],
        "titulo_unidad": unidad["titulo"],
        "codigo_asignatura": codigo_asignatura,
    }
    return _generar_json(prompt, schema, metadata)


def generar_glosario(unidad: dict, codigo_asignatura: str = None, instrucciones_extra: str = "") -> dict:
    """8-10 términos técnicos con su definición. -> {'terminos': [{'termino','definicion'}]}"""
    prompt = f"""
    Eres un experto en diseño instruccional universitario.
    Unidad: '{unidad['titulo']}'.

    CONTENIDO DE LA UNIDAD:
    {unidad['contenido']}

    Genera entre ocho y diez términos técnicos específicos de esta unidad
    (no términos genéricos que aplicarían a cualquier tema), cada uno con
    una definición precisa de máximo dos oraciones, sin definiciones
    circulares. Ordena los términos de más a menos fundamental.
    """
    prompt = _con_instrucciones_extra(prompt, instrucciones_extra)
    schema = {
        "type": "object",
        "properties": {
            "terminos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "termino": {"type": "string"},
                        "definicion": {"type": "string"},
                    },
                    "required": ["termino", "definicion"],
                },
                "minItems": 8,
                "maxItems": 10,
            }
        },
        "required": ["terminos"],
    }
    metadata = {
        "tipo": "glosario",
        "numero_unidad": unidad["numero"],
        "titulo_unidad": unidad["titulo"],
        "codigo_asignatura": codigo_asignatura,
    }
    return _generar_json(prompt, schema, metadata)


def generar_preguntas(unidad: dict, codigo_asignatura: str = None, instrucciones_extra: str = "") -> dict:
    """5 preguntas por niveles de Bloom. -> {'preguntas': [{'nivel','pregunta','respuesta'}]}"""
    prompt = f"""
    Eres un experto en diseño instruccional y en la taxonomía de Bloom.
    Unidad: '{unidad['titulo']}'.

    CONTENIDO DE LA UNIDAD:
    {unidad['contenido']}

    Genera exactamente cinco preguntas de comprensión respondibles con el
    material de la unidad, organizadas así:
    - dos preguntas fáciles (nivel "facil": recordar/comprender)
    - dos preguntas medias (nivel "media": aplicar/analizar)
    - una pregunta difícil (nivel "dificil": evaluar/crear)
    Cada pregunta debe incluir su respuesta esperada, sin ambigüedad.
    """
    prompt = _con_instrucciones_extra(prompt, instrucciones_extra)
    schema = {
        "type": "object",
        "properties": {
            "preguntas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nivel": {"type": "string", "enum": ["facil", "media", "dificil"]},
                        "pregunta": {"type": "string"},
                        "respuesta": {"type": "string"},
                    },
                    "required": ["nivel", "pregunta", "respuesta"],
                },
                "minItems": 5,
                "maxItems": 5,
            }
        },
        "required": ["preguntas"],
    }
    metadata = {
        "tipo": "preguntas",
        "numero_unidad": unidad["numero"],
        "titulo_unidad": unidad["titulo"],
        "codigo_asignatura": codigo_asignatura,
    }
    return _generar_json(prompt, schema, metadata)


def generar_actividad(unidad: dict, codigo_asignatura: str = None, instrucciones_extra: str = "") -> dict:
    """Actividad de cierre de unidad. -> {'enunciado':..., 'producto_esperado':...}"""
    prompt = f"""
    Eres un experto en diseño instruccional universitario.
    Unidad: '{unidad['titulo']}'.

    CONTENIDO DE LA UNIDAD:
    {unidad['contenido']}

    ACTIVIDADES SUGERIDAS EN EL PLAN DOCENTE (si existen, úsalas como base):
    {unidad.get('actividades', '')}

    Diseña una actividad práctica de cierre de unidad: un caso para
    analizar, un problema para resolver, o una pregunta abierta que
    conecte el contenido con una situación real. Debe ser realizable en
    20 a 30 minutos, con un enunciado claro y un producto esperado
    definido.
    """
    prompt = _con_instrucciones_extra(prompt, instrucciones_extra)
    schema = {
        "type": "object",
        "properties": {
            "enunciado": {"type": "string"},
            "producto_esperado": {"type": "string"},
        },
        "required": ["enunciado", "producto_esperado"],
    }
    metadata = {
        "tipo": "actividad",
        "numero_unidad": unidad["numero"],
        "titulo_unidad": unidad["titulo"],
        "codigo_asignatura": codigo_asignatura,
    }
    return _generar_json(prompt, schema, metadata)
