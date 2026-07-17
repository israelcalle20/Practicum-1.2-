"""
evaluador.py — semana 6-7.

Dos responsabilidades:
1. LLM-as-Judge: el mismo Gemini evalúa cada recurso generado contra los
   criterios de calidad de la tabla del reto, y el reporte se guarda en
   la colección "evaluaciones".
2. Registro del feedback del docente titular: una función simple para
   dejar constancia de sus observaciones y de las mejoras aplicadas,
   guardado en la colección "feedback_docente".

Igual que en prompts.py: cada llamada a Gemini queda registrada en
"prompts_usados" (con tipo "evaluacion_<recurso>"), y si se agota la
cuota gratuita tras varios reintentos, el programa se cierra con un
mensaje claro en vez de un traceback.
"""
import os
import sys
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

PAUSA_ENTRE_LLAMADAS_SEG = 3
MAX_REINTENTOS = 5

# Criterios de calidad tomados directamente de la tabla de recursos del reto.
CRITERIOS = {
    "resumen": [
        "Cubre los tres conceptos más importantes de la unidad.",
        "Ningún párrafo supera las cuatro líneas.",
        "No inventa información que no está en el material fuente.",
    ],
    "glosario": [
        "Los términos son específicos de la unidad, no genéricos.",
        "Las definiciones son precisas y no circulares.",
        "El orden va de más a menos fundamental.",
    ],
    "preguntas": [
        "Las preguntas son respondibles con el material de la unidad.",
        "La dificultad corresponde correctamente a la taxonomía de Bloom (2 fácil, 2 media, 1 difícil).",
        "Las respuestas no son ambiguas.",
    ],
    "actividad": [
        "La actividad es realizable en 20 a 30 minutos.",
        "Tiene un enunciado claro y un producto esperado definido.",
        "Conecta el contenido teórico con un contexto práctico.",
    ],
}

_SCHEMA_EVALUACION = {
    "type": "object",
    "properties": {
        "criterios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterio": {"type": "string"},
                    "cumple": {"type": "boolean"},
                    "justificacion": {"type": "string"},
                },
                "required": ["criterio", "cumple", "justificacion"],
            },
        },
        "puntaje": {
            "type": "integer",
            "description": "Puntaje global de 1 a 5 para este recurso",
        },
    },
    "required": ["criterios", "puntaje"],
}


def _registrar_prompt_usado(metadata: dict, prompt: str, exitoso: bool,
                             resultado: dict = None, error: str = None):
    """Igual que en prompts.py: deja constancia de cada llamada a Gemini."""
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
        print(f"    (Aviso: no se pudo registrar el prompt en MongoDB: {e})")


def evaluar_recurso(tipo: str, contenido_recurso: dict, contenido_unidad: str,
                     codigo_asignatura: str = None, numero_unidad: int = None) -> dict:
    """Pide a Gemini que evalúe un recurso contra sus criterios de calidad."""
    criterios = CRITERIOS[tipo]
    prompt = f"""
    Eres un evaluador experto en diseño instruccional. Evalúa el siguiente
    recurso didáctico de tipo '{tipo}' contra cada uno de estos criterios
    de calidad, usando el contenido original de la unidad como referencia
    para verificar precisión y fidelidad.

    CRITERIOS A EVALUAR:
    {json.dumps(criterios, ensure_ascii=False, indent=2)}

    CONTENIDO ORIGINAL DE LA UNIDAD (para verificar fidelidad):
    {contenido_unidad[:4000]}

    RECURSO GENERADO A EVALUAR:
    {json.dumps(contenido_recurso, ensure_ascii=False, indent=2)}

    Para cada criterio indica si se cumple (true/false) y una justificación
    breve. Al final da un puntaje global de 1 (deficiente) a 5 (excelente).
    Sé estricto: si el recurso inventa datos que no están en el contenido
    original, márcalo como no cumplido en el criterio correspondiente.
    """
    metadata = {
        "tipo": f"evaluacion_{tipo}",
        "numero_unidad": numero_unidad,
        "codigo_asignatura": codigo_asignatura,
    }
    ultimo_error = None
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            respuesta = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_SCHEMA_EVALUACION,
                    temperature=0.2,
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
                espera = 15 * intento
                print(f"    (Gemini respondió {codigo}, reintentando en {espera}s "
                      f"— intento {intento}/{MAX_REINTENTOS})")
                time.sleep(espera)
                continue

            _registrar_prompt_usado(metadata, prompt, exitoso=False, error=ultimo_error)
            if codigo == 429:
                from prompts import CuotaAgotadaError, MENSAJE_CUOTA_AGOTADA
                raise CuotaAgotadaError(MENSAJE_CUOTA_AGOTADA) from e
            raise


