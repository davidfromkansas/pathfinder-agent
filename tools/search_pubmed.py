from agents import function_tool
import httpx
from typing import Optional, List
from datetime import datetime, timedelta
from .cache import add_pubmed_article


ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

# Headers for NCBI API requests
REQUEST_HEADERS = {
    "User-Agent": "PathfinderAgent/1.0 (Clinical Research Application)",
    "Accept": "application/json",
}


@function_tool
def search_pubmed(
    query: str,
    max_results: int = 15,
    years_back: int = 3,
    article_types: Optional[str] = None,
    high_quality: bool = True
) -> str:
    """
    Search PubMed for HIGH-QUALITY research articles on a disease and its treatments.
    
    PURPOSE: Find the BEST, most relevant research - not the most research.
    Prioritize review articles and meta-analyses that summarize the field.
    
    QUALITY OVER QUANTITY: Run 2-3 focused searches, not 5-7 broad ones.
    
    RECOMMENDED SEARCH STRATEGY:
    1. "[condition] systematic review" with article_types="review" (BEST - comprehensive summaries)
    2. "[condition] treatment guidelines" (clinical recommendations)
    3. "[condition] [specific treatment]" if relevant (targeted research)
    
    Args:
        query: Focused search query. Add "systematic review" or "guidelines" for best results.
               GOOD: "anaplastic thyroid cancer systematic review", "ATC treatment guidelines"
               GOOD: "thyroid cancer immunotherapy", "BRAF thyroid cancer"
               BAD: generic queries without focus
        max_results: Number of articles (default: 15, max: 30 for quality)
        years_back: How many years back (default: 3 for recent, relevant research)
        article_types: "review" (RECOMMENDED), "meta-analysis", or None for all
        high_quality: If True, adds filters for human studies and major topic focus (default: True)
    
    Returns:
        Top research articles ranked by Best Match. Automatically added to Research tab.
    """
    print(f"[PubMed] Searching: {query} (high_quality={high_quality})")
    
    # Cap max_results for quality
    max_results = min(max_results, 30)
    
    # Build the search query
    search_terms = [query]
    
    # Add date filter
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years_back * 365)
    date_filter = f"{start_date.strftime('%Y/%m/%d')}:{end_date.strftime('%Y/%m/%d')}[dp]"
    search_terms.append(date_filter)
    
    # Add high-quality filters
    if high_quality:
        search_terms.append("humans[mh]")  # Only human studies
    
    # Add article type filter if specified
    if article_types:
        type_map = {
            "review": "review[pt]",
            "systematic review": "(systematic review[pt] OR meta-analysis[pt])",
            "meta-analysis": "meta-analysis[pt]",
            "clinical trial": "clinical trial[pt]",
            "randomized controlled trial": "randomized controlled trial[pt]",
            "guidelines": "guideline[pt]"
        }
        if article_types.lower() in type_map:
            search_terms.append(type_map[article_types.lower()])
    
    full_query = " AND ".join(search_terms)
    
    try:
        # Step 1: Search for article IDs
        search_params = {
            "db": "pubmed",
            "term": full_query,
            "retmax": min(max_results, 100),
            "sort": "relevance",  # Sort by Best Match
            "retmode": "json"
        }
        
        print(f"[PubMed] Query: {full_query}")
        
        with httpx.Client(timeout=30.0, headers=REQUEST_HEADERS) as client:
            search_response = client.get(ESEARCH_URL, params=search_params)
            search_response.raise_for_status()
            search_data = search_response.json()
        
        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total_count = int(search_data.get("esearchresult", {}).get("count", 0))
        
        if not id_list:
            return f"No PubMed articles found for '{query}' in the last {years_back} years."
        
        print(f"[PubMed] Found {total_count} articles, fetching top {len(id_list)}")
        
        # Step 2: Fetch article summaries
        summary_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "json"
        }
        
        with httpx.Client(timeout=30.0, headers=REQUEST_HEADERS) as client:
            summary_response = client.get(ESUMMARY_URL, params=summary_params)
            summary_response.raise_for_status()
            summary_data = summary_response.json()
        
        # Parse and format results
        articles = []
        result = summary_data.get("result", {})
        
        for pmid in id_list:
            article = result.get(pmid, {})
            if not article or pmid == "uids":
                continue
            
            title = article.get("title", "No title")
            authors = article.get("authors", [])
            author_str = ", ".join([a.get("name", "") for a in authors[:3]])
            if len(authors) > 3:
                author_str += " et al."
            
            journal = article.get("source", "Unknown journal")
            pub_date = article.get("pubdate", "Unknown date")
            
            # Get article types
            pub_types = article.get("pubtype", [])
            pub_type_str = ", ".join(pub_types[:2]) if pub_types else "Article"
            
            article_data = {
                "pmid": pmid,
                "title": title,
                "authors": author_str,
                "journal": journal,
                "date": pub_date,
                "type": pub_type_str,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            }
            articles.append(article_data)
            
            # Add to research cache for Research tab
            add_pubmed_article(article_data)
        
        # Format output
        output = [f"PUBMED RESEARCH: Found {total_count} articles on '{query}'. Showing {len(articles)} best matches:\n"]
        
        for i, article in enumerate(articles, 1):
            output.append(f"""
**{i}. {article['title']}**
- Authors: {article['authors']}
- Journal: {article['journal']} ({article['date']})
- Type: {article['type']}
- PubMed: https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/
""")
        
        output.append(f"\n---\nUse these findings to understand current research directions and treatment approaches for the condition.")
        
        return "".join(output)
        
    except httpx.HTTPStatusError as e:
        print(f"[PubMed Error] HTTP {e.response.status_code}")
        return f"Error searching PubMed: HTTP {e.response.status_code}"
    except Exception as e:
        print(f"[PubMed Error] {str(e)}")
        return f"Error searching PubMed: {str(e)}"

