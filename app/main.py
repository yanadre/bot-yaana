import os
from contextlib import asynccontextmanager

import requests
from fastapi import Body, FastAPI, Request
from qdrant_client import models, QdrantClient

from app.schemas import *


VECTOR_SIZE = 768 # GEMINI


# ----------------------------
# Lifespan for startup/shutdown
# ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: logic to run before the app starts
    print("Application is starting up...")

    # Initialize Qdrant client
    app.state.qdrant_client = QdrantClient(
        host=os.getenv("QDRANT_HOST"),
        port=int(os.getenv("QDRANT_PORT"))
    )
    print("Qdrant client initialized.")

    qdrant_client = app.state.qdrant_client
    collection_name = os.getenv("QDRANT_COLLECTION_NAME")

    # Check if collection exists
    
    if not qdrant_client.collection_exists(collection_name):
        print(f"Creating collection: {collection_name}")
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            ),
        )
    else:
        print(f"Collection '{collection_name}' already exists")

    yield  # The app is now running and serving requests

    # Shutdown: logic to run after the app stops
    print("Application is shutting down...")


# ----------------------------
# FastAPI app instance
# ----------------------------
app = FastAPI(lifespan=lifespan)


# ----------------------------
# Health check endpoint
# ----------------------------
@app.get("/health")
async def health_check():
    return {"status": "OK"}

@app.get("/api/v1/qdrant-test") # move to the span initialization / health check -> 2 fields in the return 
async def qdrant_test():
    qdrant_client: QdrantClient = app.state.qdrant_client

    try:
        collections = qdrant_client.get_collections()
        return {"status": "OK", "collections": collections}
    except Exception as e:
        return {"status": "ERROR", "details": str(e)}



TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()

    print(data)
    
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "")

    
    # Call your bot logic functions here
    response_text = f"You said: {text}"
    
    # Send reply to Telegram
    requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": response_text
    })
    
    return {"ok": True}





# # ----------------------------
# # Chat endpoint (mock for now)
# # ----------------------------
# @app.post("/api/v1/chat", response_model=ChatResponse, tags=["ChatBot"])
# async def ask_chatbot(request: ChatRequest = Body(...)):
#     # Access Qdrant client if needed later
#     qdrant_client: QdrantClient = app.state.qdrant_client

#     # Temporary response
#     return {"message": f"Hello, your request is '{request.message}'"}


# # ----------------------------
# # Text ingestion endpoint (mock for now)
# # ----------------------------
# @app.post("/api/v1/ingest/text", response_model=TextIngestResponse, tags=["ChatBot"])
# async def add_item(request: TextIngestRequest = Body(...)):
#     # Access Qdrant client if needed later
#     qdrant_client: QdrantClient = app.state.qdrant_client

#     # Temporary ingestion response
#     return {"status": True}


