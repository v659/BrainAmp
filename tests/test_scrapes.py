from src.scrape_web import browse_allowed_sources

if __name__ == "__main__":
    query = "physics"
    text = browse_allowed_sources(query)
    print("Extracted text preview")
    print(text[:1000])
