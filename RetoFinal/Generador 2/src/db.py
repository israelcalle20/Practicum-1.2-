"""
db.py — conexión centralizada a MongoDB para todo el pipeline.

Todas las demás piezas del proyecto (base_conocimiento.py, pipeline.py,
exportador.py, evaluador.py) importan get_db() desde aquí en lugar de
abrir sus propias conexiones.
"""
import os
from pymongo import MongoClient
from pymongo.database import Database
from dotenv import load_dotenv

load_dotenv()

_client = None
_db = None


def get_db() -> Database:
    """Devuelve (y cachea) la conexión a la base de datos MongoDB."""
    global _client, _db
    if _db is None:
        uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGODB_DB_NAME", "generador_recursos")
        _client = MongoClient(uri)
        _db = _client[db_name]
    return _db


def cerrar_conexion():
    global _client
    if _client is not None:
        _client.close()
        _client = None
