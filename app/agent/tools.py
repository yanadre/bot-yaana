import asyncio
import logging

from typing import Literal, Optional, Dict, Any
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from app.agent.schemas import SearchVaultInput

logger = logging.getLogger(__name__)

@tool(
    args_schema=SearchVaultInput,
    description=(
        "Search the vector store for user data. "
        "Always extract and use relevant metadata fields from the user's query for filtering. "
        "The metadata schema is dynamic: infer fields such as item_type, status, update_date, etc., from the query context. "
        "Use 'query' for the main search term and 'filter_dict' for all inferred metadata filters. "
        "Examples: "
        "- For 'What books do I have?', set filter_dict={'item_type': 'book'} "
        "- For 'Show movies from 2023', set filter_dict={'item_type': 'movie', 'update_date': '2023'} "
        "- For 'Show all items regardless of status', omit the status key entirely "
        "- For 'Show my work task list' or 'show my groceries list', set filter_dict={'item_type': 'task_list'} or {'item_type': 'shopping_list'} "
        "IMPORTANT: 'task_list' (structured list with items[]) is different from 'task' (single standalone task). "
        "Use 'task_list' when the user refers to a named list of tasks. Use 'task' for individual task documents. "
        "Special filter values: "
        "- Omit a key to apply no constraint on that field (same as any value). "
        "- Set a field to null/None to match documents where that field is absent (e.g. no status set). "
        "- The 'version' field is automatically set to 'new' (current docs). You do NOT need to set it. "
        "  Only include version in filter_dict if the user explicitly asks for archived/old documents. "
        "This tool should be used to answer ANY user question about their personal data."
    )
)
def search_vault(query: str, filter_dict: Optional[Dict[str, Any]] = None, config: RunnableConfig = None):
    """
    Use this tool to answer ANY user question about their personal data, including:
    - Watched series or movies
    - Viewing history
    - Notes or reports
    - Any information stored in the user's database

    Parameters:
    - query (str): The search string describing what the user is looking for (e.g., 'watched series', 'movies I watched').
    - filter_dict (dict, optional): Optional dictionary to further filter results (e.g., by date or type). The schema is dynamic and should be inferred from the query.

    ALWAYS use this tool for these topics, never answer from your own knowledge.
    """
    logger.info(f"[TOOL] search_vault called with query={query!r}, filter_dict={filter_dict!r}, config={config!r}")
    vs = config.get("configurable", {}).get("vs")
    if vs is None:
        logger.error("[TOOL] search_vault: Vector store connection is missing in the current context.")
        return "Error: Vector store connection is missing in the current context."
    result = asyncio.run(vs.search(query=query, filter_dict=filter_dict))
    logger.info(f"[TOOL] search_vault result: {result}")
    return result

@tool(
    description=(
        "Add a document to the vector store. "
        "Always extract both the main content and all relevant metadata fields from the user's input. "
        "The metadata schema is dynamic: infer fields such as item_type, update_date, etc., from the query context. "
        "Use 'text' for the main content and 'metadata' for all inferred metadata fields. "
        "Examples: "
        "- For 'Add the book I, Robot', set metadata={'item_type': 'book'} "
        "- For 'Add a task to wash dishes', set metadata={'item_type': 'task'} "
        "- For list documents (shopping_list, task_list), use the items[] schema: "
        "  metadata={'item_type': 'shopping_list', 'name': 'Groceries', 'items': ["
        "    {'text': 'milk', 'checked': False, 'added_at': '<ISO datetime>', 'checked_at': None}"
        "  ]} "
        "- For task_list items, also include: priority ('high'/'medium'/'low'), "
        "  effort ('small'/'medium'/'large'), due_date ('YYYY-MM-DD', optional). "
        "- The 'text' field of a list document should be a plain summary: 'Groceries: milk, eggs' "
        "IMPORTANT: 'task_list' is a structured list of tasks (has items[]). "
        "'task' is a single standalone task document (no items[]). These are different item_types. "
        "If unsure, attempt to infer likely metadata fields. "
        "This tool should be used for any user request to add information to their personal database."
    )
)
def add_to_vault(text: str, metadata: Dict[str, Any], config: RunnableConfig):
    """SENSITIVE: Adds a document to Qdrant. Requires approval."""
    logger.info(f"[TOOL] add_to_vault called with text={text[:50]!r}, metadata={metadata!r}, config={config!r}")
    vs = config["configurable"].get("vs")
    try:
        asyncio.run(vs.add(texts=[text], metadatas=[metadata]))
        logger.info(f"[TOOL] add_to_vault: Successfully added document with metadata: {metadata}")
        return f"Successfully added document with metadata: {metadata}"
    except Exception as e:
        logger.error(f"[TOOL] add_to_vault error: {e}", exc_info=True)
        return f"Error adding document: {e}"

