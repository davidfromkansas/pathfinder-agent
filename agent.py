from agents import Agent, Runner, SQLiteSession
from tools import all_tools
import json
import os
import re

# Use /tmp for Railway (writable), fallback to local data dir
if os.environ.get('RAILWAY_ENVIRONMENT'):
    DATA_DIR = '/tmp/data'
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

try:
    os.makedirs(DATA_DIR, exist_ok=True)
    SESSION_DB_PATH = os.path.join(DATA_DIR, 'sessions.db')
    print(f"[Agent] Session DB path: {SESSION_DB_PATH}", flush=True)
except Exception as e:
    print(f"[Agent] Could not create data dir: {e}", flush=True)
    SESSION_DB_PATH = None

# Load system prompt from markdown file
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')
SYSTEM_PROMPT_PATH = os.path.join(PROMPTS_DIR, 'system_prompt.md')

def load_system_prompt() -> str:
    """Load the system prompt from the markdown file."""
    with open(SYSTEM_PROMPT_PATH, 'r') as f:
        return f.read()

system_prompt = load_system_prompt()

clinical_agent = Agent(
    name="Clinical Trials Agent",
    instructions=system_prompt,
    tools=all_tools,
    model="gpt-5.2"
)


def get_session(session_id: str):
    """Get or create a session for the given session ID."""
    if not SESSION_DB_PATH:
        print(f"[Agent] Session storage unavailable, running without memory", flush=True)
        return None
    try:
        return SQLiteSession(session_id, SESSION_DB_PATH)
    except Exception as e:
        print(f"[Agent] Session creation failed: {e}, running without memory", flush=True)
        return None




def remove_json_from_text(text: str) -> str:
    """Remove JSON-like structures from text to prevent raw JSON showing in chat."""
    if not text:
        return text
    
    result = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            # Try to find matching closing brace
            brace_count = 1
            j = i + 1
            while j < len(text) and brace_count > 0:
                if text[j] == '{':
                    brace_count += 1
                elif text[j] == '}':
                    brace_count -= 1
                j += 1
            
            if brace_count == 0:
                # Found complete JSON-like block, check if it looks like JSON
                block = text[i:j]
                if '"' in block and ':' in block:
                    # Skip this JSON block
                    print(f"[Filter] Removed JSON block ({len(block)} chars)", flush=True)
                    i = j
                    continue
            
        result.append(text[i])
        i += 1
    
    return ''.join(result)


def get_mode_instruction(mode: str) -> str:
    """Get additional instructions based on the search mode."""
    if mode == 'trials':
        return """
[MODE: CLINICAL TRIALS ONLY]
The user has explicitly requested to find CLINICAL TRIALS only.
- Focus ONLY on searching ClinicalTrials.gov using search_clinical_trials
- Do NOT search PubMed or use research_disease tools
- Find as many relevant recruiting trials as possible
- Do NOT mention research papers in your response
"""
    elif mode == 'research':
        return """
[MODE: RESEARCH PAPERS ONLY]
The user has explicitly requested to find RESEARCH PAPERS only.
- Focus ONLY on searching PubMed using search_pubmed
- Run multiple PubMed searches with different queries to be comprehensive
- Do NOT search for clinical trials
- Do NOT mention clinical trials in your response
- Populate the Research tab with as many relevant articles as possible
"""
    else:
        # Auto mode - explicitly search BOTH
        return """
[MODE: AUTO - SEARCH BOTH]
Search BOTH PubMed AND ClinicalTrials.gov to give the user comprehensive results.

You MUST do BOTH of these:
1. Run 4-7 PubMed searches to populate the Research tab
2. Run 3-5 clinical trial searches to populate the Clinical Trials tab

Start with PubMed searches, then do clinical trial searches.
"""


async def get_agent_response_stream(message: str, session_id: str = None, mode: str = "auto"):
    """
    Send a message to the clinical agent and stream the response.
    Yields tuples of (event_type, data) where event_type is 'text' or 'tool_call'.
    
    If session_id is provided, the agent will remember previous messages in the conversation.
    Filters out JSON tool argument blobs from the text stream.
    
    Mode can be:
    - 'auto': Agent decides based on user query (default)
    - 'trials': Focus only on clinical trial search
    - 'research': Focus only on PubMed research
    """
    # Create session if session_id provided
    session = None
    if session_id:
        session = get_session(session_id)
        if session:
            print(f"[Agent] Using session: {session_id}", flush=True)
        else:
            print(f"[Agent] No session available, running stateless", flush=True)
    
    # Add mode-specific instructions to the message
    mode_instruction = get_mode_instruction(mode)
    full_message = f"{mode_instruction}\n{message}" if mode_instruction else message
    
    print(f"[Agent] Mode: {mode}", flush=True)
    
    try:
        result = Runner.run_streamed(clinical_agent, full_message, session=session)
    except Exception as e:
        print(f"[Agent] Failed to start stream: {e}", flush=True)
        raise
    
    # Buffer to accumulate text and filter out JSON blobs
    text_buffer = ""
    # Track the last tool called for associating with output
    last_tool_name = None
    
    async for event in result.stream_events():
        # Handle text delta events
        if event.type == "raw_response_event":
            data = event.data
            if hasattr(data, 'delta') and data.delta:
                text_buffer += data.delta
                
                # Process buffer - filter out JSON blobs
                # Check if we might have incomplete JSON (open brace without close)
                if '{' in text_buffer and text_buffer.count('{') > text_buffer.count('}'):
                    # Might be incomplete JSON, wait for more data
                    pass
                elif text_buffer:
                    # Clean any JSON from the buffer before yielding
                    cleaned = remove_json_from_text(text_buffer)
                    if cleaned.strip():
                        yield ('text', cleaned)
                    text_buffer = ""
        
        # Handle tool call events
        elif event.type == "run_item_stream_event":
            item = getattr(event, 'item', None)
            if item:
                item_type = getattr(item, 'type', None)
                
                if item_type == 'tool_call_item':
                    # Get tool info from raw_item
                    raw = getattr(item, 'raw_item', None)
                    tool_name = getattr(raw, 'name', 'unknown') if raw else 'unknown'
                    tool_args = getattr(raw, 'arguments', '{}') if raw else '{}'
                    
                    # Track this tool name for the upcoming output
                    last_tool_name = tool_name
                    
                    print(f"[Tool Call] {tool_name}({tool_args})", flush=True)
                    yield ('tool_call', {'name': tool_name, 'arguments': tool_args})
                    
                elif item_type == 'tool_call_output_item':
                    tool_output = getattr(item, 'output', '')
                    print(f"[Tool Output] {last_tool_name}: {tool_output[:100]}...", flush=True)
                    yield ('tool_output', {'output': tool_output, 'tool_name': last_tool_name})
    
    # Yield any remaining buffered text (filter JSON if present)
    if text_buffer:
        # Clean any remaining JSON from buffer
        cleaned = remove_json_from_text(text_buffer).strip()
        if cleaned:
            yield ('text', cleaned)
