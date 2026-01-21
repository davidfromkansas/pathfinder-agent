import os
import json
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from agent import get_agent_response_stream
from tools.cache import get_trial_cache, clear_trial_cache, get_research_cache, clear_research_cache

# Load environment variables from .env file
load_dotenv()

# Startup checks
api_key = os.environ.get("OPENAI_API_KEY")
if api_key:
    print(f"[Server] OPENAI_API_KEY is set (length: {len(api_key)})", flush=True)
else:
    print("[Server] WARNING: OPENAI_API_KEY is NOT set!", flush=True)

railway_env = os.environ.get("RAILWAY_ENVIRONMENT")
if railway_env:
    print(f"[Server] Running on Railway: {railway_env}", flush=True)

app = FastAPI()


@app.get("/")
async def index():
    return FileResponse("index.html")


@app.get("/health")
async def health():
    """Health check endpoint for debugging."""
    api_key = os.environ.get("OPENAI_API_KEY")
    return {
        "status": "ok",
        "api_key_set": bool(api_key),
        "api_key_preview": f"{api_key[:8]}..." if api_key else None,
        "railway": os.environ.get("RAILWAY_ENVIRONMENT"),
    }


@app.get("/styles.css")
async def styles():
    return FileResponse("styles.css")


@app.get("/main.js")
async def main_js():
    return FileResponse("main.js")


