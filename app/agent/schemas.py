from typing import Optional, Dict, Any
from pydantic import BaseModel

class SearchVaultInput(BaseModel):
    """
    Input schema for searching the vector store.
    - query: The search query (e.g., 'books', 'series', etc.)
    - filter_dict: Optional dictionary to filter results (e.g., {'item_type': 'book'})
    """
    query: str
    filter_dict: Optional[Dict[str, Any]] = None