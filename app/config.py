from pydantic_settings import BaseSettings, SettingsConfigDict

from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    # qdrant
    QDRANT_HOST: str 
    QDRANT_PORT: int  
    QDRANT_COLLECTION_NAME: str = "documents"   

    # telegram
    TELEGRAM_TOKEN: str      
    
    
    
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')


settings = Settings()
