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
        "The metadata schema is dynamic: infer fields such as item_type, update_date, etc., from the query context. "
        "Use 'query' for the main search term and 'filter_dict' for all inferred metadata filters. "
        "Examples: "
        "- For 'What books do I have?', set filter_dict={'item_type': 'book'} "
        "- For 'Show movies from 2023', set filter_dict={'item_type': 'movie', 'update_date': '2023'} "
        "If unsure, attempt to infer likely metadata fields. "
        "This tool should be used to answer ANY user question about their personal data, including watched series, viewing history, notes, or any information stored in the user's database."
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

@tool
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

@tool
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

@tool
def update_vault_metadata(filters: Dict[str, Any], new_metadata: Dict[str, Any], config: RunnableConfig):
    """
    Updates metadata for documents matching the filters.
    - filters: Dict of metadata to match documents.
    - new_metadata: Dict of new metadata to set.
    """
    logger.info(f"[TOOL] update_vault_metadata called with filters={filters!r}, new_metadata={new_metadata!r}, config={config!r}")
    vs = config["configurable"].get("vs")
    try:
        asyncio.run(vs.update_metadata(filters, new_metadata))
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
