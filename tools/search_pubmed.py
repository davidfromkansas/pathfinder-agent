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
    max_results: int = 50,
    years_back: int = 5,
    article_types: Optional[str] = None
) -> str:
    """
    Search PubMed for research articles to learn about a disease and its treatments.
    
    PURPOSE: Understand the treatment landscape - what drugs, therapies, and biomarkers 
    are relevant. Then use that knowledge to search ClinicalTrials.gov for actual trials.
    
    NOTE: PubMed is for RESEARCH ARTICLES, not for finding clinical trials.
    Do NOT include "clinical trial" or years like "2022 2023 2024" in queries.
    
    IMPORTANT: Run MULTIPLE searches with different queries to be comprehensive:
    - "[condition]" - general condition research
    - "[condition] treatment" - treatment approaches
    - "[condition] therapy" - therapeutic options  
    - "[condition] [specific drug/therapy]" - specific treatments you learn about
    - "[condition] review" with article_types="review" - overview articles
    
    Args:
        query: Simple, focused search query. 
               GOOD: "[condition]", "[condition] treatment", "[condition] review", "[drug] [condition]"
               Examples: "breast cancer immunotherapy", "EGFR lung cancer treatment", "type 2 diabetes GLP-1"
               BAD: "[condition] clinical trial 2022 2023 2024" (returns nothing)
        max_results: Maximum number of articles to return (default: 50, max: 100)
        years_back: How many years back to search (default: 5)
        article_types: Filter by article type. Options: "review" (recommended for overviews), "meta-analysis". 
                      Leave empty for all types.
    
    Returns:
        Research article summaries ranked by Best Match. Articles are automatically 
        added to the Research tab - do NOT list them in your chat response.
    """
    print(f"[PubMed] Searching: {query}")
    
    # Build the search query
    search_terms = [query]
    
    # Add date filter
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years_back * 365)
    date_filter = f"{start_date.strftime('%Y/%m/%d')}:{end_date.strftime('%Y/%m/%d')}[dp]"
    search_terms.append(date_filter)
    
    # Add article type filter if specified
    if article_types:
        type_map = {
            "review": "review[pt]",
            "clinical trial": "clinical trial[pt]",
            "meta-analysis": "meta-analysis[pt]",
            "randomized controlled trial": "randomized controlled trial[pt]"
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

