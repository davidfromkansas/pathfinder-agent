# Shared cache module - singleton pattern to ensure all imports use the same cache
from typing import Dict, List, Any

# Global cache to store trial data for later access
# Now accumulates results from multiple searches in a session
_trial_cache: Dict[str, Any] = {
    "searches": [],  # List of all searches made
    "all_trials": [],  # Accumulated unique trials (deduplicated by NCT ID)
    "total_count": 0,  # Total unique trials found
}

# Research cache to store disease info and PubMed articles
_research_cache: Dict[str, Any] = {
    "disease_name": "",
    "disease_info": [],  # Raw info from disease_researcher (NIH/NCI)
    "pubmed_articles": [],  # Articles from PubMed (last 5 years)
}


def get_trial_cache() -> Dict[str, Any]:
    """Get the current trial cache."""
    return _trial_cache


def add_to_trial_cache(query: Dict, total_count: int, trials: List[Dict]):
    """Add search results to the cache, deduplicating by NCT ID."""
    # Track this search
    _trial_cache["searches"].append({
        "query": query,
        "results_count": len(trials)
    })
    
    # Get existing NCT IDs for deduplication
    existing_nct_ids = {t.get("nct_id") for t in _trial_cache["all_trials"]}
    
    # Add new unique trials
    new_trials = []
    for trial in trials:
        nct_id = trial.get("nct_id")
        if nct_id and nct_id not in existing_nct_ids:
            _trial_cache["all_trials"].append(trial)
            existing_nct_ids.add(nct_id)
            new_trials.append(trial)
    
    _trial_cache["total_count"] = len(_trial_cache["all_trials"])
    
    print(f"[Cache] Added {len(new_trials)} new trials (total: {_trial_cache['total_count']} unique trials from {len(_trial_cache['searches'])} searches)")


def clear_trial_cache():
    """Clear the trial cache for a new session."""
    _trial_cache["searches"] = []
    _trial_cache["all_trials"] = []
    _trial_cache["total_count"] = 0
    print("[Cache] Trial cache cleared")


# ========================================
# Research Cache Functions
# ========================================

def get_research_cache() -> Dict[str, Any]:
    """Get the current research cache."""
    return _research_cache


def add_disease_info(disease_name: str, info: str, source: str):
    """Add disease information from NIH/NCI."""
    _research_cache["disease_name"] = disease_name
    _research_cache["disease_info"].append({
        "source": source,
        "content": info
    })
    print(f"[Research Cache] Added disease info from {source}")


def add_pubmed_article(article: Dict):
    """Add a PubMed article to the research cache."""
    # Avoid duplicates by PMID
    existing_pmids = {a.get("pmid") for a in _research_cache["pubmed_articles"]}
    if article.get("pmid") not in existing_pmids:
        _research_cache["pubmed_articles"].append(article)
        print(f"[Research Cache] Added article: {article.get('title', 'Unknown')[:50]}...")


def clear_research_cache():
    """Clear the research cache for a new session."""
    _research_cache["disease_name"] = ""
    _research_cache["disease_info"] = []
    _research_cache["pubmed_articles"] = []
    print("[Cache] Research cache cleared")

