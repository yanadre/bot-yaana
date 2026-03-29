from pydantic_settings import BaseSettings, SettingsConfigDict

from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    # qdrant
    QDRANT_HOST: str 
    QDRANT_PORT: int  
    QDRANT_COLLECTION_NAME: str = "documents_tests"   

    # telegram
    TELEGRAM_TOKEN: str     
    AUTHORIZED_ID: str 

    # embedding
    GOOGLE_API_KEY: str
    EMBEDDING_MODEL_NAME: str = "gemini-embedding-001"
    EMBEDDING_VECTOR_SIZE: int = 3072
    
    
    
    
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')


settings = Settings()
