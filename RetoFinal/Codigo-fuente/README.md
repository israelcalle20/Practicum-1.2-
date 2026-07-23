# Generador de Recursos Didácticos con IA

Sistema que, a partir del Plan Docente (y opcionalmente la Guía de Estudio)
de cualquier asignatura de la UTPL, genera automáticamente cuatro recursos
didácticos por unidad —resumen ejecutivo, glosario de términos, banco de
preguntas organizado por nivel de Bloom y actividad de reflexión práctica—
usando la API de Google Gemini, y los exporta a un documento Word listo
para el EVA. Incluye evaluación automática de calidad (LLM-as-Judge) y una
interfaz web para operar todo sin necesidad de la terminal.

MongoDB Atlas se usa como capa de persistencia central: guarda la base de
conocimiento curricular, los recursos JSON generados por cada prompt, los
reportes de evaluación, el feedback del docente titular, y un registro
auditable de cada llamada realizada a Gemini. Gracias a esto, el pipeline
se puede interrumpir en cualquier momento (por ejemplo, al agotarse la
cuota gratuita de la API) y reanudarse después sin perder ni repetir
trabajo ya hecho.

## Cómo funciona

```
Plan Docente + Guía  →  extractor.py  →  construir_base_real.py  →  MongoDB (asignaturas)
                                                                          │
                                                                          ▼
                                                    pipeline.py + prompts.py  ⇄  Gemini
                                                                          │
                                                                          ▼
                                                        MongoDB (recursos, prompts_usados)
                                                                          │
                                                                          ▼
                                              exportador.py  →  Word final (recursos_CODIGO.docx)

                                              evaluador.py  ⇄  Gemini  →  MongoDB (evaluaciones, feedback_docente)
```

1. **Lectura del documento** — `extractor.py` abre el Plan Docente (y la
   Guía de Estudio, si existe) y saca dos cosas: el texto de cada unidad,
   y los metadatos de la asignatura (código, carrera, ciclo) buscando por
   palabra clave en la tabla de "Datos Básicos", sin importar cuál de las
   plantillas de la UTPL se haya usado.

2. **Construcción de la base de conocimiento** — `construir_base_real.py`
   prueba dos formas de encontrar las unidades dentro del documento
   (encabezados de párrafo tipo `SEMANA N:`, o una tabla independiente por
   cada semana) y usa la que sí encuentre resultados. El resultado —código,
   carrera, ciclo y el contenido de cada unidad— se guarda en MongoDB
   (colección `asignaturas`) con `upsert`, así que volver a correrlo no
   duplica nada.

3. **Generación con Gemini** — `pipeline.py` recorre cada unidad y llama,
   una por una, a las 4 funciones de `prompts.py`. Cada llamada especifica
   a Gemini un `response_schema` obligatorio, de modo que la respuesta
   siempre llega en un JSON con la misma forma (por ejemplo, el glosario
   siempre es una lista de `{termino, definicion}`), sin necesidad de
   interpretar texto libre. Antes de generar, `pipeline.py` revisa si ese
   recurso ya existe en MongoDB — si existe, lo salta, para no gastar
   cuota regenerando lo que ya está listo.

4. **Manejo de errores de la API** — si Gemini responde 429 (cuota) o 503
   (saturado), `prompts.py` espera un poco más en cada intento (15 s, 30 s,
   45 s, 60 s) y reintenta, hasta 5 veces. Si la cuota se agotó de verdad,
   se detiene con un mensaje claro (`CuotaAgotadaError`) en vez de un
   traceback, y lo que ya se generó queda guardado — la siguiente corrida
   retoma justo ahí.

5. **Exportación** — cuando todas las unidades tienen sus 4 recursos,
   `exportador.py` los lee desde MongoDB (sin volver a llamar a Gemini) y
   arma el documento Word: una portada, una sección por unidad, y dentro
   de cada una sus 4 subsecciones con el formato correspondiente (tabla
   para el glosario, preguntas numeradas por nivel de Bloom, etc.).

6. **Evaluación de calidad** — de forma independiente, `evaluador.py` le
   pide al mismo Gemini que actúe como juez (LLM-as-Judge): puntúa cada
   recurso del 1 al 5 contra criterios específicos de su tipo (¿el resumen
   inventó algo que no está en el material? ¿el glosario tiene términos
   genéricos?), y guarda el reporte en MongoDB junto con el feedback que
   el docente titular quiera registrar.

