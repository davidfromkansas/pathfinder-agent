import os
import json
import re
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
            word_count = 0
            async for event_type, event_data in get_agent_response_stream(prompt, session_id=None, mode="auto"):
                if event_type == 'text':
                    # Stream text chunks to frontend
                    yield f"data: {json.dumps({'type': 'text', 'content': event_data})}\n\n"
                    # Track word count to enforce 250 word limit
                    word_count += len(event_data.split())
                    if word_count >= 250:
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
            
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
    
    prompt = f"""Based on the user's search query and this clinical trial, provide a personalized recommendation on whether this trial might be relevant to them.

User's search: "{user_query}"

Trial Information:
- Title: {trial_title}
- Conditions: {trial_conditions}
- Treatments: {trial_interventions}
- Study Overview: {trial_summary}{eligibility_section}

IMPORTANT: Carefully review the Eligibility Criteria section above. Use it to assess whether the user might qualify for this trial. Mention specific eligibility requirements (age, disease stage, prior treatments, etc.) that are relevant to the user's search query.

Write a recommendation (maximum 250 words) in paragraph form that:
- Assesses whether this trial matches what the user is looking for
- Explains why it might or might not be a good fit
- References specific eligibility criteria that are relevant to the user's condition/search
- Highlights any potential eligibility barriers or requirements the user should be aware of
- Uses simple, non-technical language
- Be honest if the trial doesn't seem relevant - don't force a match

Write in paragraph form (NO bullet points). Be concise and helpful."""

    async def generate():
        try:
            accumulated_text = ""
            word_count = 0
            max_words = 250
            
            async for event_type, event_data in get_agent_response_stream(prompt, session_id=None, mode="auto"):
                if event_type == 'text':
                    accumulated_text += event_data
                    word_count = len(accumulated_text.split())
                    
                    # Always yield the text as it comes
                    yield f"data: {json.dumps({'type': 'text', 'content': event_data})}\n\n"
                    
                    # If we're approaching or past the limit, check for sentence completion
                    if word_count >= max_words - 10:  # Start checking when close to limit
                        # Look for the last complete sentence (ending with . ! or ?)
                        # Match sentence endings followed by space or end of string
                        sentence_pattern = r'[.!?](?:\s+|$)'
                        matches = list(re.finditer(sentence_pattern, accumulated_text))
                        
                        if matches:
                            last_sentence_end = matches[-1].end()
                            text_up_to_last_sentence = accumulated_text[:last_sentence_end]
                            words_in_complete_sentences = len(text_up_to_last_sentence.split())
                            
                            # If we have complete sentences and we're at/over the limit, stop
                            if words_in_complete_sentences >= max_words:
                                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                return
            
            # Stream ended naturally
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3000)