@app.post("/search")
async def search(request: Request):
    data = await request.json()
    condition = data.get("condition", "")
    session_id = data.get("session_id", None)
    mode = data.get("mode", "auto")  # 'auto', 'trials', or 'research'
    print(f"Message received: {condition} (session: {session_id}, mode: {mode})")
    
    # Clear caches for new search (but keep conversation memory)
    clear_trial_cache()
    clear_research_cache()
    
    async def generate():
        try:
            print(f"[Server] Starting stream (mode: {mode})...", flush=True)
            async for event_type, data in get_agent_response_stream(condition, session_id, mode):
                if event_type == 'text':
                    print(data, end="", flush=True)
                    yield f"data: {json.dumps({'type': 'text', 'content': data})}\n\n"
                elif event_type == 'tool_call':
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': data['name'], 'arguments': data['arguments']})}\n\n"
                elif event_type == 'tool_output':
                    output = data['output']
                    # Check if this is a client-side search request (server blocked by ClinicalTrials.gov)
                    if output.startswith('__CLIENT_SEARCH__:'):
                        try:
                            search_json = output.replace('__CLIENT_SEARCH__:', '')
                            search_data = json.loads(search_json)
                            print(f"[Server] Forwarding client-side search request: {search_data.get('condition')}", flush=True)
                            yield f"data: {json.dumps({'type': 'client_search', 'search': search_data})}\n\n"
                        except json.JSONDecodeError:
                            yield f"data: {json.dumps({'type': 'tool_output', 'output': output, 'tool_name': data.get('tool_name')})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'tool_output', 'output': output, 'tool_name': data.get('tool_name')})}\n\n"
            print("\n[Server] Stream finished, getting caches...", flush=True)
            
            # Send the research cache (for Research tab - first-line treatments)
            research_cache = get_research_cache()
            article_count = len(research_cache.get('pubmed_articles', []))
            print(f"[Server] Research cache has {article_count} articles", flush=True)
            yield f"data: {json.dumps({'type': 'research_cache', 'data': research_cache})}\n\n"
            
            # Send the trial cache (for Clinical Trials tab - experimental treatments)
            trial_cache = get_trial_cache()
            search_count = len(trial_cache.get('searches', []))
            trial_count = trial_cache.get('total_count', 0)
            print(f"[Server] Trial cache has {trial_count} unique trials from {search_count} searches", flush=True)
            yield f"data: {json.dumps({'type': 'trial_cache', 'data': trial_cache})}\n\n"
            
            print("[Server] Sending [DONE]", flush=True)
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_msg = str(e)
            print(f"[Server] Streaming error: {error_msg}", flush=True)
            import traceback
            traceback.print_exc()
            # Provide more context for connection errors
            if "connection" in error_msg.lower() or "connect" in error_msg.lower():
                error_msg = f"Connection error: {error_msg}. Please check OPENAI_API_KEY is set correctly."
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/summarize-trial")
async def summarize_trial(request: Request):
    """Generate a non-technical summary of a clinical trial's study overview - STREAMING."""
    data = await request.json()
    study_overview = data.get("study_overview", "")
    nct_id = data.get("nct_id", "")
    
    if not study_overview:
        return {"error": "No study overview provided"}
    
    # Create a prompt for the agent to summarize in non-technical terms
    prompt = f"""Please summarize the following clinical trial study overview in simple, non-technical language that a patient without a medical or science background can understand.

FORMAT: Write in paragraph form (NOT bullet points). Use 1-2 flowing paragraphs that read naturally.

Keep the summary to a maximum of 250 words. Focus ONLY on:
- What this clinical trial is about (the condition being treated)
- What drugs or treatments are being tested
- Why these drugs/treatments are relevant to the disease (how they work, why they might help)

IMPORTANT:
- Write in continuous paragraph form - NO bullet points, NO numbered lists, NO section headers
- Do NOT include details about what participants will do (procedures, visits, etc.)
- Do NOT include specific study endpoints or outcomes being measured
- Do explain any medical terms or concepts that might be unfamiliar
- Write as if explaining to a friend who has no medical background
- Keep it concise and focused on helping the patient understand the treatment approach
- Use smooth transitions between sentences to create a flowing narrative

Study Overview:
{study_overview}

Provide only the summary in paragraph form, no additional commentary."""
    
    async def generate():
        try:
            async for event_type, event_data in get_agent_response_stream(prompt, session_id=None, mode="auto"):
                if event_type == 'text':
                    # Stream text chunks to frontend
                    yield f"data: {json.dumps({'type': 'text', 'content': event_data})}\n\n"
            
            # Stream ended naturally - LLM will respect the 250 word limit from the prompt
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            print(f"[Server] Error generating summary: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/personalized-recommendation")
async def personalized_recommendation(request: Request):
    """Generate a personalized recommendation for whether a trial is relevant to the user."""
    data = await request.json()
    user_query = data.get("user_query", "")
    trial_title = data.get("trial_title", "")
    trial_conditions = data.get("trial_conditions", "")
    trial_interventions = data.get("trial_interventions", "")
    trial_summary = data.get("trial_summary", "")
    eligibility_criteria = data.get("eligibility_criteria", "")
    
    if not user_query:
        return {"error": "No user query provided"}
    
    # Create a prompt for personalized recommendation
    # Note: trial_summary may be brief (from API) since this runs in parallel with the full summary generation
    eligibility_section = f"\n\nEligibility Criteria:\n{eligibility_criteria}" if eligibility_criteria else ""
    
    prompt = f"""Based on the user's search query and this clinical trial, provide a concise, direct recommendation.

User's search: "{user_query}"

Trial Information:
- Title: {trial_title}
- Conditions: {trial_conditions}
- Treatments: {trial_interventions}
- Study Overview: {trial_summary}{eligibility_section}

IMPORTANT: 
- Do NOT restate the user's search query or condition - jump straight to the recommendation
- Focus on whether this trial is a good fit and why
- Reference specific eligibility criteria that are relevant (age, disease stage, prior treatments, etc.)
- Highlight any potential eligibility barriers or requirements
- Be direct and concise - get to the point quickly
- Use simple, non-technical language
- Be honest if the trial doesn't seem relevant - don't force a match

Write a recommendation (maximum 250 words) in paragraph form that:
- Directly states whether this trial is relevant (don't repeat the user's condition)
- Explains why it might or might not be a good fit
- Mentions specific eligibility requirements or barriers
- Uses simple, non-technical language

Write in paragraph form (NO bullet points). Be concise and direct - focus on the recommendation itself."""

    async def generate():
        try:
            async for event_type, event_data in get_agent_response_stream(prompt, session_id=None, mode="auto"):
                if event_type == 'text':
                    yield f"data: {json.dumps({'type': 'text', 'content': event_data})}\n\n"
            
            # Stream ended naturally - LLM will respect the 250 word limit from the prompt
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            print(f"[Server] Error generating recommendation: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/generate-email-context")
async def generate_email_context(request: Request):
    """Generate a natural, first-person summary of the user's condition from conversation messages."""
    data = await request.json()
    user_messages = data.get("user_messages", [])
    trial_summary = data.get("trial_summary", "")
    
    if not user_messages or len(user_messages) == 0:
        # Fallback to trial summary if no conversation
        if trial_summary:
            return {"context": f"I have read about this clinical trial and am interested in learning more. {trial_summary}"}
        return {"context": "I am interested in learning more about this clinical trial and whether I might be eligible to participate."}
    
    # Combine user messages
    conversation_text = " ".join(user_messages)
    
    # Create prompt for LLM to generate natural email context
    prompt = f"""Based on the following conversation messages from a patient searching for clinical trials, create a natural, first-person sentence that summarizes their medical condition for an email to a study contact.

The sentence should:
- Be written in first person (I, my, etc.)
- Sound natural and professional
- Focus ONLY on the medical condition/health issue
- Remove any search terms, location preferences, or trial-related language
- Be concise (1-2 sentences maximum)
- Start with something like "I have been diagnosed with..." or "I have..." or "I am dealing with..."

Conversation messages:
{conversation_text}

Generate ONLY the sentence(s) describing the condition - no additional commentary or explanation."""

    try:
        context_text = ""
        async for event_type, event_data in get_agent_response_stream(prompt, session_id=None, mode="auto"):
            if event_type == 'text':
                context_text += event_data
        
        # Clean up the response
        context_text = context_text.strip()
        
        # If we got a response, use it; otherwise fallback
        if context_text and len(context_text) > 10:
            return {"context": context_text}
        else:
            # Fallback
            if trial_summary:
                return {"context": f"I have read about this clinical trial and am interested in learning more. {trial_summary}"}
            return {"context": "I am interested in learning more about this clinical trial and whether I might be eligible to participate."}
            
    except Exception as e:
        print(f"[Server] Error generating email context: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        # Fallback on error
        if trial_summary:
            return {"context": f"I have read about this clinical trial and am interested in learning more. {trial_summary}"}
        return {"context": "I am interested in learning more about this clinical trial and whether I might be eligible to participate."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3000)
