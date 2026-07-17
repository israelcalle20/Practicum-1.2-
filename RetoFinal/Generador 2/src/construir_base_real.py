"""
construir_base_real.py — arma la base de conocimiento de CUALQUIER
asignatura de la UTPL a partir de su Plan Docente (y opcionalmente su
Guía de Estudio) reales, sin nada harcodeado: la asignatura, el código,
la carrera y el ciclo se detectan automáticamente desde la tabla de
datos básicos del Plan Docente (ver extractor.extraer_metadatos_plan_docente).

Distintas facultades/asignaturas de la UTPL organizan el contenido
semanal de forma distinta, así que este módulo prueba dos estrategias
de lectura, en orden, y usa la primera que encuentre resultados:

ESTRATEGIA A — formato de párrafos:
    El Plan Docente y la Guía de Estudio usan encabezados de párrafo
    "SEMANA N: Título", con "Contenidos:", "Actividades docente:",
    "Actividades practico:", "Actividades autonomo:" en el Plan Docente,
    y "Objetivos", "Conceptos Clave" en la Guía de Estudio. Requiere
    ambos documentos.

ESTRATEGIA B — formato de tablas:
    El Plan Docente tiene una tabla por semana (la primera celda de la
    tabla dice "Semana N"), con filas "Resultados de aprendizaje...",
    "Contenidos a desarrollarse", y "Actividades del componente:
    Aprendizaje (en contacto con el docente / práctico-experimental /
    autónomo)". No necesita Guía de Estudio — el Plan Docente ya trae
    todo el contenido.

Uso:
    python src/construir_base_real.py --plan data/Plan_Docente.docx --guia data/Guia_Estudio.docx
    python src/construir_base_real.py --plan data/Plan_Docente.docx   (sin guía, si el Plan Docente ya trae todo)

    Si no pasas --plan/--guia, te los pide de forma interactiva
    (Enter en blanco para omitir la guía).
"""
import re
import argparse

import docx

from extractor import extraer_texto_docx, extraer_metadatos_plan_docente
from base_conocimiento import construir_base, guardar_base, cargar_base

_TILDES = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.translate(_TILDES)).strip().lower()


# ─────────────────────────────────────────────────────────────────────────
# ESTRATEGIA A — párrafos "SEMANA N: Título"
# ─────────────────────────────────────────────────────────────────────────
def _parsear_plan_docente_parrafos(texto: str) -> dict:
    bloques = re.split(r'(SEMANA \d+:.*)', texto)
    semanas = {}
    for i in range(1, len(bloques), 2):
        m = re.match(r'SEMANA (\d+): (.*)', bloques[i])
        if not m:
            continue
        num = int(m.group(1))
        cuerpo = bloques[i + 1]
        contenidos = re.search(r'Contenidos: (.*)', cuerpo)
        act_docente = re.search(r'Actividades docente: (.*)', cuerpo)
        act_practico = re.search(r'Actividades practico: (.*)', cuerpo)
        act_autonomo = re.search(r'Actividades autonomo: (.*)', cuerpo)
        semanas[num] = {
            'titulo': m.group(2).strip(),
            'contenidos': contenidos.group(1).strip() if contenidos else '',
            'actividades': ' | '.join(filter(None, [
                f"Docente: {act_docente.group(1).strip()}" if act_docente else '',
                f"Práctico: {act_practico.group(1).strip()}" if act_practico else '',
                f"Autónomo: {act_autonomo.group(1).strip()}" if act_autonomo else '',
            ])),
        }
    return semanas


def _parsear_guia_estudio_parrafos(texto: str) -> dict:
    partes = re.split(r'RESUMEN FINAL[^\n]*', texto, maxsplit=1)
    cuerpo_semanas = partes[0]
    resumen_final = partes[1] if len(partes) > 1 else ''

    bloques = re.split(r'(SEMANA \d+:.*)', cuerpo_semanas)
    semanas = {}
    for i in range(1, len(bloques), 2):
        m = re.match(r'SEMANA (\d+): (.*)', bloques[i])
        if not m:
            continue
        num = int(m.group(1))
        cuerpo = bloques[i + 1]

        obj_match = re.search(r'Objetivos\n(.*?)\nConceptos Clave', cuerpo, re.DOTALL)
        objetivos = obj_match.group(1).strip().split('\n') if obj_match else []

        con_match = re.search(r'Componentes Principales\n(.*?)\nPreguntas de Autoevaluacion', cuerpo, re.DOTALL)
        conceptos = con_match.group(1).strip().split('\n') if con_match else []

        semanas[num] = {'titulo': m.group(2).strip(), 'objetivos': objetivos, 'conceptos': conceptos}

    resumen_bloques = re.split(r'(Semana \d+)\n', resumen_final)
    for i in range(1, len(resumen_bloques), 2):
        num_match = re.search(r'\d+', resumen_bloques[i])
        if not num_match:
            continue
        num = int(num_match.group())
        texto_resumen = resumen_bloques[i + 1].strip().split('\n')[0]
        if num in semanas:
            semanas[num]['resumen'] = texto_resumen

    return semanas


