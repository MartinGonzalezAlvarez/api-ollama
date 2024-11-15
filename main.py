import os
import json
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import httpx

app = FastAPI()

# Obtener la URL del servidor LLM desde una variable de entorno
LLM_SERVER_URL = os.environ.get("LLM_SERVER_URL", "http://localhost:11434")  

class Query(BaseModel):
    """
    Modelo para las solicitudes a la API.
    """
    prompt: str
    model: str = "llama2"
    stream: Optional[bool] = True  # Por defecto, se utiliza streaming

# Async generator para extraer "response" de /api/generate (Streaming)
async def stream_generated_text(prompt: str, model: str):
    """
    Genera texto de forma asíncrona a partir del modelo de lenguaje.

    Args:
        prompt (str): El prompt para el modelo.
        model (str): El nombre del modelo a utilizar.

    Yields:
        str: Fragmentos de la respuesta del modelo.
    """
    url = f"{LLM_SERVER_URL}/api/generate"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", url, json={"model": model, "prompt": prompt}) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error al conectar con el servidor LLM: {response.status_code} - {response.text}"
                    )

                # Se itera sobre los fragmentos de la respuesta y se extrae el contenido de "response"
                async for chunk in response.aiter_bytes():
                    decoded_chunk = chunk.decode('utf-8')
                    for line in decoded_chunk.split("\n\n"):
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if "response" in data:
                                    yield data["response"]
                            except json.JSONDecodeError:
                                continue  # Se ignoran los fragmentos JSON inválidos

        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Error de comunicación con el servidor LLM: {e}")

# Función auxiliar para obtener la respuesta completa de /api/generate (sin streaming)
async def get_generated_text(prompt: str, model: str):
    """
    Obtiene el texto completo generado por el modelo de lenguaje.

    Args:
        prompt (str): El prompt para el modelo.
        model (str): El nombre del modelo a utilizar.

    Returns:
        dict: Un diccionario con la respuesta del modelo.
    """
    url = f"{LLM_SERVER_URL}/api/generate"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, json={"model": model, "prompt": prompt})
            response.raise_for_status()

            # Se combinan todas las respuestas en una sola cadena
            combined_response = ""
            for line in response.text.splitlines():
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "response" in data:
                            combined_response += data["response"]
                    except json.JSONDecodeError:
                        continue  # Se ignoran los fragmentos JSON inválidos

            return {"response": combined_response}

        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Error de comunicación con el servidor LLM: {e}")

# Endpoint para /generate que maneja tanto streaming como no streaming
@app.post("/api/generate")
async def generate_text(query: Query):
    """
    Endpoint para generar texto a partir de un prompt.

    Args:
        query (Query): La solicitud con el prompt y la configuración.

    Returns:
        StreamingResponse o JSONResponse: La respuesta del modelo, en streaming o completa.
    """
    if query.stream:
        return StreamingResponse(
            stream_generated_text(query.prompt, query.model),
            media_type="text/plain"
        )
    else:
        response = await get_generated_text(query.prompt, query.model)
        return JSONResponse(response)

# Endpoint para /models/download que maneja la descarga de modelos
@app.post("/api/models/download")
async def download_model(llm_name: str = Body(..., embed=True)):
    """
    Endpoint para descargar un modelo de lenguaje.

    Args:
        llm_name (str): El nombre del modelo a descargar.

    Returns:
        dict: Un diccionario con un mensaje de éxito o error.
    """
    url = f"{LLM_SERVER_URL}/api/pull"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={"name": llm_name})
            response.raise_for_status()  # Lanza una excepción si la solicitud falla
            return {"message": f"Model {llm_name} downloaded successfully"}
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Error al descargar el modelo: {e}")

# Endpoint para /models que lista los modelos disponibles
@app.get("/api/models")
async def list_models():
    """
    Endpoint para listar los modelos de lenguaje disponibles.

    Returns:
        dict: Un diccionario con la lista de modelos.
    """
    url = f"{LLM_SERVER_URL}/api/tags"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()  # Lanza una excepción si la solicitud falla
            return {"models": response.json()["models"]}
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener la lista de modelos: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)