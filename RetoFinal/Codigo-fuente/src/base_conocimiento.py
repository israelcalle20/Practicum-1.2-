"""
base_conocimiento.py — construye el diccionario de la asignatura y sus
unidades, y lo persiste en MongoDB para no tener que re-extraer los PDFs
cada vez que se corre el pipeline.

Colección usada: "unidades" (una colección "asignaturas" guarda un
documento por asignatura, con sus unidades embebidas).

Estructura que se guarda (igual a la del documento del reto):
{
    "asignatura": "Fundamentos de Programación",
    "codigo": "INF101",
    "carrera": "Ingeniería en Sistemas",
    "ciclo": "1ro",
    "unidades": [
        {
            "numero": 1,
            "titulo": "Introducción a la algoritmia",
            "objetivos": "...",
            "contenido": "...",
            "actividades": "...",
        },
        ...
    ]
}
"""
from extractor import extraer_texto
from db import get_db


def construir_unidad(numero: int, titulo: str, ruta_contenido: str,
                      objetivos: str = "", actividades: str = "") -> dict:
    """Construye el diccionario de una unidad a partir de su material fuente."""
    contenido = extraer_texto(ruta_contenido)
    return {
        "numero": numero,
        "titulo": titulo,
        "objetivos": objetivos,
        "contenido": contenido,
        "actividades": actividades,
    }


def construir_base(asignatura: str, codigo: str, carrera: str, ciclo: str,
                    unidades: list) -> dict:
    """Ensambla el diccionario completo de la base de conocimiento."""
    return {
        "asignatura": asignatura,
        "codigo": codigo,
        "carrera": carrera,
        "ciclo": ciclo,
        "unidades": unidades,
    }


def guardar_base(base: dict):
    """Inserta o actualiza la base de conocimiento en MongoDB (upsert por código)."""
    db = get_db()
    db.asignaturas.update_one(
        {"codigo": base["codigo"]},
        {"$set": base},
        upsert=True,
    )
    print(f"Base de conocimiento guardada en MongoDB para '{base['codigo']}'.")


def cargar_base(codigo: str) -> dict | None:
    """Recupera la base de conocimiento de una asignatura desde MongoDB."""
    db = get_db()
    return db.asignaturas.find_one({"codigo": codigo}, {"_id": 0})


if __name__ == "__main__":
    # Ejemplo con las dos unidades mínimas que pide la semana 1.
    # Ajusta rutas y textos a tu propia asignatura.
    unidad_1 = construir_unidad(
        numero=1,
        titulo="Introducción a la algoritmia",
        ruta_contenido="data/materiales/unidad_1.pdf",
        objetivos="Resultados de aprendizaje extraídos del plan docente...",
        actividades="Descripción de actividades de la unidad 1...",
    )
    unidad_2 = construir_unidad(
        numero=2,
        titulo="Estructuras de control",
        ruta_contenido="data/materiales/unidad_2.pdf",
        objetivos="Resultados de aprendizaje extraídos del plan docente...",
        actividades="Descripción de actividades de la unidad 2...",
    )

    base = construir_base(
        asignatura="Fundamentos de Programación",
        codigo="INF101",
        carrera="Ingeniería en Sistemas",
        ciclo="1ro",
        unidades=[unidad_1, unidad_2],
    )

    guardar_base(base)

    # Verificación: releer desde MongoDB
    base_recuperada = cargar_base("INF101")
    print(f"Unidades recuperadas: {len(base_recuperada['unidades'])}")
