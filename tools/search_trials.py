from agents import function_tool
import httpx
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode, quote
from tools.cache import add_to_trial_cache
import xml.etree.ElementTree as ET


BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
LEGACY_API_URL = "https://classic.clinicaltrials.gov/api/query/study_fields"

# Browser-like headers to avoid blocking
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}


@function_tool
def search_clinical_trials(
    condition: Optional[str] = None,
    intervention: Optional[str] = None,
    location: Optional[str] = None,
    status: Optional[str] = None,
    phase: Optional[str] = None,
    study_type: Optional[str] = None,
    sponsor: Optional[str] = None,
    keyword: Optional[str] = None,
    nct_id: Optional[str] = None,
    page_size: int = 50
) -> str:
    """
    Search for clinical trials on ClinicalTrials.gov based on various criteria.
    
    Args:
        condition: Medical condition or disease (e.g., "type 2 diabetes", "breast cancer")
        intervention: Treatment or intervention being studied (e.g., "aspirin", "chemotherapy")
        location: Geographic location for trials (e.g., "California", "New York", "United States")
        status: Recruitment status. Options: RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, 
                COMPLETED, ENROLLING_BY_INVITATION, SUSPENDED, TERMINATED, WITHDRAWN
        phase: Trial phase. Options: EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4, NA
        study_type: Type of study. Options: INTERVENTIONAL, OBSERVATIONAL, EXPANDED_ACCESS
        sponsor: Sponsor or collaborator name (e.g., "Pfizer", "NIH")
        keyword: General keyword search across all fields
        nct_id: Specific NCT identifier (e.g., "NCT04280705")
        page_size: Number of results to return (default: 10, max: 100)
    
    Returns:
        A formatted summary of matching clinical trials with key details
    """
    print(f"[Tool] Searching ClinicalTrials.gov - condition: {condition}, intervention: {intervention}, location: {location}, status: {status}")
    
    # Store the query parameters
    query_params = {
        "condition": condition,
        "intervention": intervention,
        "location": location,
        "status": status,
        "phase": phase,
        "study_type": study_type,
        "sponsor": sponsor,
        "keyword": keyword,
        "nct_id": nct_id,
        "page_size": page_size
    }
    
    # Build query parameters
    params = {
        "format": "json",
        "pageSize": min(page_size, 100),
    }
    
    # Use the correct query parameters for API v2
    if condition:
        params["query.cond"] = condition
    
    if intervention:
        params["query.intr"] = intervention
    
    if location:
        # Clean up location for better API matching
        # The API's query.locn does text search which can be too restrictive
        # Simplify location to improve matches
        clean_location = location
        
        # Extract just city/state if a specific institution is mentioned
        # This helps find more trials since institutions are often listed differently
        location_lower = location.lower()
        
        # If it's a well-known city, use simplified form
        city_state_map = {
            "new york": "New York, NY",
            "nyc": "New York, NY",
            "boston": "Boston, MA",
            "los angeles": "Los Angeles, CA",
            "la": "Los Angeles, CA",
            "chicago": "Chicago, IL",
            "houston": "Houston, TX",
            "philadelphia": "Philadelphia, PA",
            "san francisco": "San Francisco, CA",
            "seattle": "Seattle, WA",
            "miami": "Miami, FL",
            "atlanta": "Atlanta, GA",
            "denver": "Denver, CO",
            "phoenix": "Phoenix, AZ",
            "dallas": "Dallas, TX",
            "san diego": "San Diego, CA",
            "baltimore": "Baltimore, MD",
            "cleveland": "Cleveland, OH",
            "pittsburgh": "Pittsburgh, PA",
            "minneapolis": "Minneapolis, MN",
            "detroit": "Detroit, MI",
            "st. louis": "Saint Louis, MO",
            "tampa": "Tampa, FL",
        }
        
        # Check if any city name is in the location
        for city, city_state in city_state_map.items():
            if city in location_lower:
                clean_location = city_state
                break
        
        # Also try using filter.geo for distance-based search if we have a known city
        # For now, just use the cleaned location
        params["query.locn"] = clean_location
    
    if keyword or sponsor or nct_id:
        # General term search
        term_parts = []
        if keyword:
            term_parts.append(keyword)
        if sponsor:
            term_parts.append(sponsor)
        if nct_id:
            term_parts.append(nct_id)
        params["query.term"] = " ".join(term_parts)
    
    # Status filter - can be multiple values
    if status:
        status_map = {
            "recruiting": "RECRUITING",
            "active": "ACTIVE_NOT_RECRUITING",
            "completed": "COMPLETED",
            "not yet recruiting": "NOT_YET_RECRUITING",
            "enrolling by invitation": "ENROLLING_BY_INVITATION",
            "suspended": "SUSPENDED",
            "terminated": "TERMINATED",
            "withdrawn": "WITHDRAWN"
        }
        mapped_status = status_map.get(status.lower(), status.upper())
        params["filter.overallStatus"] = mapped_status
    
    # Phase filter
    if phase:
        phase_map = {
            "1": "PHASE1",
            "2": "PHASE2", 
            "3": "PHASE3",
            "4": "PHASE4",
            "early phase 1": "EARLY_PHASE1",
            "phase 1": "PHASE1",
            "phase 2": "PHASE2",
            "phase 3": "PHASE3",
            "phase 4": "PHASE4",
            "n/a": "NA",
            "not applicable": "NA"
        }
        mapped_phase = phase_map.get(phase.lower(), phase.upper())
        params["filter.phase"] = mapped_phase
    
    # Study type filter
    if study_type:
        type_map = {
            "interventional": "INTERVENTIONAL",
            "observational": "OBSERVATIONAL",
            "expanded access": "EXPANDED_ACCESS"
        }
        mapped_type = type_map.get(study_type.lower(), study_type.upper())
        params["filter.studyType"] = mapped_type
    
    # Debug: print the actual request
    print(f"[API Request] {BASE_URL}?{urlencode(params)}")
    
    try:
        with httpx.Client(timeout=30.0, headers=REQUEST_HEADERS) as client:
            response = client.get(BASE_URL, params=params)
            
            # Debug: print response status
            print(f"[API Response] Status: {response.status_code}")
            
            if response.status_code == 400:
                # Print error details
                print(f"[API Error] {response.text[:500]}")
                return f"Error: Invalid search parameters. Please try simplifying your search. Details: {response.text[:200]}"
            
            response.raise_for_status()
            data = response.json()
        
        studies = data.get("studies", [])
        total_count = data.get("totalCount", len(studies))  # Fallback to actual count
        
        # Debug: print what we got
        print(f"[API Data] totalCount: {data.get('totalCount')}, studies returned: {len(studies)}")
        
        if not studies:
            # Don't clear cache - other parallel searches may have results
            # But DO track this search so the UI knows it was attempted
            add_to_trial_cache(query_params, 0, [])  # Record search with 0 results
            
            search_desc = []
            if condition: search_desc.append(f"condition '{condition}'")
            if intervention: search_desc.append(f"intervention '{intervention}'")
            if location: search_desc.append(f"location '{location}'")
            if sponsor: search_desc.append(f"sponsor '{sponsor}'")
            search_str = ", ".join(search_desc) if search_desc else "the specified criteria"
            print(f"[Search] No results for: {search_str}")
            return f"SEARCH RESULT: 0 trials found. No clinical trials match {search_str}. This search returned zero results from ClinicalTrials.gov."
        
        # Use actual count if totalCount wasn't provided or is 0
        display_total = total_count if total_count > 0 else len(studies)
        
        # Build structured trial data for cache
        structured_trials: List[Dict[str, Any]] = []
        
        # Format results with clear count prefix
        results = [f"SEARCH RESULT: {display_total} trials found. Showing top {len(studies)} results:\n"]
        
        for i, study in enumerate(studies, 1):
            protocol = study.get("protocolSection", {})
            id_module = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})
            design_module = protocol.get("designModule", {})
            sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
            description_module = protocol.get("descriptionModule", {})
            conditions_module = protocol.get("conditionsModule", {})
            interventions_module = protocol.get("armsInterventionsModule", {})
            eligibility_module = protocol.get("eligibilityModule", {})
            contacts_module = protocol.get("contactsLocationsModule", {})
            
            nct = id_module.get("nctId", "N/A")
            title = id_module.get("briefTitle", "No title")
            official_title = id_module.get("officialTitle", "")
            overall_status = status_module.get("overallStatus", "Unknown")
            phases = design_module.get("phases", [])
            phase_str = ", ".join(phases) if phases else "N/A"
            enrollment_info = design_module.get("enrollmentInfo", {})
            enrollment = enrollment_info.get("count", "N/A") if enrollment_info else "N/A"
            
            # Sponsor
            lead_sponsor = sponsor_module.get("leadSponsor", {})
            sponsor_name = lead_sponsor.get("name", "Unknown")
            
            # Conditions
            conditions = conditions_module.get("conditions", [])
            conditions_str = ", ".join(conditions[:3]) if conditions else "N/A"
            if len(conditions) > 3:
                conditions_str += f" (+{len(conditions) - 3} more)"
            
            # Interventions
            interventions = interventions_module.get("interventions", [])
            intervention_names = [i.get("name", "") for i in interventions[:3] if i.get("name")]
            interventions_str = ", ".join(intervention_names) if intervention_names else "N/A"
            if len(interventions) > 3:
                interventions_str += f" (+{len(interventions) - 3} more)"
            
            # Locations
            locations = contacts_module.get("locations", [])
            location_strs = []
            location_data = []
            for loc in locations:
                city = loc.get("city", "")
                state = loc.get("state", "")
                country = loc.get("country", "")
                facility = loc.get("facility", "")
                loc_parts = [p for p in [city, state, country] if p]
                if loc_parts:
                    location_strs.append(", ".join(loc_parts))
                location_data.append({
                    "facility": facility,
                    "city": city,
                    "state": state,
                    "country": country
                })
            locations_str = "; ".join(location_strs[:3]) if location_strs else "Not specified"
            if len(locations) > 3:
                locations_str += f" (+{len(locations) - 3} more sites)"
            
            # Eligibility
            min_age = eligibility_module.get("minimumAge", "N/A")
            max_age = eligibility_module.get("maximumAge", "N/A")
            sex_elig = eligibility_module.get("sex", "All")
            eligibility_criteria = eligibility_module.get("eligibilityCriteria", "")
            
            # Brief summary
            summary = description_module.get("briefSummary", "")
            summary_truncated = summary[:200] + "..." if summary and len(summary) > 200 else summary
            
            # Store structured data in cache
            trial_data = {
                "nct_id": nct,
                "title": title,
                "official_title": official_title,
                "status": overall_status,
                "phase": phases,
                "phase_display": phase_str,
                "sponsor": sponsor_name,
                "conditions": conditions,
                "interventions": [i.get("name", "") for i in interventions],
                "enrollment": enrollment,
                "eligibility": {
                    "min_age": min_age,
                    "max_age": max_age,
                    "sex": sex_elig,
                    "criteria": eligibility_criteria
                },
                "locations": location_data,
                "summary": summary,
                "link": f"https://clinicaltrials.gov/study/{nct}"
            }
            structured_trials.append(trial_data)
            
            result = f"""
---
**{i}. {title}**
- **NCT ID:** {nct}
- **Status:** {overall_status}
- **Phase:** {phase_str}
- **Sponsor:** {sponsor_name}
- **Conditions:** {conditions_str}
- **Interventions:** {interventions_str}
- **Enrollment:** {enrollment} participants
- **Eligibility:** Ages {min_age} to {max_age}, {sex_elig}
- **Locations:** {locations_str}
- **Summary:** {summary_truncated if summary_truncated else 'No summary available'}
- **Link:** https://clinicaltrials.gov/study/{nct}
"""
            results.append(result)
        
        # Add to the shared cache (accumulates across multiple searches)
        add_to_trial_cache(query_params, display_total, structured_trials)
        
        # Build search URL for user
        search_params = []
        if condition:
            search_params.append(f"cond={condition}")
        if intervention:
            search_params.append(f"intr={intervention}")
        if location:
            search_params.append(f"locn={location}")
        search_url = "https://clinicaltrials.gov/search?" + "&".join(search_params) if search_params else "https://clinicaltrials.gov/search"
        
        results.append(f"\n---\nView all results: {search_url}")
        
        return "".join(results)
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            print(f"[API] Got 403, trying legacy API fallback...")
            return _search_legacy_api(condition, intervention, location, status, query_params)
        return f"Error searching ClinicalTrials.gov: HTTP {e.response.status_code}. Please try simplifying your search."
    except httpx.RequestError as e:
        print(f"[API] Connection error, trying legacy API fallback...")
        return _search_legacy_api(condition, intervention, location, status, query_params)
    except Exception as e:
        print(f"[Error] {str(e)}")
        return f"Error searching clinical trials: {str(e)}. Please try again with different search criteria."