def _construir_unidades_estrategia_a(ruta_plan_docente: str, ruta_guia_estudio: str) -> list:
    """Requiere ambos documentos con encabezados de párrafo 'SEMANA N: ...'."""
    if not ruta_guia_estudio:
        return []
    texto_plan = extraer_texto_docx(ruta_plan_docente)
    texto_guia = extraer_texto_docx(ruta_guia_estudio)

    plan = _parsear_plan_docente_parrafos(texto_plan)
    guia = _parsear_guia_estudio_parrafos(texto_guia)

    unidades = []
    for num in sorted(set(plan.keys()) & set(guia.keys())):
        p, g = plan[num], guia[num]
        objetivos = "; ".join(g.get("objetivos", []))
        conceptos = "\n".join(g.get("conceptos", []))
        contenido = (
            f"Contenidos oficiales del plan docente: {p['contenidos']}.\n\n"
            f"Conceptos clave de la semana:\n{conceptos}\n\n"
            f"Resumen: {g.get('resumen', '')}"
        )
        unidades.append({
            "numero": num, "titulo": p["titulo"], "objetivos": objetivos,
            "contenido": contenido, "actividades": p["actividades"],
        })
    return unidades


# ─────────────────────────────────────────────────────────────────────────
# ESTRATEGIA B — una tabla por semana dentro del Plan Docente
# ─────────────────────────────────────────────────────────────────────────
def _construir_unidades_estrategia_b(ruta_plan_docente: str) -> list:
    """No necesita Guía de Estudio: el Plan Docente ya trae el contenido
    semanal completo, una tabla por semana. Algunas plantillas de Word
    parten esa tabla en dos objetos de tabla distintos por un salto de
    página (la segunda mitad no repite el encabezado "Semana N"), así
    que primero agrupamos filas por bloque de semana antes de leer los
    campos."""
    documento = docx.Document(ruta_plan_docente)

    bloques = []
    bloque_actual = None
    for tabla in documento.tables:
        if not tabla.rows:
            continue
        primera_celda = tabla.rows[0].cells[0].text.strip()
        m = re.match(r'Semana (\d+)', primera_celda, re.IGNORECASE)
        filas = [[c.text.strip() for c in fila.cells] for fila in tabla.rows]
        if m:
            if bloque_actual is not None:
                bloques.append(bloque_actual)
            bloque_actual = {"numero": int(m.group(1)), "filas": filas}
        elif bloque_actual is not None:
            # Continuación de la tabla de semana anterior, partida por Word.
            bloque_actual["filas"].extend(filas)
    if bloque_actual is not None:
        bloques.append(bloque_actual)

    unidades = []
    for bloque in bloques:
        campos = {"objetivos": "", "contenidos": "", "docente": "", "practico": "", "autonomo": ""}
        for celdas in bloque["filas"]:
            if len(celdas) < 2 or not celdas[0]:
                continue
            etiqueta = _normalizar(celdas[0])
            valor = next((c for c in celdas[1:] if c and c != celdas[0]), "")
            if not valor:
                continue
            if "resultados" in etiqueta and "aprendizaje" in etiqueta:
                campos["objetivos"] = valor
            elif "contenidos" in etiqueta:
                campos["contenidos"] = valor
            elif "actividades" in etiqueta:
                if "practico" in etiqueta or "practica" in etiqueta:
                    campos["practico"] = valor
                elif "autonomo" in etiqueta:
                    campos["autonomo"] = valor
                elif "docente" in etiqueta:
                    campos["docente"] = valor

        if not campos["contenidos"]:
            continue  # semana sin contenido real (ej. semana de solo evaluación)

        titulo = campos["contenidos"].split("\n")[0].strip() or f"Semana {bloque['numero']}"
        actividades = " | ".join(filter(None, [
            f"Docente: {campos['docente']}" if campos['docente'] else '',
            f"Práctico: {campos['practico']}" if campos['practico'] else '',
            f"Autónomo: {campos['autonomo']}" if campos['autonomo'] else '',
        ]))
        unidades.append({
            "numero": bloque["numero"], "titulo": titulo, "objetivos": campos["objetivos"],
            "contenido": campos["contenidos"], "actividades": actividades,
        })

    return sorted(unidades, key=lambda u: u["numero"])


