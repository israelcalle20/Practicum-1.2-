# Generador automático de recursos didácticos

Pipeline de prompts encadenados que, a partir del plan docente y los
materiales de una asignatura de la UTPL, genera automáticamente cuatro
recursos didácticos por unidad (resumen ejecutivo, glosario, preguntas
de comprensión y actividad de reflexión) usando la API de Gemini, y los
exporta a un documento Word listo para el EVA.

MongoDB se usa como capa de persistencia: guarda la base de conocimiento,
los recursos JSON generados por cada prompt, y los reportes de evaluación
y feedback del docente — así el pipeline no depende de mantener todo en
memoria ni de re-generar contenido ya producido en corridas anteriores.

## Estructura

```
generador_recursos/
├── .env                      # GEMINI_API_KEY, MONGODB_URI, MONGODB_DB_NAME
├── requirements.txt
├── data/
│   ├── plan_docente.pdf
│   ├── guia_didactica.pdf
│   └── materiales/            # un PDF o Word por unidad
├── src/
│   ├── db.py                  # conexión a MongoDB
│   ├── extractor.py            # extrae texto de PDF/Word
│   ├── base_conocimiento.py    # construye y persiste la base de conocimiento
│   ├── prompts.py               # los cuatro prompts (Gemini, salida JSON)
│   ├── pipeline.py              # orquestador: extrae → genera → exporta
│   ├── exportador.py            # ensambla el documento Word final
│   └── evaluador.py             # LLM-as-Judge + registro de feedback docente
└── README.md
```

## Instalación

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # y completa tus valores
```

Necesitas:
- Una API key de Gemini (gratis en [Google AI Studio](https://aistudio.google.com)).
- MongoDB corriendo local (`mongod`) o una base gratuita en MongoDB Atlas.

## Uso

1. Coloca tus PDFs/Word en `data/` y `data/materiales/`.
2. Construye y guarda la base de conocimiento:
   ```bash
   python src/base_conocimiento.py
   ```
3. Corre el pipeline completo (genera los 4 recursos por unidad y exporta el Word):
   ```bash
   python src/pipeline.py
   ```
4. Evalúa la calidad de los recursos de una unidad:
   ```bash
   python -c "from src.evaluador import evaluar_unidad; evaluar_unidad('INF101', 1)"
   ```
5. Registra el feedback del docente titular (ver ejemplo al final de `evaluador.py`).

## Colecciones de MongoDB

| Colección          | Contenido                                                        |
|---------------------|-------------------------------------------------------------------|
| `asignaturas`        | Base de conocimiento: asignatura + unidades con su contenido       |
| `recursos`            | JSON de cada uno de los 4 recursos, por unidad                     |
| `evaluaciones`        | Reportes del evaluador LLM-as-Judge, por unidad                    |
| `feedback_docente`    | Observaciones del docente titular y mejoras aplicadas               |

## Notas técnicas

- El SDK usado es `google-genai` (el paquete `google-generativeai` y los
  modelos `gemini-1.5-*` están descontinuados). El modelo por defecto es
  `gemini-2.5-flash`; ajusta `MODEL_NAME` en `prompts.py` y `evaluador.py`
  si tienes acceso a uno más reciente.
- Todos los prompts fuerzan `response_mime_type="application/json"` con
  `response_schema`, para que el exportador y el evaluador reciban
  siempre la misma estructura sin necesidad de parsear texto libre.
