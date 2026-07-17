"""
pantallas.py — interfaz web del generador de recursos didácticos, con Streamlit.

Tres pasos secuenciales, navegados con un stepper (no pestañas):
1. Cargar documentos: subir Plan Docente (y opcionalmente Guía de
   Estudio), construir y guardar la base de conocimiento en MongoDB.
2. Generar recursos: elegir la asignatura y las unidades a procesar,
   escribir instrucciones adicionales opcionales por tipo de recurso,
   y lanzar la generación con Gemini (con barra de progreso).
3. Descargar: bajar el documento Word ya generado.

Uso:
    streamlit run src/pantallas.py
"""
import tempfile
from pathlib import Path

import streamlit as st

from db import get_db
from construir_base_real import construir_y_guardar
from base_conocimiento import cargar_base
from pipeline import ejecutar_pipeline
from prompts import CuotaAgotadaError

st.set_page_config(page_title="Generador de recursos didácticos", layout="wide")

# ─────────────────────────────────────────────────────────────────────────
# ESTILO
# ─────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --ink: #0B0F14;
    --surface: #131920;
    --surface-2: #1A222C;
    --border-subtle: #262F3B;
    --text-primary: #ECEEF1;
    --text-muted: #838EA0;
    --accent: #CDA349;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background-color: var(--ink); }
#MainMenu, header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem !important; max-width: 1000px; }

h1, h2, h3 { font-family: 'Source Serif 4', serif !important; letter-spacing: -0.01em; color: var(--text-primary); }

/* ── Hero ─────────────────────────────────────────────────────────── */
.hero { position: relative; padding-bottom: 1.6rem; margin-bottom: 1.8rem; border-bottom: 1px solid var(--border-subtle); }
.hero-marca {
    position: absolute; top: -0.6rem; right: 0;
    font-family: 'Source Serif 4', serif; font-weight: 700; font-size: 5.5rem;
    color: var(--accent); opacity: 0.07; line-height: 1; user-select: none;
}
.hero h1 { font-size: 2.3rem !important; font-weight: 600 !important; margin: 0 0 0.35rem 0 !important; }
.hero p.subt { color: var(--text-muted); font-size: 1rem; margin: 0; max-width: 640px; }

/* ── Franja de estadísticas ───────────────────────────────────────── */
.stat-row { display: flex; gap: 2.2rem; margin-top: 1.3rem; }
.stat-item .num { font-family: 'Source Serif 4', serif; font-size: 1.9rem; font-weight: 600; color: var(--accent); line-height: 1; }
.stat-item .lbl { font-family: 'JetBrains Mono', monospace; font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-muted); margin-top: 0.2rem; }

/* ── Stepper (segmented control estilizado como pasos conectados) ──── */
div[data-testid="stSegmentedControl"] { margin-bottom: 1.6rem; }
div[data-testid="stSegmentedControl"] label {
    background-color: transparent !important;
    border: none !important;
    border-bottom: 2px solid var(--border-subtle) !important;
    border-radius: 0 !important;
    color: var(--text-muted) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.06em !important;
    padding: 0.55rem 0.2rem !important;
    margin-right: 2.4rem !important;
}
div[data-testid="stSegmentedControl"] label[data-checked="true"] {
    color: var(--accent) !important;
    border-bottom-color: var(--accent) !important;
}

