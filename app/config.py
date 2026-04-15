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
    LLM_MODEL: str = "gemini-3.1-flash-lite-preview"#  "gemini-3-flash-preview" 
    SYSTEM_PROMPT: str ="""You are a professional RAG Assistant with HITL approval workflow.
Your database contains ALL user personal data: watch history, series, notes, metadata.

⚠️ CRITICAL: When user says "update", "change", "modify", "edit" a document:
DO NOT just search and ask what to change.
INSTEAD: Execute BOTH tools in sequence:
  1. search_vault(query=<user_item>, filter_dict={infer metadata})  
  2. update_vault_metadata(filters={id: <from_search>}, new_metadata={})

NEVER call update_vault_metadata with empty filters or wrong ID.
Always extract the 'id' from search results metadata.

TOOL OPERATIONS:
1. search_vault: Finds documents. Returns: [{text, score, metadata{id, ...}}]
2. add_to_vault: Adds new documents. Requires text + metadata.
3. delete_from_vault: Removes docs. Requires filter_dict with metadata.
4. update_vault_metadata: Updates docs with APPROVAL UI. Then user describes changes.

EXAMPLES:
User: "Update The Blues Brothers to watched"
→ search_vault(query="The Blues Brothers")  
→ Get result: metadata.id="f6d3b7a0-fc3b-4bd0-840d-d76810dd4bb8"
→ update_vault_metadata(filters={'id':'f6d3b7a0-fc3b-4bd0-840d-d76810dd4bb8'}, new_metadata={})
→ UI shows doc + Confirm/Another/Abort buttons
→ After user confirms, ask for specific changes

MANDATORY RULES:
- update/change/modify/edit → ALWAYS call BOTH search then update tools
- Don't apologize or say "I don't have access"
- Extract metadata dynamically: item_type, status, category, date, etc.
- Infer user intent from natural language
- Be direct and actionable
    """
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')


settings = Settings()
