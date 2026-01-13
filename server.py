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
                    yield f"data: {json.dumps({'type': 'tool_output', 'output': data['output'], 'tool_name': data.get('tool_name')})}\n\n"
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3000)
