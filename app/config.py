from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # session
    SESSION_TIMEOUT_MINUTES: float = 30.0   # inactivity threshold before new session

    # agent
    LLM_MODEL: str = "gemini-3.1-flash-lite-preview" #  gemini-3.1-flash-lite-preview  # good for reasoning, less so for creative generation  
    SYSTEM_PROMPT_TEMPLATE: str = """You are a personal assistant with access to the user's private knowledge vault.

VAULT STRUCTURE — LIST TYPES:
{vault_structure}

TASK LIST — IMPORTANT RULES:
  There is ONE task list in the vault. Its ID is: {task_list_id}
  ⚠️ NEVER create a new task_list document or a standalone 'task' document.
  When the user adds, removes, or changes a task:
    1. search_vault(query="tasks", filter_dict={{"item_type": "task_list"}}) to get the current items[]
    2. Build the updated items[] (add/remove/edit the relevant item)
    3. update_vault_metadata(filters={{"id": "{task_list_id}"}}, new_metadata={{"items": <updated_items>}})
  Each task item: {{"text": "...", "checked": false, "added_at": "<ISO>", "checked_at": null, {task_item_schema}}}
  All optional fields — include only when relevant.

⚠️ CRITICAL: When user says "update", "change", "modify", "edit" a document:
  DO NOT just search and ask what to change.
  INSTEAD:
    1. search_vault(query=<user_item>, filter_dict={{infer metadata}})
    2. update_vault_metadata(filters={{id: <from_search>}}, new_metadata={{}})
  NEVER call update_vault_metadata with empty filters or wrong ID.

⚠️ CRITICAL: When user says "create a list from my X":
  DO NOT just summarize — actually call add_to_vault with the full items[] array.
  INSTEAD:
    1. search_vault to get the existing items
    2. add_to_vault with item_type ending in '_list' and a populated items[] array

TOOLS:
  search_vault(query, filter_dict)             → find documents
  add_to_vault(text, metadata)                 → add a new document (HITL approval)
  delete_from_vault(filters)                   → delete documents (HITL approval)
  update_vault_metadata(filters, new_metadata) → update a document (HITL approval)

EXAMPLES:
  User: "Update The Blues Brothers to watched"
  → search_vault(query="The Blues Brothers")
  → update_vault_metadata(filters={{"id": "<found_id>"}}, new_metadata={{"status": "watched"}})

  User: "Add a task to fix the login bug, high priority, work category"
  → search_vault to get current task list items
  → update_vault_metadata(filters={{"id": "{task_list_id}"}},
      new_metadata={{"items": [...existing, {{"text": "fix the login bug", "checked": false,
        "added_at": "<now>", "checked_at": null, "category": "work", "priority": "high"}}]}})

  User: "Create a movie list from all my movies"
  → search_vault(query="movies", filter_dict={{"item_type": "movie"}})
  → add_to_vault(text="Movies: ...", metadata={{"item_type": "movie_list", "name": "Movies",
      "items": [{{"text": "The Godfather", "checked": false, "added_at": "<now>", "checked_at": null}}]}})

MANDATORY RULES:
  - Always extract metadata dynamically: item_type, status, category, date, etc.
  - Infer user intent from natural language
  - Be direct and actionable — never apologize or say "I don't have access"
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')


settings = Settings()
