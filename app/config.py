from pydantic_settings import BaseSettings, SettingsConfigDict

from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    # qdrant
    QDRANT_HOST: str 
    QDRANT_PORT: int  
    QDRANT_COLLECTION_NAME: str = "documents_tests"   

    # telegram
    TELEGRAM_TOKEN: str     
    AUTHORIZED_ID: int 

    # embedding
    GOOGLE_API_KEY: str
    EMBEDDING_MODEL_NAME: str = "gemini-embedding-001"
    EMBEDDING_VECTOR_SIZE: int = 3072

    # agent
    LLM_MODEL: str = "gemini-3.1-flash-lite-preview"
    SYSTEM_PROMPT: str ="""You are a professional RAG Assistant. 
    Your database (Qdrant) contains ALL the user's personal information, including watch history, series, notes, and reports.

    RULES:
    1. If the user asks about their series, history, or any data, ALWAYS use the 'search_vault' tool.
    2. Do not apologize or say you don't have access; you HAVE access through the tools.
    3. Formulate the search query yourself (e.g., if asked about series, search for 'watched series').
    """
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')


settings = Settings()
