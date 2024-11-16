import os
import json
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, AsyncGenerator
import httpx
from starlette.responses import Response

app = FastAPI()

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especifica los orígenes permitidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Obtener la URL del servidor LLM desde una variable de entorno
LLM_SERVER_URL = os.environ.get("LLM_SERVER_URL", "http://localhost:11434")

class Query(BaseModel):
    """Modelo para las solicitudes a la API."""
    prompt: str
    model: str = "llama2"
    stream: Optional[bool] = True

async def stream_response(response: httpx.Response) -> AsyncGenerator[str, None]:
    """
    Procesa la respuesta streaming de forma segura.
    
    Args:
        response: La respuesta de httpx en modo streaming
        
    Yields:
        str: Fragmentos de la respuesta procesada
    """
    try:
        async for chunk in response.aiter_bytes():
            if chunk:
                try:
                    decoded_chunk = chunk.decode('utf-8')
                    for line in decoded_chunk.split('\n'):
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if "response" in data:
                                    yield data["response"]
                            except json.JSONDecodeError:
                                continue
                except UnicodeDecodeError:
                    continue
    except httpx.HTTPError as e:
        yield f"Error durante el streaming: {str(e)}"
    except Exception as e:
        yield f"Error inesperado: {str(e)}"

async def stream_generated_text(prompt: str, model: str) -> AsyncGenerator[str, None]:
    """
    Genera texto de forma asíncrona a partir del modelo de lenguaje.
    
    Args:
        prompt: El prompt para el modelo
        model: El nombre del modelo a utilizar
        
    Yields:
        str: Fragmentos de la respuesta del modelo
    """
    url = f"{LLM_SERVER_URL}/api/generate"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json={"model": model, "prompt": prompt}) as response:
                if response.status_code != 200:
                    # Leer el contenido del error de forma segura
                    error_content = await response.aread()
                    try:
                        error_text = error_content.decode('utf-8')
                    except UnicodeDecodeError:
                        error_text = "Error al decodificar la respuesta"
                        
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error al conectar con el servidor LLM: {response.status_code} - {error_text}"
                    )
                
                async for text in stream_response(response):
                    yield text

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error de comunicación con el servidor LLM: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error inesperado: {str(e)}"
        )

@app.post("/api/generate")
async def generate_text(query: Query) -> Response:
    """
    Endpoint para generar texto a partir de un prompt.
    
    Args:
        query: La solicitud con el prompt y la configuración
        
    Returns:
        StreamingResponse o JSONResponse según la configuración
    """
    if query.stream:
        return StreamingResponse(
            stream_generated_text(query.prompt, query.model),
            media_type="text/plain",
        )
    else:
        # Para respuestas no streaming
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{LLM_SERVER_URL}/api/generate",
                    json={"model": query.model, "prompt": query.prompt}
                )
                response.raise_for_status()
                return JSONResponse(response.json())
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error al generar respuesta: {str(e)}"
            )

@app.post("/api/models/download")
async def download_model(llm_name: str = Body(..., embed=True)):
    """Endpoint para descargar un modelo de lenguaje."""
    url = f"{LLM_SERVER_URL}/api/pull"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={"name": llm_name})
            response.raise_for_status()
            return {"message": f"Model {llm_name} downloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al descargar el modelo: {str(e)}")

@app.get("/api/models")
async def list_models():
    """Endpoint para listar los modelos disponibles."""
    url = f"{LLM_SERVER_URL}/api/tags"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return {"models": response.json()["models"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener la lista de modelos: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3335)