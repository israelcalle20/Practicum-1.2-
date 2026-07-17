"""
pipeline.py — orquestador de extremo a extremo.

Flujo:
1. Carga la base de conocimiento (desde MongoDB si ya existe, o la
   construye desde los PDFs si es la primera corrida).
2. Para cada unidad, llama a los cuatro prompts en orden: resumen,
   glosario, preguntas, actividad.
3. Guarda el resultado de cada prompt en MongoDB (colección "recursos"),
   un documento por (asignatura, unidad, tipo_recurso).
4. Al terminar todas las unidades, llama al exportador para generar el
   documento Word.

Correr con: python src/pipeline.py

Este módulo también lo usa app_web.py (la interfaz web con Streamlit),
por eso ejecutar_pipeline() acepta parámetros opcionales para: procesar
solo algunas unidades, pasar instrucciones adicionales por tipo de
recurso, y reportar progreso con un callback (para la barra de progreso
de la web).
"""
from datetime import datetime, timezone

from db import get_db
from base_conocimiento import cargar_base, guardar_base
from prompts import generar_resumen, generar_glosario, generar_preguntas, generar_actividad, CuotaAgotadaError
from exportador import exportar_word


def guardar_recurso(codigo_asignatura: str, numero_unidad: int, tipo: str, contenido: dict):
    """Guarda (o reemplaza) el JSON de un recurso en la colección 'recursos'."""
    db = get_db()
    db.recursos.update_one(
        {"codigo_asignatura": codigo_asignatura, "numero_unidad": numero_unidad, "tipo": tipo},
        {"$set": {
            "codigo_asignatura": codigo_asignatura,
            "numero_unidad": numero_unidad,
            "tipo": tipo,
            "contenido": contenido,
            "generado_en": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


def obtener_recursos_unidad(codigo_asignatura: str, numero_unidad: int) -> dict:
    """Recupera los cuatro recursos ya generados de una unidad, listos para exportar."""
    db = get_db()
    recursos = {}
    for doc in db.recursos.find(
        {"codigo_asignatura": codigo_asignatura, "numero_unidad": numero_unidad}, {"_id": 0}
    ):
        recursos[doc["tipo"]] = doc["contenido"]
    return recursos


def ya_existe_recurso(codigo_asignatura: str, numero_unidad: int, tipo: str) -> bool:
    """Revisa si un recurso ya fue generado antes, para no gastar cuota de Gemini
    regenerándolo si el pipeline se interrumpió y se vuelve a correr."""
    db = get_db()
    return db.recursos.find_one(
        {"codigo_asignatura": codigo_asignatura, "numero_unidad": numero_unidad, "tipo": tipo}
    ) is not None


def procesar_unidad(codigo_asignatura: str, unidad: dict, forzar: bool = False,
                     instrucciones_por_tipo: dict = None, callback_paso=None):
    """Genera y guarda los cuatro recursos de una unidad.
    - forzar=False (por defecto): salta los recursos que ya existen en
      MongoDB — así se puede reanudar tras un corte de cuota sin gastar
      cuota en lo que ya estaba listo.
    - instrucciones_por_tipo: dict opcional {'resumen': '...', 'glosario': '...', ...}
      con instrucciones adicionales para Gemini, por tipo de recurso
      (lo usa la app web para permitir personalizar el prompt).
    - callback_paso: función opcional que se llama como
      callback_paso(numero_unidad, tipo, estado) para reportar progreso
      ('omitido' | 'generando' | 'listo'), útil para la barra de progreso
      de la web."""
    instrucciones_por_tipo = instrucciones_por_tipo or {}
    numero = unidad["numero"]
    print(f"  Unidad {numero} — {unidad['titulo']}")

    tareas = [
        ("resumen", generar_resumen),
        ("glosario", generar_glosario),
        ("preguntas", generar_preguntas),
        ("actividad", generar_actividad),
    ]
    for tipo, funcion_generadora in tareas:
        if not forzar and ya_existe_recurso(codigo_asignatura, numero, tipo):
            print(f"    · {tipo} ya generado, se omite")
            if callback_paso:
                callback_paso(numero, tipo, "omitido")
            continue
        print(f"    · generando {tipo}...")
        if callback_paso:
            callback_paso(numero, tipo, "generando")
        resultado = funcion_generadora(
            unidad, codigo_asignatura,
            instrucciones_extra=instrucciones_por_tipo.get(tipo, ""),
        )
        guardar_recurso(codigo_asignatura, numero, tipo, resultado)
        if callback_paso:
            callback_paso(numero, tipo, "listo")


def ejecutar_pipeline(codigo_asignatura: str, ruta_salida_docx: str, forzar: bool = False,
                       unidades_seleccionadas: list = None, instrucciones_por_tipo: dict = None,
                       callback_paso=None):
    """
    unidades_seleccionadas: lista opcional de números de unidad a procesar
    (por defecto, todas las de la base de conocimiento). El documento Word
    final igual incluye todas las unidades de la base, usando lo que ya
    esté generado para las que no se hayan seleccionado esta vez.
    """
    base = cargar_base(codigo_asignatura)
    if base is None:
        raise ValueError(
            f"No hay base de conocimiento guardada para '{codigo_asignatura}'. "
            "Corre primero construir_base_real.py para construirla y guardarla."
        )

    unidades_a_procesar = [
        u for u in base["unidades"]
        if unidades_seleccionadas is None or u["numero"] in unidades_seleccionadas
    ]

    print(f"Procesando '{base['asignatura']}' ({len(unidades_a_procesar)} unidades)...")
    for unidad in unidades_a_procesar:
        procesar_unidad(codigo_asignatura, unidad, forzar=forzar,
                         instrucciones_por_tipo=instrucciones_por_tipo, callback_paso=callback_paso)

    print("Ensamblando documento Word...")
    unidades_recursos = []
    for unidad in base["unidades"]:
        recursos = obtener_recursos_unidad(codigo_asignatura, unidad["numero"])
        unidades_recursos.append({
            "numero": unidad["numero"],
            "titulo": unidad["titulo"],
            "resumen": recursos.get("resumen"),
            "glosario": recursos.get("glosario"),
            "preguntas": recursos.get("preguntas"),
            "actividad": recursos.get("actividad"),
        })

    exportar_word(base["asignatura"], unidades_recursos, ruta_salida_docx)
    print("Pipeline completo.")
    return ruta_salida_docx


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Corre el pipeline completo para una asignatura.")
    parser.add_argument("--codigo", help="Código de la asignatura, tal como quedó guardada en MongoDB "
                                          "(lo imprime construir_base_real.py al terminar).")
    parser.add_argument("--forzar", action="store_true",
                         help="Regenera TODOS los recursos aunque ya existan (por defecto se saltan "
                              "los que ya están generados).")
    args = parser.parse_args()

    codigo = args.codigo or input("Código de la asignatura (el que imprimió construir_base_real.py): ").strip()

    try:
        ejecutar_pipeline(
            codigo_asignatura=codigo,
            ruta_salida_docx=f"data/recursos_{codigo}.docx",
            forzar=args.forzar,
        )
    except CuotaAgotadaError as e:
        sys.exit(f"\n{'=' * 56}\n  {e}\n{'=' * 56}\n")
