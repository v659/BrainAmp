import requests
import logging
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from typing import Optional
import time

logger = logging.getLogger(__name__)

# Configuration
REQUEST_TIMEOUT = 10
MAX_RETRIES = 2
RATE_LIMIT_DELAY = 1  # seconds between requests
MAX_CONTENT_LENGTH = 5000  # characters

# Supported domains and their search URL patterns
DOMAIN_SEARCH = {
    "wikipedia.org": "https://en.wikipedia.org/w/index.php?search={query}",
    "britannica.com": "https://www.britannica.com/search?query={query}",
    "plato.stanford.edu": "https://plato.stanford.edu/search/searcher.py?query={query}",
    "iep.utm.edu": "https://iep.utm.edu/?s={query}",
    "ocw.mit.edu": "https://ocw.mit.edu/search/?q={query}",
    "openstax.org": "https://openstax.org/search?query={query}",
    "nap.edu": "https://www.nap.edu/search/?terms={query}",
    "arxiv.org": "https://export.arxiv.org/api/query?search_query=all:{query}",
    "nasa.gov": "https://www.nasa.gov/search?q={query}",
    "bbc.co.uk": "https://www.bbc.co.uk/search?q={query}"
}

# User agent to identify ourselves
USER_AGENT = "Brain-Amp-Educational-Bot/1.0 (Educational purposes only)"


def fetch_clean_text(url: str) -> Optional[str]:
    retries = 0

    while retries < MAX_RETRIES:
        try:
            # Add rate limiting
            time.sleep(RATE_LIMIT_DELAY)

            # Make request with timeout
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True
            )

            # Check status code
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type.lower():
                logger.warning(f"Non-HTML content type: {content_type}")
                return None

            # Parse HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # Remove unwanted elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe", "noscript"]):
                tag.decompose()

            # Try to find main content
            main_content = (
                    soup.find("main") or
                    soup.find("article") or
                    soup.find("div", {"id": "content"}) or
                    soup.find("div", {"class": "content"}) or
                    soup.body
            )

            if not main_content:
                logger.warning(f"No main content found for URL: {url}")
                return None

            # Extract text
            text = main_content.get_text(" ", strip=True)

            # Clean whitespace
            text = " ".join(text.split())

            # Validate minimum length
            if len(text) < 100:
                logger.warning(f"Content too short: {len(text)} characters")
                return None

            # Limit length
            if len(text) > MAX_CONTENT_LENGTH:
                text = text[:MAX_CONTENT_LENGTH]

            return text

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching URL: {url} (attempt {retries + 1}/{MAX_RETRIES})")
            retries += 1

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching URL: {url} - {e}")
            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error fetching URL: {url} - {e}")
            retries += 1

        except Exception as e:
            logger.error(f"Unexpected error fetching URL: {url} - {e}")
            return None

    logger.error(f"Failed to fetch URL after {MAX_RETRIES} retries: {url}")
    return None


def browse_allowed_sources(
        query: str,
        forced_domain: str
) -> str:
    if not query or not query.strip():
        logger.warning("Empty query provided")
        return ""

    if not forced_domain or forced_domain not in DOMAIN_SEARCH:
        logger.warning(f"Invalid or unsupported domain: {forced_domain}")
        return ""

    # Clean query
    query = query.strip()

    # Limit query length
    if len(query) > 200:
        query = query[:200]

    try:
        # Build search URL
        search_url = DOMAIN_SEARCH[forced_domain].format(query=quote_plus(query))

        logger.info(f"Searching {forced_domain} for: {query}")

        # Fetch content
        text = fetch_clean_text(search_url)

        if not text:
            logger.warning(f"No content retrieved from {forced_domain}")
            return ""

        # Format result with source attribution
        result = f"[SOURCE: {forced_domain}]\n{text}"

        logger.info(f"Successfully retrieved {len(text)} characters from {forced_domain}")

        return result

    except Exception as e:
        logger.error(f"Error browsing source {forced_domain}: {e}")
        return ""


def validate_domain(domain: str) -> bool:
    return domain.lower().strip() in DOMAIN_SEARCH


def get_supported_domains() -> list:
    return list(DOMAIN_SEARCH.keys())
