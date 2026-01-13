from agents import function_tool
import httpx
from typing import Optional
import json
import re
from .cache import add_disease_info


# MedlinePlus Connect API - NIH's consumer health information
MEDLINEPLUS_API = "https://connect.medlineplus.gov/service"

# NCI Dictionary API - Cancer-specific terms
NCI_DICT_API = "https://api.cancer.gov/v1/Terms"

# Headers for API requests
REQUEST_HEADERS = {
    "User-Agent": "PathfinderAgent/1.0 (Medical Research Application)",
    "Accept": "application/json",
}


@function_tool
def research_disease(
    disease_name: str,
    include_treatments: bool = True,
    include_causes: bool = True,
    cancer_specific: bool = False
) -> str:
    """
    Research a disease or medical condition using trusted medical sources (NIH, NCI, MedlinePlus).
    Use this to learn about a disease's definition, causes, symptoms, treatments, and prognosis.
    
    Args:
        disease_name: The name of the disease or condition to research (e.g., "anaplastic thyroid cancer", "type 2 diabetes")
        include_treatments: Whether to include treatment information (default: True)
        include_causes: Whether to include causes and risk factors (default: True)
        cancer_specific: Set to True for cancer conditions to search NCI database (default: False)
    
    Returns:
        Comprehensive information about the disease from trusted medical sources.
        Use this to understand the condition, its standard treatments, and key medical terminology.
    """
    print(f"[DiseaseResearcher] Researching: {disease_name}")
    
    results = []
    
    # Search MedlinePlus for general health information
    medlineplus_info = _search_medlineplus(disease_name)
    if medlineplus_info:
        results.append(medlineplus_info)
        add_disease_info(disease_name, medlineplus_info, "MedlinePlus")
    
    # For cancer conditions, also search NCI
    if cancer_specific or _is_cancer_related(disease_name):
        nci_info = _search_nci_dictionary(disease_name)
        if nci_info:
            results.append(nci_info)
            add_disease_info(disease_name, nci_info, "NCI")
    
    if not results:
        return f"No detailed information found for '{disease_name}' in trusted medical databases. Try using search_pubmed for research articles instead."
    
    output = [f"DISEASE RESEARCH: {disease_name.title()}\n"]
    output.append("=" * 50 + "\n")
    output.extend(results)
    output.append("\n---")
    output.append("Sources: NIH MedlinePlus, National Cancer Institute")
    output.append("\nUse this information to understand the condition and identify relevant clinical trial search terms.")
    
    return "\n".join(output)


def _is_cancer_related(disease_name: str) -> bool:
    """Check if the disease name suggests a cancer condition."""
    cancer_keywords = [
        'cancer', 'carcinoma', 'tumor', 'tumour', 'lymphoma', 'leukemia', 
        'melanoma', 'sarcoma', 'myeloma', 'neoplasm', 'malignant', 'oncology',
        'metastatic', 'metastases'
    ]
    disease_lower = disease_name.lower()
    return any(keyword in disease_lower for keyword in cancer_keywords)


def _search_medlineplus(query: str) -> Optional[str]:
    """Search MedlinePlus for health topic information."""
    try:
        # MedlinePlus Health Topics API
        params = {
            "mainSearchCriteria.v.cs": "2.16.840.1.113883.6.90",  # ICD-10-CM
            "mainSearchCriteria.v.dn": query,
            "informationRecipient.languageCode.c": "en",
            "knowledgeResponseType": "application/json"
        }
        
        with httpx.Client(timeout=15.0, headers=REQUEST_HEADERS) as client:
            response = client.get(MEDLINEPLUS_API, params=params)
            
            if response.status_code != 200:
                # Try alternate search approach
                return _search_medlineplus_web(query)
            
            data = response.json()
            
            # Parse the response
            feed = data.get("feed", {})
            entries = feed.get("entry", [])
            
            if not entries:
                return _search_medlineplus_web(query)
            
            output = ["**From NIH MedlinePlus:**\n"]
            
            for entry in entries[:3]:  # Limit to top 3 results
                title = entry.get("title", {}).get("_value", "Unknown")
                summary = entry.get("summary", {}).get("_value", "")
                link = ""
                
                for l in entry.get("link", []):
                    if l.get("rel") == "alternate":
                        link = l.get("href", "")
                        break
                
                output.append(f"**{title}**")
                if summary:
                    # Clean up summary (remove HTML tags)
                    clean_summary = summary.replace("<p>", "").replace("</p>", "\n")
                    clean_summary = clean_summary.replace("<ul>", "").replace("</ul>", "")
                    clean_summary = clean_summary.replace("<li>", "• ").replace("</li>", "\n")
                    output.append(clean_summary[:1000])  # Limit length
                if link:
                    output.append(f"More info: {link}")
                output.append("")
            
            return "\n".join(output)
            
    except Exception as e:
        print(f"[DiseaseResearcher] MedlinePlus error: {e}")
        return _search_medlineplus_web(query)


