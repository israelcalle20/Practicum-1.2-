"""
test_conexion.py — corre esto primero para verificar que MONGODB_URI y
GEMINI_API_KEY están bien configurados en tu .env, antes de lanzar el
pipeline completo.

Uso: python src/test_conexion.py
"""
import os
from dotenv import load_dotenv

load_dotenv()


def probar_mongo():
    print("Probando conexión a MongoDB...")
    try:
        from db import get_db
        db = get_db()
        db.command("ping")
        print(f"  OK — conectado a la base '{db.name}'.")
        return True
    except Exception as e:
        print(f"  FALLÓ: {e}")
        print("  Revisa MONGODB_URI en tu .env (usuario, password, y que tu IP")
        print("  esté en la whitelist de Network Access si usas Atlas).")
        return False


def probar_gemini():
    print("Probando conexión a Gemini...")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("  FALLÓ: no se encontró GEMINI_API_KEY en tu .env.")
        return False
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        respuesta = client.models.generate_content(
            model="gemini-flash-latest",
            contents="Responde únicamente con la palabra: ok",
        )
        print(f"  OK — Gemini respondió: {respuesta.text.strip()}")
        return True
    except Exception as e:
        print(f"  FALLÓ: {e}")
        print("  Revisa que GEMINI_API_KEY sea válida en https://aistudio.google.com/apikey")
        return False


if __name__ == "__main__":
    mongo_ok = probar_mongo()
    print()
    gemini_ok = probar_gemini()
    print()
    if mongo_ok and gemini_ok:
        print("Todo listo. Ya puedes correr base_conocimiento.py y luego pipeline.py.")
    else:
        print("Corrige lo anterior antes de seguir.")
