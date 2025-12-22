"""
Literotica Story Scraper Utility

Fetches and parses stories from Literotica.com for text-to-speech reading.
"""

import re
import asyncio
from dataclasses import dataclass, field
from typing import Optional
import httpx
from bs4 import BeautifulSoup


@dataclass
class StoryChapter:
    """Represents a single chapter/page of a story."""
    title: str
    url: str
    content: str = ""
    page_number: int = 1


@dataclass
class LiteroticaStory:
    """Represents a complete Literotica story with metadata."""
    title: str
    author: str
    url: str
    description: str = ""
    category: str = ""
    chapters: list[StoryChapter] = field(default_factory=list)
    
    @property
    def full_text(self) -> str:
        """Get all chapter content as a single string."""
        return "\n\n".join(ch.content for ch in self.chapters if ch.content)


class LiteroticaScraper:
    """Async scraper for Literotica stories."""
    
    BASE_URL = "https://www.literotica.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self.client = httpx.AsyncClient(headers=self.HEADERS, timeout=30.0, follow_redirects=True)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    def _extract_story_id(self, url: str) -> Optional[str]:
        """Extract the story ID/slug from a Literotica URL."""
        # Handle various URL formats:
        # https://www.literotica.com/s/story-name
        # https://www.literotica.com/s/story-name?page=2
        # https://literotica.com/s/story-name
        
        match = re.search(r'/s/([a-zA-Z0-9\-]+)', url)
        if match:
            return match.group(1)
        return None
    
    async def fetch_story(self, url: str) -> Optional[LiteroticaStory]:
        """
        Fetch a complete story from Literotica.
        
        Args:
            url: The URL of the story (any page)
            
        Returns:
            LiteroticaStory object with all content, or None if fetch fails
        """
        if not self.client:
            raise RuntimeError("Scraper must be used as async context manager")
        
        story_id = self._extract_story_id(url)
        if not story_id:
            print(f"Could not extract story ID from URL: {url}")
            return None
        
        # Normalize URL to page 1
        base_story_url = f"{self.BASE_URL}/s/{story_id}"
        
        try:
            # Fetch first page to get metadata and page count
            response = await self.client.get(base_story_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract metadata
            story = self._parse_metadata(soup, base_story_url)
            if not story:
                return None
            
            # Get page count
            page_count = self._get_page_count(soup)
            
            # Fetch first page content
            first_chapter = StoryChapter(
                title=story.title,
                url=base_story_url,
                content=self._extract_content(soup),
                page_number=1
            )
            story.chapters.append(first_chapter)
            
            # Fetch remaining pages if multi-page story
            if page_count > 1:
                for page_num in range(2, page_count + 1):
                    await asyncio.sleep(0.5)  # Rate limiting
                    page_url = f"{base_story_url}?page={page_num}"
                    
                    try:
                        page_response = await self.client.get(page_url)
                        page_response.raise_for_status()
                        page_soup = BeautifulSoup(page_response.text, 'html.parser')
                        
                        chapter = StoryChapter(
                            title=f"{story.title} - Page {page_num}",
                            url=page_url,
                            content=self._extract_content(page_soup),
                            page_number=page_num
                        )
                        story.chapters.append(chapter)
                    except Exception as e:
                        print(f"Error fetching page {page_num}: {e}")
                        continue
            
            return story
            
        except Exception as e:
            print(f"Error fetching story: {e}")
            return None
    
    def _parse_metadata(self, soup: BeautifulSoup, url: str) -> Optional[LiteroticaStory]:
        """Extract story metadata from the page."""
        try:
            # Title - try multiple selectors
            title_elem = (
                soup.select_one('h1.j_bm') or
                soup.select_one('h1[class*="headline"]') or
                soup.select_one('.b-story-header h1') or
                soup.find('h1')
            )
            title = title_elem.get_text(strip=True) if title_elem else "Unknown Title"
            
            # Author
            author_elem = (
                soup.select_one('a.y_eU') or
                soup.select_one('a[href*="/stories/memberpage"]') or
                soup.select_one('.b-story-user-y a')
            )
            author = author_elem.get_text(strip=True) if author_elem else "Unknown Author"
            
            # Description/Tagline
            desc_elem = (
                soup.select_one('.b-story-copy') or
                soup.select_one('meta[name="description"]')
            )
            if desc_elem:
                if desc_elem.name == 'meta':
                    description = desc_elem.get('content', '')
                else:
                    description = desc_elem.get_text(strip=True)
            else:
                description = ""
            
            # Category
            category_elem = soup.select_one('.b-breadcrumbs a:last-child')
            category = category_elem.get_text(strip=True) if category_elem else ""
            
            return LiteroticaStory(
                title=title,
                author=author,
                url=url,
                description=description,
                category=category
            )
            
        except Exception as e:
            print(f"Error parsing metadata: {e}")
            return None
    
    def _get_page_count(self, soup: BeautifulSoup) -> int:
        """Determine how many pages the story has."""
        try:
            # Look for page navigation
            page_links = soup.select('.l_bJ a') or soup.select('.b-pager-pages a')
            if page_links:
                # Find the highest page number
                max_page = 1
                for link in page_links:
                    text = link.get_text(strip=True)
                    if text.isdigit():
                        max_page = max(max_page, int(text))
                return max_page
            
            # Alternative: check URL in "last" button
            last_link = soup.select_one('a[title="Last"]') or soup.select_one('.b-pager-next')
            if last_link:
                href = last_link.get('href', '')
                match = re.search(r'page=(\d+)', href)
                if match:
                    return int(match.group(1))
            
            return 1
            
        except Exception:
            return 1
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract the story text content from the page."""
        try:
            # Main content container - try multiple selectors
            content_elem = (
                soup.select_one('.aa_ht') or
                soup.select_one('.b-story-body-x') or
                soup.select_one('div[class*="panel-body"]') or
                soup.select_one('.b-story-body')
            )
            
            if not content_elem:
                # Fallback: look for paragraphs in article
                article = soup.find('article')
                if article:
                    content_elem = article
            
            if not content_elem:
                return ""
            
            # Extract text, preserving paragraph structure
            paragraphs = content_elem.find_all('p')
            if paragraphs:
                text_parts = []
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if text:
                        text_parts.append(text)
                return '\n\n'.join(text_parts)
            else:
                # Fallback to direct text extraction
                return content_elem.get_text(separator='\n\n', strip=True)
                
        except Exception as e:
            print(f"Error extracting content: {e}")
            return ""


async def fetch_story(url: str) -> Optional[LiteroticaStory]:
    """
    Convenience function to fetch a story.
    
    Args:
        url: Literotica story URL
        
    Returns:
        LiteroticaStory object or None
    """
    async with LiteroticaScraper() as scraper:
        return await scraper.fetch_story(url)


# For testing
if __name__ == "__main__":
    import sys
    
    async def test():
        if len(sys.argv) < 2:
            print("Usage: python literotica.py <story_url>")
            return
        
        story = await fetch_story(sys.argv[1])
        if story:
            print(f"Title: {story.title}")
            print(f"Author: {story.author}")
            print(f"Category: {story.category}")
            print(f"Chapters: {len(story.chapters)}")
            print(f"Total length: {len(story.full_text)} characters")
            print("\n--- First 500 chars ---")
            print(story.full_text[:500])
        else:
            print("Failed to fetch story")
    
    asyncio.run(test())