def _search_medlineplus_web(query: str) -> Optional[str]:
    """Fallback: Search MedlinePlus web search API."""
    try:
        # Use the MedlinePlus web services search
        search_url = "https://wsearch.nlm.nih.gov/ws/query"
        params = {
            "db": "healthTopics",
            "term": query,
            "retmax": 5
        }
        
        with httpx.Client(timeout=15.0, headers=REQUEST_HEADERS) as client:
            response = client.get(search_url, params=params)
            
            if response.status_code != 200:
                return None
            
            # Parse XML response (basic parsing)
            text = response.text
            
            # Extract titles and snippets from XML
            output = ["**From NIH MedlinePlus:**\n"]
            
            # Simple extraction of document content
            import re
            docs = re.findall(r'<document[^>]*>(.*?)</document>', text, re.DOTALL)
            
            if not docs:
                return None
            
            for doc in docs[:3]:
                title_match = re.search(r'<content name="title">(.*?)</content>', doc)
                snippet_match = re.search(r'<content name="FullSummary">(.*?)</content>', doc, re.DOTALL)
                url_match = re.search(r'<content name="altTitle"[^>]*>(https?://[^<]+)</content>', doc)
                
                if title_match:
                    title = title_match.group(1).strip()
                    output.append(f"**{title}**")
                
                if snippet_match:
                    snippet = snippet_match.group(1).strip()
                    # Clean HTML
                    snippet = re.sub(r'<[^>]+>', '', snippet)
                    snippet = snippet[:800]  # Limit length
                    output.append(snippet)
                
                if url_match:
                    output.append(f"Link: {url_match.group(1)}")
                
                output.append("")
            
            if len(output) > 2:
                return "\n".join(output)
            return None
            
    except Exception as e:
        print(f"[DiseaseResearcher] MedlinePlus web search error: {e}")
        return None


def _search_nci_dictionary(query: str) -> Optional[str]:
    """Search NCI Cancer Dictionary for cancer-specific terminology."""
    try:
        params = {
            "searchText": query,
            "matchType": "Begins",
            "size": 5,
            "from": 0
        }
        
        with httpx.Client(timeout=15.0, headers=REQUEST_HEADERS) as client:
            response = client.get(
                f"{NCI_DICT_API}/search/Cancer.gov",
                params=params
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            results = data.get("results", [])
            
            if not results:
                # Try contains match
                params["matchType"] = "Contains"
                response = client.get(
                    f"{NCI_DICT_API}/search/Cancer.gov",
                    params=params
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
            
            if not results:
                return None
            
            output = ["**From National Cancer Institute:**\n"]
            
            for result in results[:3]:
                term_name = result.get("termName", "Unknown")
                definition = result.get("definition", {}).get("text", "")
                
                # Get related terms/aliases
                aliases = result.get("aliases", [])
                alias_names = [a.get("name", "") for a in aliases if a.get("name")]
                
                output.append(f"**{term_name}**")
                if definition:
                    # Clean HTML from definition
                    import re
                    clean_def = re.sub(r'<[^>]+>', '', definition)
                    output.append(clean_def[:600])
                
                if alias_names:
                    output.append(f"Also known as: {', '.join(alias_names[:5])}")
                
                output.append("")
            
            return "\n".join(output)
            
    except Exception as e:
        print(f"[DiseaseResearcher] NCI search error: {e}")
        return None

