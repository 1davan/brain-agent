#!/usr/bin/env python3
"""
Web search tool for the AI assistant
Uses DuckDuckGo for free, no-API-key web search
"""

import asyncio
from typing import List, Dict, Any
import aiohttp
import json
from datetime import datetime


class WebSearchTool:
    """Web search tool using DuckDuckGo"""
    
    def __init__(self):
        self.search_url = "https://api.duckduckgo.com/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    
    async def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Search the web using DuckDuckGo Instant Answer API
        
        Args:
            query: Search query
            num_results: Number of results to return
            
        Returns:
            List of search results with title, url, and snippet
        """
        try:
            params = {
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.search_url,
                    params=params,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_results(data, num_results)
                    else:
                        print(f"Search failed with status {response.status}")
                        return []
                        
        except asyncio.TimeoutError:
            print("Search timed out")
            return []
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    def _parse_results(self, data: Dict, num_results: int) -> List[Dict[str, str]]:
        """Parse DuckDuckGo API response"""
        results = []
        
        # Abstract (main answer)
        if data.get("Abstract"):
            results.append({
                "title": data.get("Heading", "Result"),
                "url": data.get("AbstractURL", ""),
                "snippet": data.get("Abstract", ""),
                "source": data.get("AbstractSource", "")
            })
        
        # Related topics
        for topic in data.get("RelatedTopics", [])[:num_results]:
            if isinstance(topic, dict):
                if "Text" in topic:
                    results.append({
                        "title": topic.get("Text", "")[:100],
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                        "source": "DuckDuckGo"
                    })
                # Handle nested topics
                elif "Topics" in topic:
                    for subtopic in topic.get("Topics", [])[:2]:
                        if isinstance(subtopic, dict) and "Text" in subtopic:
                            results.append({
                                "title": subtopic.get("Text", "")[:100],
                                "url": subtopic.get("FirstURL", ""),
                                "snippet": subtopic.get("Text", ""),
                                "source": "DuckDuckGo"
                            })
        
        # Infobox
        if data.get("Infobox"):
            infobox = data["Infobox"]
            for item in infobox.get("content", [])[:3]:
                if isinstance(item, dict):
                    results.append({
                        "title": item.get("label", "Info"),
                        "url": "",
                        "snippet": str(item.get("value", "")),
                        "source": "Infobox"
                    })
        
        return results[:num_results]
    
    async def search_with_scraping(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Fallback search using DuckDuckGo HTML (more results but slower)
        Uses duckduckgo-search library if available
        """
        try:
            from duckduckgo_search import DDGS
            
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=num_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                        "source": "DuckDuckGo"
                    })
            return results
            
        except ImportError:
            print("duckduckgo-search not installed, using basic API")
            return await self.search(query, num_results)
        except Exception as e:
            print(f"Scraping search error: {e}")
            return await self.search(query, num_results)
    
    def format_results_for_ai(self, results: List[Dict[str, str]]) -> str:
        """Format search results for AI context"""
        if not results:
            return "No search results found."
        
        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(f"{i}. **{result.get('title', 'Result')}**")
            if result.get('url'):
                formatted.append(f"   URL: {result['url']}")
            if result.get('snippet'):
                formatted.append(f"   {result['snippet'][:300]}...")
            formatted.append("")
        
        return "\n".join(formatted)


# Singleton instance
_web_search = None

def get_web_search() -> WebSearchTool:
    """Get singleton web search instance"""
    global _web_search
    if _web_search is None:
        _web_search = WebSearchTool()
    return _web_search