@tool(
    description=(
        "Delete documents from the vector store. "
        "NEVER use 'text' as a filter key — it is not a metadata field and will never match anything. "
        "The only valid filter keys are real metadata fields: item_type, status, id, update_date, etc. "
        "Choose the right strategy based on what the user asked: "
        "- To delete ONE specific document (e.g. 'delete I, Robot'): call search_vault first, get the 'id', then use filters={'id': '<found_id>'}. "
        "- To delete ALL documents matching a title/name (e.g. 'delete all I robot records'): use filters={'item_type': '<type>'} — do NOT filter by id. "
        "  The UI will show ALL matching documents and let the user pick which ones to delete. "
        "- To delete by metadata only (e.g. 'delete all tasks with status done'): filters={'item_type': 'task', 'status': 'done'} (no search needed). "
        "- To delete everything: call with filters={} (empty). "
        "When the user says 'all records' or 'all entries' of something, NEVER narrow by id — use broad metadata filters only. "
        "This tool triggers an approval UI — the user will confirm before anything is deleted."
    )
)
def delete_from_vault(filters: Dict[str, Any], config: RunnableConfig):
    """SENSITIVE: Deletes documents from Qdrant. Requires approval."""
    logger.info(f"[TOOL] delete_from_vault called with filters={filters!r}, config={config!r}")
    vs = config["configurable"].get("vs")
    try:
        asyncio.run(vs.delete(filter_dict=filters))
        logger.info(f"[TOOL] delete_from_vault: Successfully deleted documents matching filters: {filters}")
        return f"Successfully deleted documents matching filters: {filters}"
    except Exception as e:
        logger.error(f"[TOOL] delete_from_vault error: {e}", exc_info=True)
        return f"Error deleting documents: {e}"

@tool(
    description=(
        "Update metadata for documents in the vector store. "
        "Always extract all relevant metadata fields from the user's input to construct the filters and new metadata. "
        "The metadata schema is dynamic: infer fields such as item_type, status, rating, etc., from the query context. "
        "Use 'filters' for metadata fields that uniquely identify the document(s) to update, and 'new_metadata' for the new values. "
        "Examples: "
        "- For 'Change the status of The Blues Brothers from to_watch to watched', first search_vault finds it has id='f6d3b7a0-fc3b-4bd0-840d-d76810dd4bb8', then call with filters={'id': 'f6d3b7a0-fc3b-4bd0-840d-d76810dd4bb8'}, new_metadata={'status': 'watched'} "
        "- For 'Update homework task deadline to tomorrow', filters={'item_type': 'task', 'text': 'homework'}, new_metadata={'deadline': 'tomorrow'} "
        "If multiple docs match the filters, they will all be updated. To update a single document, include the 'id' in filters. "
        "For list documents (shopping_list, task_list): to add/remove/update items, pass the COMPLETE updated 'items' array in new_metadata. "
        "Do NOT partially update items — always send the full list. "
        "This tool triggers an approval UI for the user to confirm the document and describe changes before update is applied."
    )
)
def update_vault_metadata(filters: Dict[str, Any], new_metadata: Dict[str, Any], config: RunnableConfig):
    """
    Updates metadata for documents matching the filters using versioning.
    Creates a new version with updated metadata, marks old version as 'old'.
    HITL approval required.
    - filters: Dict of metadata to match documents (should include 'id' for single document updates).
    - new_metadata: Dict of new metadata to set.
    """
    logger.info(f"[TOOL] update_vault_metadata called with filters={filters!r}, new_metadata={new_metadata!r}, config={config!r}")
    vs = config["configurable"].get("vs")
    try:
        asyncio.run(vs.update_document(filter_dict=filters, new_metadata=new_metadata))
        logger.info(f"[TOOL] update_vault_metadata: Updated metadata for docs matching: {filters}")
        return f"Updated metadata for docs matching: {filters}"
    except Exception as e:
        logger.error(f"[TOOL] update_vault_metadata error: {e}", exc_info=True)
        return f"Error updating metadata: {e}"


@tool
def manage_vault(
    action: Literal["add", "delete"], 
    text: Optional[str] = None, 
    metadata: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, Any]] = None
):
    """
    Modifies the database.
    - action 'add': Provide 'text' and a 'metadata' dictionary (extracted from the text).
    - action 'delete': Provide 'filters' (metadata dict) to identify which docs to remove.
    """
    # This tool is intercepted by the Middleware. 
    # The agent will populate 'metadata' based on your System Prompt instructions.
    return f"PROPOSAL: {action} requested."


tools = [search_vault, add_to_vault, delete_from_vault, update_vault_metadata]
