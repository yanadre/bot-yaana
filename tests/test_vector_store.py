import pytest

@pytest.mark.asyncio
async def test_add_and_search_with_metadata(qdrant_store):
    # 1. Add documents with specific metadata
    texts = ["Tax report 2023", "Tax report 2024", "Cooking recipes"]
    metadatas = [
        {"year": 2023, "type": "finance"},
        {"year": 2024, "type": "finance"},
        {"year": 2024, "type": "food"}
    ]
    await qdrant_store.add(texts, metadatas)

    # 2. Test Hybrid Search (Content + Metadata Filter)
    # Search for 'tax' but only in 2024
    results = await qdrant_store.search(
        query="tax", 
        filter_dict={"year": 2024, "type": "finance"}, 
        top_k=5
    )

    assert len(results) == 1
    assert results[0]["metadata"]["year"] == 2024
    assert "Tax report 2024" in results[0]["text"]

@pytest.mark.asyncio
async def test_update_metadata(qdrant_store):
    await qdrant_store.add(["Old Doc"], [{"status": "draft"}])
    
    # Update status from 'draft' to 'published'
    await qdrant_store.update_metadata(
        filter_dict={"status": "draft"}, 
        new_metadata={"status": "published"}
    )
    
    # Verify change
    results = await qdrant_store.search(query="", filter_dict={"status": "published"})
    assert len(results) == 1
    assert results[0]["metadata"]["status"] == "published"

@pytest.mark.asyncio
async def test_delete_with_filter(qdrant_store):
    await qdrant_store.add(["Delete me", "Keep me"], [{"id": 100}, {"id": 200}])
    
    # Delete only ID 100
    await qdrant_store.delete(filter_dict={"id": 100})
    
    # Verify only one remains
    results = await qdrant_store.search(query="")
    assert len(results) == 1
    assert results[0]["metadata"]["id"] == 200