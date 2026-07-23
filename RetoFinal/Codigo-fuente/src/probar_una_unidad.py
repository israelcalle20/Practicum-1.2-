"""
probar_una_unidad.py — corre los 4 prompts y la exportación solo para
una unidad, para revisar la calidad antes de lanzar el pipeline completo
sobre todas las unidades de la asignatura.

Uso:
    python src/probar_una_unidad.py --codigo COMP_2010 --unidad 1
    (si no pasas los argumentos, te los pide de forma interactiva)
"""
import json
import argparse

from base_conocimiento import cargar_base
from pipeline import procesar_unidad, obtener_recursos_unidad
from exportador import exportar_word


def probar(codigo_asignatura: str, numero_unidad: int):
    base = cargar_base(codigo_asignatura)
    if base is None:
        raise ValueError(f"No hay base de conocimiento guardada para '{codigo_asignatura}'.")

    unidad = next((u for u in base["unidades"] if u["numero"] == numero_unidad), None)
    if unidad is None:
        raise ValueError(f"La asignatura '{codigo_asignatura}' no tiene una unidad número {numero_unidad}.")

    print(f"Procesando solo la unidad {unidad['numero']}: {unidad['titulo']}")
    procesar_unidad(codigo_asignatura, unidad)

    recursos = obtener_recursos_unidad(codigo_asignatura, numero_unidad)

    for etiqueta, clave in [
        ("RESUMEN GENERADO", "resumen"),
        ("GLOSARIO GENERADO", "glosario"),
        ("PREGUNTAS GENERADAS", "preguntas"),
        ("ACTIVIDAD GENERADA", "actividad"),
    ]:
        print("\n" + "=" * 60)
        print(etiqueta)
        print("=" * 60)
        print(json.dumps(recursos.get(clave), indent=2, ensure_ascii=False))

    ruta_salida = f"data/prueba_{codigo_asignatura}_unidad_{numero_unidad}.docx"
    exportar_word(
        asignatura=base["asignatura"],
        unidades_recursos=[{
            "numero": unidad["numero"],
            "titulo": unidad["titulo"],
            "resumen": recursos.get("resumen"),
            "glosario": recursos.get("glosario"),
            "preguntas": recursos.get("preguntas"),
            "actividad": recursos.get("actividad"),
        }],
        ruta_salida=ruta_salida,
    )
    print(f"\nListo. Revisa {ruta_salida} para ver el formato final.")


if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="Prueba el pipeline con una sola unidad.")
    parser.add_argument("--codigo", help="Código de la asignatura")
    parser.add_argument("--unidad", type=int, help="Número de unidad a probar")
    args = parser.parse_args()

    codigo = args.codigo or input("Código de la asignatura: ").strip()
    numero = args.unidad or int(input("Número de unidad a probar: ").strip())

    from prompts import CuotaAgotadaError
    try:
        probar(codigo, numero)
    except CuotaAgotadaError as e:
        sys.exit(f"\n{'=' * 56}\n  {e}\n{'=' * 56}\n")