def evaluar_unidad(codigo_asignatura: str, numero_unidad: int):
    """Evalúa los cuatro recursos de una unidad y guarda el reporte en MongoDB."""
    db = get_db()

    unidad_doc = db.recursos.find_one(
        {"codigo_asignatura": codigo_asignatura, "numero_unidad": numero_unidad}
    )
    if unidad_doc is None:
        raise ValueError("No hay recursos generados para esta unidad todavía.")

    asignatura_doc = db.asignaturas.find_one({"codigo": codigo_asignatura})
    unidad_original = next(
        u for u in asignatura_doc["unidades"] if u["numero"] == numero_unidad
    )
    contenido_unidad = unidad_original["contenido"]

    reporte = {
        "codigo_asignatura": codigo_asignatura,
        "numero_unidad": numero_unidad,
        "evaluado_en": datetime.now(timezone.utc),
        "resultados": {},
    }

    for tipo in ("resumen", "glosario", "preguntas", "actividad"):
        recurso = db.recursos.find_one(
            {"codigo_asignatura": codigo_asignatura, "numero_unidad": numero_unidad, "tipo": tipo}
        )
        if recurso is None:
            continue
        print(f"  Evaluando '{tipo}' de la unidad {numero_unidad}...")
        reporte["resultados"][tipo] = evaluar_recurso(
            tipo, recurso["contenido"], contenido_unidad,
            codigo_asignatura=codigo_asignatura, numero_unidad=numero_unidad,
        )

    db.evaluaciones.update_one(
        {"codigo_asignatura": codigo_asignatura, "numero_unidad": numero_unidad},
        {"$set": reporte},
        upsert=True,
    )
    return reporte


def registrar_feedback_docente(codigo_asignatura: str, docente: str, observaciones: list[str]):
    """
    Registra el feedback cualitativo del docente titular sobre el
    documento Word generado. 'observaciones' es una lista de strings,
    una por cada observación concreta (el reto pide al menos tres).
    """
    db = get_db()
    db.feedback_docente.insert_one({
        "codigo_asignatura": codigo_asignatura,
        "docente": docente,
        "observaciones": observaciones,
        "registrado_en": datetime.now(timezone.utc),
        "mejoras_aplicadas": [],
    })
    print(f"Feedback de {docente} registrado ({len(observaciones)} observaciones).")


def registrar_mejora_aplicada(codigo_asignatura: str, docente: str, mejora: str):
    """Agrega una mejora aplicada al último feedback registrado de ese docente."""
    db = get_db()
    db.feedback_docente.update_one(
        {"codigo_asignatura": codigo_asignatura, "docente": docente},
        {"$push": {"mejoras_aplicadas": mejora}},
        sort=[("registrado_en", -1)],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evalúa los recursos de una unidad ya generada.")
    parser.add_argument("--codigo", help="Código de la asignatura (el que imprimió construir_base_real.py)")
    parser.add_argument("--unidad", type=int, help="Número de unidad a evaluar")
    parser.add_argument("--docente", help="Nombre del docente titular, para el registro de feedback (opcional)")
    args = parser.parse_args()

    codigo = args.codigo or input("Código de la asignatura: ").strip()
    numero_unidad = args.unidad or int(input("Número de unidad a evaluar: ").strip())

    from prompts import CuotaAgotadaError
    try:
        reporte = evaluar_unidad(codigo, numero_unidad)
    except CuotaAgotadaError as e:
        sys.exit(f"\n{'=' * 56}\n  {e}\n{'=' * 56}\n")

    print(json.dumps(reporte, indent=2, ensure_ascii=False, default=str))

    docente = args.docente or input(
        "Nombre del docente titular (Enter para omitir el registro de feedback): "
    ).strip()
    if docente:
        observaciones = []
        print("Ingresa las observaciones del docente, una por línea (línea vacía para terminar):")
        while True:
            obs = input("  - ").strip()
            if not obs:
                break
            observaciones.append(obs)
        if observaciones:
            registrar_feedback_docente(codigo, docente, observaciones)