/* ── Paneles (contenedores nativos con borde) ────────────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: var(--surface) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 4px !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] > div { padding: 0.4rem 0.3rem; }
.panel-titulo { font-size: 1.25rem !important; margin-top: 0 !important; margin-bottom: 0.3rem !important; }
.panel-desc { color: var(--text-muted); font-size: 0.88rem; margin-bottom: 1.1rem; }

/* ── Botones ──────────────────────────────────────────────────────── */
button[kind="primary"] {
    background-color: var(--accent) !important; color: var(--ink) !important;
    border: none !important; border-radius: 3px !important; font-weight: 600 !important;
    letter-spacing: 0.01em;
}
button[kind="primary"]:hover { background-color: #B8923D !important; }
button[kind="secondary"] { border-radius: 3px !important; border-color: var(--border-subtle) !important; }

/* ── Inputs / uploaders / expanders ──────────────────────────────── */
[data-testid="stFileUploaderDropzone"] {
    background-color: var(--surface-2) !important; border: 1px dashed var(--border-subtle) !important;
    border-radius: 3px !important;
}
[data-testid="stExpander"] { border: 1px solid var(--border-subtle) !important; border-radius: 3px !important; background-color: var(--surface-2) !important; }
[data-baseweb="select"] > div { background-color: var(--surface-2) !important; border-color: var(--border-subtle) !important; border-radius: 3px !important; }
textarea, input { border-radius: 3px !important; }

code, .mono { font-family: 'JetBrains Mono', monospace !important; }
hr { border-color: var(--border-subtle) !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
# HERO + ESTADÍSTICAS EN VIVO
# ─────────────────────────────────────────────────────────────────────────
try:
    _db = get_db()
    _asignaturas = list(_db.asignaturas.find({}, {"_id": 0, "codigo": 1, "unidades": 1}))
    _n_asignaturas = len(_asignaturas)
    _n_unidades = sum(len(a.get("unidades", [])) for a in _asignaturas)
    _n_recursos = _db.recursos.count_documents({})
except Exception:
    _n_asignaturas = _n_unidades = _n_recursos = 0

st.markdown(f"""
<div class="hero">
  <div class="hero-marca">GD</div>
  <h1>Generador de recursos didácticos</h1>
  <p class="subt">Plan Docente + Guía de Estudio &rarr; resumen, glosario, preguntas y actividad
  por unidad, generados con Gemini y guardados en MongoDB.</p>
  <div class="stat-row">
    <div class="stat-item"><div class="num">{_n_asignaturas}</div><div class="lbl">Asignaturas</div></div>
    <div class="stat-item"><div class="num">{_n_unidades}</div><div class="lbl">Unidades</div></div>
    <div class="stat-item"><div class="num">{_n_recursos}</div><div class="lbl">Recursos generados</div></div>
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
# STEPPER
# ─────────────────────────────────────────────────────────────────────────
paso = st.segmented_control(
    "Paso", ["01 · Cargar documentos", "02 · Generar recursos", "03 · Descargar"],
    default="01 · Cargar documentos", label_visibility="collapsed",
)
if paso is None:
    paso = "01 · Cargar documentos"


# ─────────────────────────────────────────────────────────────────────────
# PASO 1: CARGAR DOCUMENTOS
# ─────────────────────────────────────────────────────────────────────────
if paso.startswith("01"):
    with st.container(border=True):
        st.markdown('<p class="panel-titulo">Sube el Plan Docente</p>', unsafe_allow_html=True)
        st.markdown('<p class="panel-desc">La Guía de Estudio es opcional: algunas plantillas de la '
                    'UTPL ya traen todo el contenido semanal dentro del Plan Docente.</p>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            archivo_plan = st.file_uploader("Plan Docente (.docx) — obligatorio", type=["docx"], key="plan")
        with col2:
            archivo_guia = st.file_uploader("Guía de Estudio (.docx) — opcional", type=["docx"], key="guia")

        if st.button("Construir base de conocimiento", type="primary", disabled=not archivo_plan):
            with st.spinner("Leyendo documentos y guardando en MongoDB..."):
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        ruta_plan = Path(tmp) / "plan_docente.docx"
                        ruta_plan.write_bytes(archivo_plan.getvalue())
                        ruta_guia = None
                        if archivo_guia:
                            ruta_guia = Path(tmp) / "guia_estudio.docx"
                            ruta_guia.write_bytes(archivo_guia.getvalue())
                            ruta_guia = str(ruta_guia)

                        codigo = construir_y_guardar(str(ruta_plan), ruta_guia)

                    base = cargar_base(codigo)
                    st.session_state["codigo_actual"] = codigo
                    st.success(f"Base de conocimiento guardada — código {codigo}")
                    st.markdown(f"**Asignatura:** {base['asignatura']}  \n"
                                f"**Carrera:** {base['carrera']}  \n"
                                f"**Ciclo:** {base['ciclo']}")
                    st.markdown("**Unidades detectadas**")
                    for u in base["unidades"]:
                        st.write(f"— Unidad {u['numero']}: {u['titulo']}")
                except Exception as e:
                    st.error(f"No se pudo construir la base de conocimiento: {e}")

    with st.container(border=True):
        st.markdown('<p class="panel-titulo">Asignaturas guardadas</p>', unsafe_allow_html=True)
        try:
            db = get_db()
            asignaturas = list(db.asignaturas.find({}, {"_id": 0, "codigo": 1, "asignatura": 1, "unidades": 1}))
            if asignaturas:
                for a in asignaturas:
                    st.markdown(f"`{a['codigo']}` — {a['asignatura']} · {len(a.get('unidades', []))} unidades")
            else:
                st.caption("Todavía no hay ninguna asignatura guardada.")
        except Exception as e:
            st.warning(f"No se pudo conectar a MongoDB: {e}")


# ─────────────────────────────────────────────────────────────────────────
# PASO 2: GENERAR RECURSOS
# ─────────────────────────────────────────────────────────────────────────
elif paso.startswith("02"):
    with st.container(border=True):
        st.markdown('<p class="panel-titulo">Genera los recursos con Gemini</p>', unsafe_allow_html=True)

        try:
            db = get_db()
            codigos_disponibles = [a["codigo"] for a in db.asignaturas.find({}, {"_id": 0, "codigo": 1})]
        except Exception as e:
            codigos_disponibles = []
            st.warning(f"No se pudo conectar a MongoDB: {e}")

        if not codigos_disponibles:
            st.info("Primero carga una asignatura en el paso 01.")
        else:
            codigo_default = st.session_state.get("codigo_actual", codigos_disponibles[0])
            codigo = st.selectbox(
                "Asignatura", codigos_disponibles,
                index=codigos_disponibles.index(codigo_default) if codigo_default in codigos_disponibles else 0,
            )
            base = cargar_base(codigo)

            opciones_unidades = {f"Unidad {u['numero']}: {u['titulo']}": u["numero"] for u in base["unidades"]}
            seleccion = st.multiselect(
                "Unidades a procesar", list(opciones_unidades.keys()),
                default=list(opciones_unidades.keys()),
            )
            unidades_seleccionadas = [opciones_unidades[s] for s in seleccion]

            forzar = st.checkbox(
                "Regenerar aunque ya exista (por defecto se omite lo ya generado, para no gastar cuota de más)",
                value=False,
            )

            with st.expander("Personalizar instrucciones para Gemini"):
                st.caption("Se agregan al final del prompt base de cada tipo de recurso. Déjalo vacío para usar el prompt estándar.")
                instr_resumen = st.text_area("Resumen", key="instr_resumen")
                instr_glosario = st.text_area("Glosario", key="instr_glosario")
                instr_preguntas = st.text_area("Preguntas", key="instr_preguntas")
                instr_actividad = st.text_area("Actividad", key="instr_actividad")

            instrucciones_por_tipo = {
                "resumen": instr_resumen, "glosario": instr_glosario,
                "preguntas": instr_preguntas, "actividad": instr_actividad,
            }

            if st.button("Generar recursos", type="primary", disabled=not unidades_seleccionadas):
                total_pasos = len(unidades_seleccionadas) * 4
                barra = st.progress(0.0)
                estado_texto = st.empty()
                pasos_hechos = {"n": 0}

                def callback_paso(numero_unidad, tipo, estado):
                    if estado in ("listo", "omitido"):
                        pasos_hechos["n"] += 1
                    estado_texto.markdown(f"`Unidad {numero_unidad} · {tipo} · {estado}`")
                    barra.progress(min(pasos_hechos["n"] / total_pasos, 1.0))

                try:
                    ruta_salida = f"data/recursos_{codigo}.docx"
                    Path("data").mkdir(exist_ok=True)
                    with st.spinner("Generando con Gemini — esto puede tardar varios minutos."):
                        ejecutar_pipeline(
                            codigo_asignatura=codigo, ruta_salida_docx=ruta_salida, forzar=forzar,
                            unidades_seleccionadas=unidades_seleccionadas,
                            instrucciones_por_tipo=instrucciones_por_tipo, callback_paso=callback_paso,
                        )
                    st.session_state["ruta_docx_generado"] = ruta_salida
                    st.session_state["codigo_actual"] = codigo
                    st.success("Listo — ve al paso 03 para descargar el documento.")
                except CuotaAgotadaError as e:
                    st.error(str(e))
                    st.info("Lo que ya se alcanzó a generar quedó guardado. Cuando vuelvas a generar "
                            "para la misma asignatura, retoma justo donde se quedó.")
                except Exception as e:
                    st.error(f"Ocurrió un error inesperado: {e}")


# ─────────────────────────────────────────────────────────────────────────
# PASO 3: DESCARGAR
# ─────────────────────────────────────────────────────────────────────────
else:
    with st.container(border=True):
        st.markdown('<p class="panel-titulo">Estado por asignatura</p>', unsafe_allow_html=True)
        st.markdown('<p class="panel-desc">Recursos generados y si ya existe un Word listo para descargar en disco.</p>',
                    unsafe_allow_html=True)

        try:
            db = get_db()
            asignaturas = list(db.asignaturas.find({}, {"_id": 0, "codigo": 1, "asignatura": 1, "unidades": 1}))
        except Exception as e:
            asignaturas = []
            st.warning(f"No se pudo conectar a MongoDB: {e}")

        if not asignaturas:
            st.info("Todavía no hay ninguna asignatura cargada. Ve al paso 01.")
        else:
            for a in asignaturas:
                codigo = a["codigo"]
                n_unidades = len(a.get("unidades", []))
                n_esperados = n_unidades * 4
                n_generados = db.recursos.count_documents({"codigo_asignatura": codigo})
                completo = n_generados >= n_esperados and n_esperados > 0
                ruta_docx = Path(f"data/recursos_{codigo}.docx")
                archivo_listo = ruta_docx.exists()

                col_info, col_estado, col_accion = st.columns([3, 2, 2])
                with col_info:
                    st.markdown(f"**{codigo}** — {a['asignatura']}")
                    st.caption(f"{n_unidades} unidades")
                with col_estado:
                    if completo:
                        st.markdown(":green[Completo] · " + f"`{n_generados}/{n_esperados}` recursos")
                    elif n_generados > 0:
                        st.markdown(":orange[Parcial] · " + f"`{n_generados}/{n_esperados}` recursos")
                    else:
                        st.markdown(":gray[Vacío] · " + "`0` recursos")
                with col_accion:
                    if archivo_listo:
                        with open(ruta_docx, "rb") as f:
                            st.download_button(
                                "Descargar", data=f.read(), file_name=ruta_docx.name,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                type="primary", key=f"descargar_{codigo}",
                            )
                    elif n_generados > 0:
                        if st.button("Exportar Word", key=f"exportar_{codigo}"):
                            from pipeline import obtener_recursos_unidad
                            from exportador import exportar_word

                            base = cargar_base(codigo)
                            unidades_recursos = []
                            for u in base["unidades"]:
                                recursos = obtener_recursos_unidad(codigo, u["numero"])
                                unidades_recursos.append({
                                    "numero": u["numero"], "titulo": u["titulo"],
                                    "resumen": recursos.get("resumen"), "glosario": recursos.get("glosario"),
                                    "preguntas": recursos.get("preguntas"), "actividad": recursos.get("actividad"),
                                })
                            Path("data").mkdir(exist_ok=True)
                            exportar_word(base["asignatura"], unidades_recursos, str(ruta_docx))
                            st.rerun()
                    else:
                        st.caption("Ve al paso 02")
                st.divider()