def _search_legacy_api(condition: str, intervention: str, location: str, status: str, query_params: dict) -> str:
    """Fallback to the legacy ClinicalTrials.gov API."""
    try:
        # Build expression for legacy API
        expr_parts = []
        if condition:
            expr_parts.append(f"AREA[Condition]{condition}")
        if intervention:
            expr_parts.append(f"AREA[Intervention]{intervention}")
        if location:
            expr_parts.append(f"AREA[LocationCountry]United States AND AREA[LocationCity]{location}")
        if status and status.lower() == "recruiting":
            expr_parts.append("AREA[OverallStatus]Recruiting")
        
        expr = " AND ".join(expr_parts) if expr_parts else "cancer"
        
        params = {
            "expr": expr,
            "fields": "NCTId,BriefTitle,OverallStatus,Phase,LeadSponsorName,Condition,InterventionName,LocationCity,BriefSummary",
            "min_rnk": 1,
            "max_rnk": 20,
            "fmt": "json"
        }
        
        print(f"[Legacy API] Trying: {LEGACY_API_URL}?{urlencode(params)}")
        
        with httpx.Client(timeout=30.0, headers=REQUEST_HEADERS, follow_redirects=True) as client:
            response = client.get(LEGACY_API_URL, params=params)
            print(f"[Legacy API] Status: {response.status_code}")
            
            if response.status_code == 403:
                # Both APIs blocked - request client-side search
                print("[API] Both APIs blocked (403), requesting client-side search")
                return _create_client_side_search_request(condition, intervention, location, status, query_params)
            
            response.raise_for_status()
            data = response.json()
        
        studies = data.get("StudyFieldsResponse", {}).get("StudyFields", [])
        n_found = data.get("StudyFieldsResponse", {}).get("NStudiesFound", 0)
        
        if not studies:
            add_to_trial_cache(query_params, 0, [])
            return f"SEARCH RESULT: 0 trials found for this search."
        
        structured_trials = []
        results = [f"SEARCH RESULT: {n_found} trials found. Showing top {len(studies)} results:\n"]
        
        for i, study in enumerate(studies, 1):
            nct = study.get("NCTId", ["N/A"])[0] if study.get("NCTId") else "N/A"
            title = study.get("BriefTitle", ["No title"])[0] if study.get("BriefTitle") else "No title"
            overall_status = study.get("OverallStatus", ["Unknown"])[0] if study.get("OverallStatus") else "Unknown"
            phases = study.get("Phase", [])
            phase_str = ", ".join(phases) if phases else "N/A"
            sponsor = study.get("LeadSponsorName", ["Unknown"])[0] if study.get("LeadSponsorName") else "Unknown"
            conditions = study.get("Condition", [])
            conditions_str = ", ".join(conditions[:3]) if conditions else "Not specified"
            interventions = study.get("InterventionName", [])
            interventions_str = ", ".join(interventions[:3]) if interventions else "Not specified"
            locations = study.get("LocationCity", [])
            locations_str = ", ".join(locations[:3]) if locations else "Not specified"
            summary = study.get("BriefSummary", [""])[0] if study.get("BriefSummary") else ""
            summary_truncated = summary[:200] + "..." if len(summary) > 200 else summary
            
            trial_data = {
                "nct_id": nct,
                "title": title,
                "status": overall_status,
                "phase": phase_str,
                "phase_display": phase_str,
                "sponsor": sponsor,
                "conditions": conditions_str,
                "interventions": interventions_str,
                "enrollment": "N/A",
                "eligibility": {},
                "locations": locations_str,
                "summary": summary,
                "link": f"https://clinicaltrials.gov/study/{nct}"
            }
            structured_trials.append(trial_data)
            
            result = f"""
---
**{i}. {title}**
- **NCT ID:** {nct}
- **Status:** {overall_status}
- **Phase:** {phase_str}
- **Sponsor:** {sponsor}
- **Conditions:** {conditions_str}
- **Interventions:** {interventions_str}
- **Locations:** {locations_str}
- **Summary:** {summary_truncated if summary_truncated else 'No summary available'}
- **Link:** https://clinicaltrials.gov/study/{nct}
"""
            results.append(result)
        
        add_to_trial_cache(query_params, n_found, structured_trials)
        return "".join(results)
        
    except Exception as e:
        print(f"[Legacy API Error] {str(e)}")
        # Fallback to client-side search
        return _create_client_side_search_request(condition, intervention, location, status, query_params)


def _create_client_side_search_request(condition: str, intervention: str, location: str, status: str, query_params: dict) -> str:
    """
    Create a special marker that tells the frontend to perform the search client-side.
    The frontend will detect this marker and make the API call from the user's browser.
    """
    import json
    
    search_request = {
        "condition": condition or "",
        "intervention": intervention or "",
        "location": location or "",
        "status": status or "RECRUITING",
        "query_params": query_params
    }
    
    print(f"[Client-Side Search] Requesting browser search for: {condition}, {location}")
    
    # Return as a special JSON string that server.py will detect and forward to frontend
    return f"__CLIENT_SEARCH__:{json.dumps(search_request)}"