def construir_unidades_reales(ruta_plan_docente: str, ruta_guia_estudio: str = None) -> list:
    """Prueba la estrategia A (párrafos) y, si no encuentra nada, la
    estrategia B (tablas por semana en el Plan Docente)."""
    unidades = _construir_unidades_estrategia_a(ruta_plan_docente, ruta_guia_estudio)
    if unidades:
        return unidades

    print("(No se encontró el formato de párrafos 'SEMANA N: ...' — probando el formato de "
          "tablas semanales del Plan Docente...)")
    return _construir_unidades_estrategia_b(ruta_plan_docente)


def construir_y_guardar(ruta_plan_docente: str, ruta_guia_estudio: str = None, codigo_override: str = None) -> str:
    """Construye la base completa (metadatos + unidades) y la guarda en MongoDB.
    Devuelve el código de asignatura bajo el cual quedó guardada."""
    metadatos = extraer_metadatos_plan_docente(ruta_plan_docente)
    codigo = codigo_override or metadatos.get("codigo", "").replace(" ", "_")
    if not codigo:
        raise ValueError(
            "No se pudo detectar el código de la asignatura en el Plan Docente, "
            "y no se pasó --codigo manualmente."
        )

    unidades = construir_unidades_reales(ruta_plan_docente, ruta_guia_estudio)
    if not unidades:
        raise ValueError(
            "No se encontraron semanas/unidades reconocibles en los documentos. "
            "Revisa que el Plan Docente use 'SEMANA N: ...' en párrafos, o una "
            "tabla por semana con encabezado 'Semana N'."
        )

    print(f"Asignatura detectada: {metadatos.get('asignatura', '(desconocida)')}")
    print(f"Código: {codigo} | Carrera: {metadatos.get('carrera', '?')} | Ciclo: {metadatos.get('ciclo', '?')}")
    print(f"Se construyeron {len(unidades)} unidades a partir de los documentos reales.")

    base = construir_base(
        asignatura=metadatos.get("asignatura", "(desconocida)"),
        codigo=codigo,
        carrera=metadatos.get("carrera", ""),
        ciclo=metadatos.get("ciclo", ""),
        unidades=unidades,
    )
    guardar_base(base)
    return codigo


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Construye la base de conocimiento de una asignatura de la UTPL.")
    parser.add_argument("--plan", help="Ruta al Plan Docente (.docx)")
    parser.add_argument("--guia", help="Ruta a la Guía de Estudio (.docx) — opcional, según la plantilla")
    parser.add_argument("--codigo", help="Forzar un código de asignatura (si no, se detecta del Plan Docente)")
    args = parser.parse_args()

    ruta_plan = args.plan or input("Ruta al Plan Docente (.docx) [data/Plan_Docente.docx]: ").strip() or "data/Plan_Docente.docx"
    ruta_guia = args.guia
    if ruta_guia is None:
        respuesta = input("Ruta a la Guía de Estudio (.docx), o Enter si no aplica [data/Guia_Estudio.docx]: ").strip()
        ruta_guia = respuesta or "data/Guia_Estudio.docx"
        import os
        if not os.path.exists(ruta_guia):
            ruta_guia = None

    codigo_final = construir_y_guardar(ruta_plan, ruta_guia, codigo_override=args.codigo)

    base_recuperada = cargar_base(codigo_final)
    print(f"\nVerificación: {len(base_recuperada['unidades'])} unidades guardadas en MongoDB bajo el código '{codigo_final}'.")
    for u in base_recuperada["unidades"]:
        print(f"  Unidad {u['numero']}: {u['titulo']}")