7. **Interfaz web** — `pantallas.py` no tiene lógica propia: simplemente
   llama a las funciones de los pasos 1, 3 y 5 según en qué pantalla esté
   el usuario (Cargar documentos → Generar recursos → Descargar), y
   muestra el progreso y el estado con barras y mensajes en vez de texto
   en la terminal.

## Estructura

```
generador_recursos/
├── .env                        # GEMINI_API_KEY, MONGODB_URI, MONGODB_DB_NAME
├── .env.example
├── .gitignore
├── requirements.txt
├── diagrama_arquitectura.svg
├── data/
│   ├── Plan_Docente.docx
│   ├── Guia_Estudio.docx       # opcional, según la plantilla del Plan Docente
│   └── materiales/
├── src/
│   ├── db.py                   # conexión reutilizada a MongoDB
│   ├── extractor.py            # extrae texto (PDF/Word) y metadatos del Plan Docente
│   ├── base_conocimiento.py    # funciones genéricas (construir_base/guardar_base/cargar_base)
│   ├── construir_base_real.py  # detecta plantilla y construye la base de conocimiento real
│   ├── prompts.py               # los 4 generadores + manejo de cuota/reintentos
│   ├── pipeline.py              # orquestador: genera, guarda, reanuda, exporta
│   ├── exportador.py            # ensambla el documento Word final
│   ├── evaluador.py             # LLM-as-Judge + registro de feedback docente
│   ├── pantallas.py             # interfaz web (Streamlit)
│   ├── test_conexion.py         # utilidad: prueba Mongo + Gemini
│   └── probar_una_unidad.py     # utilidad: prueba el pipeline con una sola unidad
└── README.md
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # y completa tus valores reales
```

Necesitas:
- Una API key de Gemini (gratis en [Google AI Studio](https://aistudio.google.com/apikey)).
- Una base de datos en [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) (tier gratuito M0 es suficiente), con tu IP autorizada en **Network Access** y un usuario creado en **Database Access**.

Tu `.env` debe verse así:
```
GEMINI_API_KEY=tu_api_key_real
MONGODB_URI=mongodb+srv://usuario:password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0
MONGODB_DB_NAME=generador_recursos
```

Antes de nada, verifica que ambas conexiones respondan:
```bash
python src/test_conexion.py
```

## Uso

```bash
streamlit run src/pantallas.py
```

Se abre en el navegador con tres pasos: **cargar documentos** (sube el Plan
Docente y, si la tienes, la Guía de Estudio), **generar recursos** (elige
unidades y, opcionalmente, personaliza instrucciones para Gemini) y
**descargar** (con el estado —completo / parcial / vacío— de cada
asignatura guardada).

## Colecciones de MongoDB

| Colección          | Contenido                                                                 |
|---------------------|----------------------------------------------------------------------------|
| `asignaturas`        | Base de conocimiento: código, carrera, ciclo y unidades con su contenido    |
| `recursos`            | JSON de cada uno de los 4 recursos, indexado por asignatura/unidad/tipo     |
| `evaluaciones`        | Reportes del evaluador LLM-as-Judge, por unidad                            |
| `prompts_usados`      | Cada llamada a Gemini (éxito o fallo) con el prompt exacto enviado          |
| `feedback_docente`    | Observaciones del docente titular y mejoras aplicadas                       |

## Notas técnicas

- El SDK usado es `google-genai` (el paquete `google-generativeai` y los
  modelos `gemini-1.5-*` y `gemini-2.5-*` están descontinuados). El modelo
  por defecto es `gemini-flash-latest`; ajusta `MODEL_NAME` en `prompts.py`
  y `evaluador.py` si tienes acceso a uno más reciente.
- Todos los prompts fuerzan `response_mime_type="application/json"` con
  `response_schema`, para que el exportador y el evaluador reciban siempre
  la misma estructura sin necesidad de parsear texto libre.
- Ante un error 429 (cuota) o 503 (servicio saturado), el sistema reintenta
  con espera progresiva (15s, 30s, 45s, 60s) hasta 5 veces. Si la cuota
  gratuita se agota por completo, se levanta `CuotaAgotadaError` —un
  mensaje claro en vez de un traceback— y el proceso se detiene sin perder
  lo ya generado.
- `construir_base_real.py` prueba dos estrategias de lectura del Plan
  Docente (encabezados de párrafo o una tabla por semana) y usa la que
  encuentre resultados, sin que el usuario tenga que indicar cuál aplica.
- `base_conocimiento.py` queda como plantilla genérica de referencia (útil
  si algún día quieres construir una base de conocimiento sin depender de
  documentos reales); el flujo real siempre pasa por
  `construir_base_real.py`.
