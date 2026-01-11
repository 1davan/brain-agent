from typing import List, Dict, Any, Optional
import json
from datetime import datetime
from app.database.sheets_client import SheetsClient
from app.utils.vector_processor import VectorProcessor
from app.services.ai_service import AIService

class MemoryAgent:
    def __init__(self, sheets_client: SheetsClient, vector_processor: VectorProcessor, ai_service: AIService):
        self.sheets = sheets_client
        self.vector = vector_processor
        self.ai = ai_service

    async def store_memory(self, user_id: str, category: str, key: str, value: str) -> str:
        """Store new memory with semantic embedding and conflict resolution"""
        try:
            # Check for similar existing memories
            memories_df = await self.sheets.get_sheet_data("Memories", user_id)
            memories = memories_df.to_dict('records') if not memories_df.empty else []

            similar = await self.vector.search_similar(value, memories, user_id, limit=3, threshold=0.7)

            if similar:
                # High similarity - merge with existing
                existing_key = similar[0]['key']
                existing_value = similar[0]['value']
                merged_value = await self.ai.merge_memories(existing_value, value)

                # Find and update the existing row
                row_index = await self.sheets.find_row_by_id("Memories", user_id, existing_key)
                if row_index:
                    embedding = await self.vector.generate_memory_embedding(category, existing_key, merged_value)
                    await self.sheets.update_row("Memories", row_index, {
                        "value": merged_value,
                        "embedding": embedding,
                        "timestamp": datetime.now().isoformat(),
                        "confidence": min(float(similar[0].get('confidence', 1.0)) + 0.1, 1.0)
                    })
                    return f"Memory merged with existing: {existing_key}"

            # Store as new memory
            embedding = await self.vector.generate_memory_embedding(category, key, value)

            await self.sheets.append_row("Memories", {
                "user_id": user_id,
                "category": category,
                "key": key,
                "value": value,
                "embedding": embedding,
                "timestamp": datetime.now().isoformat(),
                "confidence": 1.0,
                "tags": json.dumps([])
            })

            return f"New memory stored: {key}"

        except Exception as e:
            print(f"Error storing memory: {e}")
            return f"Error storing memory: {str(e)}"

    async def retrieve_memories(self, user_id: str, query: str, category: str = None, limit: int = 5) -> List[Dict]:
        """Retrieve semantically similar memories"""
        try:
            memories_df = await self.sheets.get_sheet_data("Memories", user_id)
            memories = memories_df.to_dict('records') if not memories_df.empty else []

            results = await self.vector.search_similar(query, memories, user_id, category, limit, threshold=0.3)
            return results

        except Exception as e:
            print(f"Error retrieving memories: {e}")
            return []

    async def update_memory(self, user_id: str, key: str, new_value: str) -> str:
        """Update existing memory by key or partial key match"""
        try:
            # Get all memories for this user
            memories_df = await self.sheets.get_sheet_data("Memories", user_id)
            if memories_df.empty:
                return f"Memory not found: {key}"

            # Try exact key match first
            existing = memories_df[memories_df['key'] == key]
            
            # If no exact match, try partial match
            if existing.empty:
                key_lower = key.lower()
                for idx, row in memories_df.iterrows():
                    if key_lower in str(row.get('key', '')).lower():
                        existing = memories_df.iloc[[idx]]
                        key = row.get('key')  # Use the actual key
                        break
            
            # If still no match, try searching by value content
            if existing.empty:
                for idx, row in memories_df.iterrows():
                    if key.lower() in str(row.get('value', '')).lower():
                        existing = memories_df.iloc[[idx]]
                        key = row.get('key')
                        break
            
            if existing.empty:
                return f"Memory not found: {key}"

            # Find the actual row in the sheet
            row_index = await self.sheets.find_row_by_id("Memories", user_id, key)
            if not row_index:
                return f"Memory not found (row lookup failed): {key}"

            category = existing.iloc[0]['category']
            embedding = await self.vector.generate_memory_embedding(category, key, new_value)

            await self.sheets.update_row("Memories", row_index, {
                "value": new_value,
                "embedding": embedding,
                "timestamp": datetime.now().isoformat()
            })

            return f"Memory updated: {key}"

        except Exception as e:
            print(f"Error updating memory: {e}")
            return f"Error updating memory: {str(e)}"

    async def delete_memory(self, user_id: str, key: str) -> str:
        """Delete a memory (move to archive)"""
        try:
            memories_df = await self.sheets.get_sheet_data("Memories", user_id)
            if memories_df.empty:
                return f"Memory not found: {key}"

            memory = memories_df[memories_df['key'] == key]
            if memory.empty:
                return f"Memory not found: {key}"

            # Move to archive
            memory_data = memory.iloc[0].to_dict()
            await self.sheets.append_row("Archive", {
                "user_id": user_id,
                "original_sheet": "Memories",
                "content": json.dumps(memory_data),
                "archived_at": datetime.now().isoformat(),
                "reason": "deleted_by_user"
            })

            # Note: In a real implementation, you'd delete the row
            # For now, we'll just mark it as archived
            row_index = await self.sheets.find_row_by_id("Memories", user_id, key)
            if row_index:
                await self.sheets.update_row("Memories", row_index, {
                    "value": "[DELETED]",
                    "timestamp": datetime.now().isoformat()
                })

            return f"Memory archived: {key}"

        except Exception as e:
            print(f"Error deleting memory: {e}")
            return f"Error deleting memory: {str(e)}"

    async def categorize_information(self, user_id: str, information: str) -> Dict[str, str]:
        """Automatically categorize new information"""
        prompt = f"""
        Analyze this information and categorize it:

        Information: {information}

        Categories: personal, work, preferences, knowledge, health, finance, relationships, goals, habits

        Return JSON: {{"category": "string", "key": "brief_key_name", "should_store": true/false}}
        """

        try:
            # This would use the AI service
            # For now, return defaults
            return {
                "category": "knowledge",
                "key": f"info_{int(datetime.now().timestamp())}",
                "should_store": True
            }
        except Exception as e:
            print(f"Error categorizing information: {e}")
            return {
                "category": "knowledge",
                "key": f"info_{int(datetime.now().timestamp())}",
                "should_store": True
            }