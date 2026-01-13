const textarea = document.getElementById('conditionInput');
const landingView = document.getElementById('landingView');
const conversationView = document.getElementById('conversationView');
const messagesContainer = document.getElementById('messagesContainer');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');

// Trial Results Page elements
const trialResultsPage = document.getElementById('trialResultsPage');
const resultsList = document.getElementById('resultsList');
const resultsCount = document.getElementById('resultsCount');
const searchSummary = document.getElementById('searchSummary');

let isConversationMode = false;
let isStreaming = false;

// Session ID for conversation memory
let sessionId = null;

// Search mode: 'auto', 'trials', or 'research'
let currentSearchMode = 'auto';

function generateSessionId() {
    return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// Global trial cache - accumulates results from multiple searches (Clinical Trials tab)
let trialCache = {
    searches: [],      // List of all searches made
    allTrials: [],     // Accumulated unique trials
    totalCount: 0      // Total unique trials found
};

// Global research cache - disease info and PubMed articles (Research tab)
let researchCache = {
    diseaseName: '',
    diseaseInfo: [],
    pubmedArticles: [],
    firstLineTreatments: []
};

// Simple markdown parser for assistant messages
function parseMarkdown(text) {
    if (!text) return '';
    
    // Escape HTML first to prevent XSS
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Bold: **text** or __text__
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
    
    // Italic: *text* or _text_ (but not inside words)
    html = html.replace(/(?<!\w)\*([^*]+)\*(?!\w)/g, '<em>$1</em>');
    html = html.replace(/(?<!\w)_([^_]+)_(?!\w)/g, '<em>$1</em>');
    
    // Convert line breaks to handle bullet points
    const lines = html.split('\n');
    const processedLines = [];
    let inList = false;
    
    for (let line of lines) {
        // Check if line is a bullet point
        const bulletMatch = line.match(/^(\s*)-\s+(.+)$/);
        if (bulletMatch) {
            if (!inList) {
                processedLines.push('<ul>');
                inList = true;
            }
            processedLines.push(`<li>${bulletMatch[2]}</li>`);
        } else {
            if (inList) {
                processedLines.push('</ul>');
                inList = false;
            }
            // Regular line - add as paragraph if not empty
            if (line.trim()) {
                processedLines.push(`<p>${line}</p>`);
            } else {
                processedLines.push('<br>');
            }
        }
    }
    
    // Close any open list
    if (inList) {
        processedLines.push('</ul>');
    }
    
    return processedLines.join('');
}

// ========================================
// Search Mode Management
// ========================================

function setSearchMode(mode) {
    currentSearchMode = mode;
    
    // Update all mode toggle buttons (both landing and chat)
    document.querySelectorAll('.mode-toggle').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    
    // If setting a specific mode (not auto), switch to the corresponding tab
    if (mode === 'trials') {
        switchResultsTab('trials');
    } else if (mode === 'research') {
        switchResultsTab('research');
    }
    // For 'auto' mode, don't change the current tab
    
    console.log(`[Mode] Set to: ${mode}`);
}

// Auto-select the appropriate tab when results come in based on mode
function autoSelectTabForMode() {
    if (currentSearchMode === 'trials') {
        switchResultsTab('trials');
    } else if (currentSearchMode === 'research') {
        switchResultsTab('research');
    }
    // For 'auto' mode, keep current tab (usually trials is default)
}

function getModeDescription() {
    switch (currentSearchMode) {
        case 'trials':
            return 'Finding clinical trials only';
        case 'research':
            return 'Finding research papers only';
        default:
            return 'Auto-detecting (trials + research)';
    }
}

// Auto-resize textarea
textarea.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 144) + 'px';
});

// Handle initial search from landing page
async function handleSearch() {
    const condition = textarea.value.trim();
    if (condition) {
        // Transition to conversation view, then send message
        transitionToConversation(condition);
    } else {
        textarea.focus();
    }
}

// Set input disabled state
function setInputDisabled(disabled) {
    isStreaming = disabled;
    
    if (chatInput) {
        chatInput.disabled = disabled;
        chatInput.placeholder = disabled ? 'Waiting for response...' : 'Type your message...';
    }
    
    if (sendBtn) {
        sendBtn.disabled = disabled;
    }
    
    // Toggle streaming class on input container for visual feedback
    const inputContainer = document.querySelector('.input-container');
    if (inputContainer) {
        inputContainer.classList.toggle('streaming', disabled);
    }
}

// Send message to agent with streaming
async function sendMessageToAgent(message) {
    // Disable input while streaming
    setInputDisabled(true);
    
    // Don't create assistant message div yet - create it lazily when text arrives
    // This allows tool indicators to appear BEFORE the agent's response
    let messageDiv = null;
    
    // Track raw text for markdown parsing
    let rawText = '';
    
    // Helper to ensure message div exists
    function ensureMessageDiv() {
        if (!messageDiv) {
            messageDiv = document.createElement('div');
            messageDiv.className = 'message assistant';
            messageDiv.innerHTML = '';
            messagesContainer.appendChild(messageDiv);
        }
        return messageDiv;
    }
    
    try {
        const response = await fetch('/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                condition: message,
                session_id: sessionId,
                mode: currentSearchMode
            }),
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = ''; // Buffer for incomplete SSE data
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            
            // Keep the last incomplete line in the buffer
            buffer = lines.pop() || '';
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') {
                        console.log('%c✅ Stream complete', 'color: #4CAF50; font-weight: bold;');
                        
                        // Auto-select the appropriate tab based on mode
                        autoSelectTabForMode();
                        
                        // Log the trial cache after stream is done
                        console.log('%c📊 Trial Cache:', 'color: #9C27B0; font-weight: bold; font-size: 14px;');
                        console.log(`   Searches made: ${trialCache.searches.length}`);
                        trialCache.searches.forEach((s, i) => {
                            console.log(`   Search ${i+1}:`, s.query, `(${s.results_count} results)`);
                        });
                        console.log(`   Total unique trials: ${trialCache.totalCount}`);
                        console.table(trialCache.allTrials.map(t => ({
                            'NCT ID': t.nct_id,
                            'Title': t.title?.substring(0, 50) + '...',
                            'Status': t.status,
                            'Phase': t.phase_display,
                            'Sponsor': t.sponsor
                        })));
                    } else {
                        try {
                            const parsed = JSON.parse(data);
                            
                            if (parsed.type === 'text') {
                                rawText += parsed.content;
                                ensureMessageDiv().innerHTML = parseMarkdown(rawText);
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            } else if (parsed.type === 'tool_call') {
                                console.log('%c🔧 Tool Call: ' + parsed.name, 'color: #4CAF50; font-weight: bold;');
                                console.log('   Arguments:', parsed.arguments);
                                
                                // Show appropriate indicator in UI based on tool type
                                if (parsed.name === 'search_clinical_trials') {
                                    // Complete research indicator before showing search
                                    completeAllResearch();
                                    showSearchIndicator(parsed.arguments);
                                } else if (['search_pubmed', 'research_disease', 'get_trial_details'].includes(parsed.name)) {
                                    showResearchIndicator(parsed.name, parsed.arguments);
                                }
                            } else if (parsed.type === 'tool_output') {
                                console.log('%c📤 Tool Output:', 'color: #2196F3; font-weight: bold;');
                                console.log('   ', parsed.output.substring(0, 200) + (parsed.output.length > 200 ? '...' : ''));
                                
                                // Mark the research step as complete if applicable
                                if (parsed.tool_name && ['search_pubmed', 'research_disease', 'get_trial_details'].includes(parsed.tool_name)) {
                                    completeResearchStep(parsed.tool_name);
                                }
                            } else if (parsed.type === 'research_cache') {
                                // Store the research cache data
                                researchCache = {
                                    diseaseName: parsed.data.disease_name || '',
                                    diseaseInfo: parsed.data.disease_info || [],
                                    pubmedArticles: parsed.data.pubmed_articles || [],
                                };
                                console.log('%c📚 Research cache received:', 'color: #9C27B0; font-weight: bold;', 
                                    `${researchCache.pubmedArticles.length} articles`);
                                
                                // Show Research tab (PubMed articles)
                                if (researchCache.pubmedArticles.length > 0) {
                                    showResearchPage(researchCache);
                                }
                            } else if (parsed.type === 'trial_cache') {
                                // Debug: log raw data
                                console.log('%c📦 Raw cache data:', 'color: #607D8B;', parsed.data);
                                
                                // Store the trial cache data (new accumulated structure)
                                trialCache = {
                                    searches: parsed.data.searches || [],
                                    allTrials: parsed.data.all_trials || parsed.data.allTrials || [],
                                    totalCount: parsed.data.total_count || parsed.data.totalCount || 0
                                };
                                console.log('%c💾 Trial cache received:', 'color: #FF9800; font-weight: bold;', 
                                    `${trialCache.totalCount} unique trials from ${trialCache.searches.length} searches`);
                                
                                // Mark search indicator as complete with total count and search details
                                completeSearchIndicator(trialCache.totalCount, trialCache.searches);
                                
                                // Show Trial Results page if we have trials
                                if (trialCache.allTrials.length > 0) {
                                    showTrialResultsPage(trialCache);
                                }
                            } else if (parsed.type === 'client_side_search') {
                                // Server was blocked from ClinicalTrials.gov - run search from browser
                                console.log('%c🌐 Client-side search requested:', 'color: #E91E63; font-weight: bold;', parsed.search);
                                await performClientSideTrialSearch(parsed.search);
                            } else if (parsed.type === 'error') {
                                ensureMessageDiv().textContent = 'Sorry, I encountered an error: ' + parsed.message;
                            }
                        } catch (e) {
                            // Fallback for non-JSON data (backwards compatibility)
                            if (data && !data.startsWith('Error:')) {
                                ensureMessageDiv().textContent += data;
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            } else if (data.startsWith('Error:')) {
                                ensureMessageDiv().textContent = 'Sorry, I encountered an error: ' + data;
                            }
                        }
                    }
                }
            }
        }
        
    } catch (error) {
        console.error('Error:', error);
        ensureMessageDiv().textContent = 'Sorry, I encountered an error processing your request.';
    } finally {
        // Re-enable input when done
        setInputDisabled(false);
    }
}

// Transition from landing to conversation view
function transitionToConversation(initialMessage) {
    isConversationMode = true;
    
    // Generate a new session ID for this conversation
    sessionId = generateSessionId();
    console.log('%c🔑 New session started:', 'color: #9C27B0; font-weight: bold;', sessionId);
    
    // Fade out landing view
    landingView.classList.add('fade-out');
    
    // Wait for CSS transition to complete, then switch views
    landingView.addEventListener('transitionend', async function handler() {
        landingView.removeEventListener('transitionend', handler);
        
        landingView.classList.add('hidden');
        conversationView.classList.remove('hidden');
        conversationView.classList.add('fade-in');
        
        // Add the initial user message first
        addMessage(initialMessage, 'user');
        
        // Then send to agent
        await sendMessageToAgent(initialMessage);
        
        // Focus on chat input
        chatInput.focus();
    });
}

// Add a message to the conversation
function addMessage(text, sender) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;
    messageDiv.textContent = text;
    messagesContainer.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Send message in conversation mode
async function sendMessage() {
    if (isStreaming) return; // Prevent sending while streaming
    
    const message = chatInput.value.trim();
    if (message) {
        addMessage(message, 'user');
        chatInput.value = '';
        chatInput.style.height = 'auto';
        
        // Send to server
        await sendMessageToAgent(message);
    }
}

// Set example text
function setExample(text) {
    textarea.value = text;
    textarea.style.height = 'auto';
    textarea.focus();
}

// Handle Enter key for landing page textarea
textarea.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSearch();
    }
});

// Setup chat input
if (chatInput) {
    chatInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 144) + 'px';
    });
    
    chatInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
}

// ========================================
// Research Tools Indicator
// ========================================

let researchIndicatorDiv = null;
let researchSteps = [];
let researchCount = 0;

function showResearchIndicator(toolName, argsJson) {
    try {
        const args = typeof argsJson === 'string' ? JSON.parse(argsJson) : argsJson;
        
        // Create or get the research indicator container
        if (!researchIndicatorDiv) {
            researchIndicatorDiv = document.createElement('div');
            researchIndicatorDiv.className = 'research-indicator';
            researchIndicatorDiv.innerHTML = `
                <div class="research-indicator-header">
                    <span class="research-indicator-icon">📚</span>
                    <span class="research-indicator-title">Researching medical literature...</span>
                </div>
                <div class="research-indicator-list"></div>
            `;
            messagesContainer.appendChild(researchIndicatorDiv);
            researchSteps = [];
            researchCount = 0;
        }
        
        // Add this research step to the list
        const list = researchIndicatorDiv.querySelector('.research-indicator-list');
        researchCount++;
        
        // Build description based on tool type
        let source = '';
        let query = '';
        let linkUrl = '';
        
        if (toolName === 'search_pubmed') {
            source = 'PubMed';
            query = args.query || 'medical research';
            linkUrl = `https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(query)}`;
        } else if (toolName === 'research_disease') {
            query = args.disease_name || 'condition';
            // Use NCI for cancer-related conditions, Google Scholar as fallback for others
            const isCancer = /cancer|carcinoma|tumor|lymphoma|leukemia|melanoma|sarcoma|myeloma/i.test(query);
            if (isCancer) {
                source = 'NCI';
                linkUrl = `https://www.cancer.gov/search/results?swKeyword=${encodeURIComponent(query)}`;
            } else {
                source = 'NIH';
                // MedlinePlus search requires a different URL format
                linkUrl = `https://vsearch.nlm.nih.gov/vivisimo/cgi-bin/query-meta?v%3Aproject=medlineplus&v%3Asources=medlineplus-bundle&query=${encodeURIComponent(query)}`;
            }
        } else if (toolName === 'get_trial_details') {
            source = 'ClinicalTrials.gov';
            query = args.nct_id || 'trial';
            linkUrl = `https://clinicaltrials.gov/study/${query}`;
        }
        
        researchSteps.push({ toolName, query, source });
        
        // Update header title
        const titleEl = researchIndicatorDiv.querySelector('.research-indicator-title');
        titleEl.textContent = `Researching medical literature (${researchCount} ${researchCount === 1 ? 'query' : 'queries'})...`;
        
        const stepItem = document.createElement('div');
        stepItem.className = 'research-item';
        stepItem.dataset.tool = toolName;
        stepItem.dataset.index = researchCount;
        stepItem.innerHTML = `
            <span class="research-number">${researchCount}</span>
            <span class="research-source">${source}</span>
            <span class="research-query">${query}</span>
            <span class="research-status">
                <span class="research-spinner"></span>
            </span>
            ${linkUrl ? `
            <a href="${linkUrl}" target="_blank" rel="noopener noreferrer" class="research-link" title="View source">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                </svg>
            </a>
            ` : ''}
        `;
        list.appendChild(stepItem);
        
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    } catch (e) {
        console.error('Error showing research indicator:', e);
    }
}

function completeResearchStep(toolName) {
    if (researchIndicatorDiv) {
        const items = researchIndicatorDiv.querySelectorAll('.research-item');
        for (const item of items) {
            if (item.dataset.tool === toolName && !item.classList.contains('completed')) {
                item.classList.add('completed');
                const statusEl = item.querySelector('.research-status');
                if (statusEl) {
                    statusEl.innerHTML = '<span class="research-check">✓</span>';
                }
                break;
            }
        }
    }
}

function completeAllResearch() {
    if (researchIndicatorDiv) {
        researchIndicatorDiv.classList.add('completed');
        const iconEl = researchIndicatorDiv.querySelector('.research-indicator-icon');
        const titleEl = researchIndicatorDiv.querySelector('.research-indicator-title');
        
        iconEl.textContent = '✓';
        titleEl.textContent = `Research complete (${researchCount} ${researchCount === 1 ? 'source' : 'sources'})`;
        
        // Mark any remaining items as complete
        const items = researchIndicatorDiv.querySelectorAll('.research-item:not(.completed)');
        items.forEach(item => {
            item.classList.add('completed');
            const statusEl = item.querySelector('.research-status');
            if (statusEl) {
                statusEl.innerHTML = '<span class="research-check">✓</span>';
            }
        });
        
        // Reset for next query
        researchIndicatorDiv = null;
        researchSteps = [];
        researchCount = 0;
    }
}

// ========================================
// Search Indicator
// ========================================

let searchIndicatorDiv = null;
let searchCount = 0;

function buildClinicalTrialsUrl(args) {
    // Build a ClinicalTrials.gov search URL from the search parameters
    const baseUrl = 'https://clinicaltrials.gov/search';
    const params = new URLSearchParams();
    
    if (args.condition) params.set('cond', args.condition);
    if (args.intervention) params.set('intr', args.intervention);
    if (args.location) params.set('locStr', args.location);
    if (args.sponsor) params.set('spons', args.sponsor);
    if (args.keyword) params.set('term', args.keyword);
    
    // Status filter
    if (args.status) {
        const statusMap = {
            'RECRUITING': 'rec',
            'NOT_YET_RECRUITING': 'not',
            'ACTIVE_NOT_RECRUITING': 'act',
            'COMPLETED': 'com',
            'ENROLLING_BY_INVITATION': 'enr'
        };
        const statusCode = statusMap[args.status] || args.status.toLowerCase().substring(0, 3);
        params.set('aggFilters', `status:${statusCode}`);
    }
    
    // Phase filter
    if (args.phase) {
        params.set('aggFilters', (params.get('aggFilters') || '') + `,phase:${args.phase}`);
    }
    
    return `${baseUrl}?${params.toString()}`;
}

function showSearchIndicator(argsJson) {
    try {
        const args = typeof argsJson === 'string' ? JSON.parse(argsJson) : argsJson;
        
        // Create or get the search indicator container
        if (!searchIndicatorDiv) {
            searchIndicatorDiv = document.createElement('div');
            searchIndicatorDiv.className = 'search-indicator';
            searchIndicatorDiv.innerHTML = `
                <div class="search-indicator-header">
                    <span class="search-indicator-icon">🔍</span>
                    <span class="search-indicator-title">Searching ClinicalTrials.gov...</span>
                </div>
                <div class="search-indicator-list"></div>
            `;
            messagesContainer.appendChild(searchIndicatorDiv);
            searchCount = 0;
        }
        
        // Add this search to the list
        const list = searchIndicatorDiv.querySelector('.search-indicator-list');
        searchCount++;
        
        // Build a readable description with better formatting
        const parts = [];
        if (args.condition) parts.push(`<strong>${args.condition}</strong>`);
        if (args.location) parts.push(`in <em>${args.location}</em>`);
        if (args.sponsor) parts.push(`sponsored by <em>${args.sponsor}</em>`);
        if (args.intervention) parts.push(`with <em>${args.intervention}</em>`);
        if (args.phase) parts.push(`Phase ${args.phase}`);
        if (args.status && args.status !== 'RECRUITING') parts.push(`(${args.status.toLowerCase().replace('_', ' ')})`);
        
        // Build the ClinicalTrials.gov URL for this search
        const searchUrl = buildClinicalTrialsUrl(args);
        
        const searchItem = document.createElement('div');
        searchItem.className = 'search-item';
        searchItem.innerHTML = `
            <span class="search-number">${searchCount}</span>
            <span class="search-text">${parts.join(' ') || 'General search'}</span>
            <a href="${searchUrl}" target="_blank" rel="noopener noreferrer" class="search-link" title="View on ClinicalTrials.gov">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                </svg>
            </a>
        `;
        list.appendChild(searchItem);
        
        // Update title with count
        const titleEl = searchIndicatorDiv.querySelector('.search-indicator-title');
        titleEl.textContent = `Searching ClinicalTrials.gov (${searchCount} ${searchCount === 1 ? 'query' : 'queries'})...`;
        
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    } catch (e) {
        console.error('Error showing search indicator:', e);
    }
}

function completeSearchIndicator(totalTrials, searches) {
    if (searchIndicatorDiv) {
        // Mark as completed with success styling
        searchIndicatorDiv.classList.add('completed');
        
        // Update icon and title
        const iconEl = searchIndicatorDiv.querySelector('.search-indicator-icon');
        const titleEl = searchIndicatorDiv.querySelector('.search-indicator-title');
        
        iconEl.textContent = '✓';
        
        // Count how many searches actually found results
        const successfulSearches = searches ? searches.filter(s => s.results_count > 0).length : searchCount;
        const emptySearches = searches ? searches.filter(s => s.results_count === 0).length : 0;
        
        if (emptySearches > 0) {
            titleEl.textContent = `Found ${totalTrials} trial${totalTrials !== 1 ? 's' : ''} (${successfulSearches} of ${searchCount} searches had results)`;
        } else {
            titleEl.textContent = `Found ${totalTrials} trial${totalTrials !== 1 ? 's' : ''} from ${searchCount} search${searchCount !== 1 ? 'es' : ''}`;
        }
        
        // Mark individual searches that returned 0 results
        if (searches && searchIndicatorDiv) {
            const searchItems = searchIndicatorDiv.querySelectorAll('.search-item');
            searches.forEach((search, i) => {
                if (searchItems[i] && search.results_count === 0) {
                    searchItems[i].classList.add('empty-result');
                }
            });
        }
        
        // Reset for next search batch (but keep the indicator visible)
        searchIndicatorDiv = null;
        searchCount = 0;
    }
}

function clearSearchIndicator() {
    // Only remove if still in searching state (not completed)
    if (searchIndicatorDiv && !searchIndicatorDiv.classList.contains('completed')) {
        searchIndicatorDiv.remove();
        searchIndicatorDiv = null;
        searchCount = 0;
    }
}

// ========================================
// Trial Results Page
// ========================================

// Tab switching for results page
function switchResultsTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.results-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    
    // Update tab content
    document.getElementById('researchTabContent').classList.toggle('active', tabName === 'research');
    document.getElementById('trialsTabContent').classList.toggle('active', tabName === 'trials');
}

function showTrialResultsPage(cache) {
    const isAlreadyVisible = !trialResultsPage.classList.contains('hidden');
    
    // Update header stats
    resultsCount.textContent = cache.totalCount;
    searchSummary.textContent = `From ${cache.searches.length} search${cache.searches.length !== 1 ? 'es' : ''}`;
    
    // Reset filters
    const phaseFilter = document.getElementById('phaseFilter');
    const statusFilter = document.getElementById('statusFilter');
    if (phaseFilter) phaseFilter.value = 'all';
    if (statusFilter) statusFilter.value = 'all';
    
    // Clear existing results
    resultsList.innerHTML = '';
    
    // Render each trial card
    cache.allTrials.forEach((trial, index) => {
        const card = createTrialCard(trial);
        // Store trial data on the card for filtering
        card.dataset.phase = normalizePhase(trial.phase_display || trial.phase || '');
        card.dataset.status = (trial.status || '').toLowerCase();
        // Stagger animation for new results
        if (isAlreadyVisible) {
            card.style.animationDelay = `${index * 30}ms`;
            card.classList.add('card-refresh');
        }
        resultsList.appendChild(card);
    });
    
    // Show the results page and trigger split layout
    trialResultsPage.classList.remove('hidden');
    conversationView.classList.add('has-results');
    
    // Flash the badge to indicate update
    if (isAlreadyVisible) {
        resultsCount.classList.add('badge-pulse');
        setTimeout(() => resultsCount.classList.remove('badge-pulse'), 600);
    }
    
    // Clear filter count
    updateFilterCount();
    
    // Scroll results to top on refresh, chat to bottom
    resultsList.scrollTop = 0;
    setTimeout(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }, 100);
}

// ========================================
// Trial Filtering
// ========================================

function normalizePhase(phase) {
    if (!phase) return 'na';
    const p = phase.toLowerCase();
    if (p.includes('early phase 1') || p.includes('early_phase1')) return 'early';
    if (p.includes('phase 1/phase 2') || p.includes('phase1/phase2') || p === 'phase 1/2') return '1/2';
    if (p.includes('phase 2/phase 3') || p.includes('phase2/phase3') || p === 'phase 2/3') return '2/3';
    if (p.includes('phase 1') || p.includes('phase1') || p === '1') return '1';
    if (p.includes('phase 2') || p.includes('phase2') || p === '2') return '2';
    if (p.includes('phase 3') || p.includes('phase3') || p === '3') return '3';
    if (p.includes('phase 4') || p.includes('phase4') || p === '4') return '4';
    if (p === 'n/a' || p === 'na' || p === 'not applicable') return 'na';
    return 'na';
}

function applyTrialFilters() {
    const phaseFilter = document.getElementById('phaseFilter').value;
    const statusFilter = document.getElementById('statusFilter').value;
    
    const cards = document.querySelectorAll('.trial-card');
    let visibleCount = 0;
    
    cards.forEach(card => {
        const cardPhase = card.dataset.phase;
        const cardStatus = card.dataset.status;
        
        const phaseMatch = phaseFilter === 'all' || cardPhase === phaseFilter;
        const statusMatch = statusFilter === 'all' || cardStatus.includes(statusFilter);
        
        if (phaseMatch && statusMatch) {
            card.classList.remove('filtered-out');
            visibleCount++;
        } else {
            card.classList.add('filtered-out');
        }
    });
    
    updateFilterCount(visibleCount, cards.length);
}

function updateFilterCount(visible, total) {
    const filterCountEl = document.getElementById('filteredCount');
    if (!filterCountEl) return;
    
    if (visible === undefined || visible === total) {
        filterCountEl.textContent = '';
        filterCountEl.classList.remove('filtered');
    } else {
        filterCountEl.textContent = `Showing ${visible} of ${total}`;
        filterCountEl.classList.add('filtered');
    }
}

// ========================================
// Research Page (PubMed Articles)
// ========================================

function showResearchPage(cache) {
    const researchContent = document.getElementById('researchTabContent');
    const researchCountEl = document.getElementById('researchCount');
    
    // Update the count badge
    researchCountEl.textContent = cache.pubmedArticles.length;
    
    // Clear existing content
    researchContent.innerHTML = '';
    
    if (cache.pubmedArticles.length === 0) {
        researchContent.innerHTML = `
            <div class="tab-empty-state">
                <div class="empty-icon">📚</div>
                <h3>Research Articles</h3>
                <p>Relevant research from PubMed will appear here</p>
            </div>
        `;
        return;
    }
    
    let html = '<div class="research-content">';
    html += `
        <div class="research-section">
            <h3 class="research-section-title">
                <span class="section-icon">📚</span>
                Research Articles (${cache.pubmedArticles.length})
            </h3>
            <p class="section-subtitle">Ranked by relevance (Best Match)</p>
            <div class="article-list">
    `;
    
    cache.pubmedArticles.forEach(article => {
        html += `
            <div class="article-card">
                <div class="article-title">${article.title}</div>
                <div class="article-meta">
                    <span class="article-authors">${article.authors}</span>
                    <span class="article-journal">${article.journal}</span>
                    <span class="article-date">${article.date}</span>
                </div>
                <div class="article-footer">
                    <span class="article-type">${article.type}</span>
                    <a href="${article.url}" target="_blank" rel="noopener noreferrer" class="article-link">
                        Read on PubMed →
                    </a>
                </div>
            </div>
        `;
    });
    
    html += '</div></div></div>';
    researchContent.innerHTML = html;
    
    // Show the results page if not already visible
    trialResultsPage.classList.remove('hidden');
    conversationView.classList.add('has-results');
}

function createTrialCard(trial) {
    const card = document.createElement('div');
    card.className = 'trial-card';
    
    // Determine status styling
    const status = (trial.status || 'Unknown').toLowerCase();
    let statusClass = '';
    if (status.includes('recruiting')) statusClass = 'recruiting';
    else if (status.includes('active')) statusClass = 'active';
    else if (status.includes('completed')) statusClass = 'completed';
    
    // Build phase tag if available
    const phaseTag = trial.phase_display && trial.phase_display !== 'N/A' 
        ? `<span class="trial-tag phase">${trial.phase_display}</span>` 
        : '';
    
    // Build condition tags (max 2)
    const conditionTags = (trial.conditions || [])
        .slice(0, 2)
        .map(c => `<span class="trial-tag condition">${c}</span>`)
        .join('');
    
    const trialUrl = trial.link || `https://clinicaltrials.gov/study/${trial.nct_id}`;
    
    card.innerHTML = `
        <div class="trial-card-top">
            <span class="trial-nct">${trial.nct_id || 'N/A'}</span>
            <span class="trial-status ${statusClass}">${trial.status || 'Unknown'}</span>
        </div>
        <div class="trial-title">${trial.title || 'Untitled Trial'}</div>
        <div class="trial-tags">
            ${phaseTag}
            ${conditionTags}
        </div>
        <div class="trial-footer">
            <span class="trial-sponsor">${trial.sponsor || 'Unknown sponsor'}</span>
            <a class="trial-link" href="${trialUrl}" target="_blank" rel="noopener noreferrer">
                View details →
            </a>
        </div>
    `;
    
    // Make entire card clickable
    card.addEventListener('click', (e) => {
        if (e.target.tagName !== 'A') {
            window.open(trialUrl, '_blank', 'noopener,noreferrer');
        }
    });
    
    return card;
}

// Expose trialCache globally for debugging in console
window.trialCache = trialCache;

// ========================================
// Client-Side Clinical Trials Search
// ========================================

async function performClientSideTrialSearch(searchParams) {
    console.log('%c🔍 Performing client-side search...', 'color: #E91E63; font-weight: bold;');
    
    const { condition, intervention, location, status, query_params } = searchParams;
    
    // Build API parameters
    const params = new URLSearchParams();
    params.append('format', 'json');
    params.append('pageSize', '50');
    
    // Add fields to return
    const fields = [
        'NCTId', 'BriefTitle', 'OfficialTitle', 'OverallStatus', 'Phase',
        'LeadSponsorName', 'Condition', 'InterventionName', 'BriefSummary',
        'LocationCity', 'LocationState', 'LocationCountry', 'EligibilityCriteria',
        'MinimumAge', 'MaximumAge', 'Gender', 'EnrollmentCount'
    ];
    fields.forEach(f => params.append('fields', f));
    
    // Add condition filter
    if (condition) {
        params.append('query.cond', condition);
    }
    
    // Add intervention filter
    if (intervention) {
        params.append('query.intr', intervention);
    }
    
    // Add location filter
    if (location) {
        params.append('query.locn', location);
    }
    
    // Add status filter (default to recruiting)
    params.append('filter.overallStatus', status || 'RECRUITING');
    
    const apiUrl = `https://clinicaltrials.gov/api/v2/studies?${params.toString()}`;
    console.log('%c📡 API URL:', 'color: #9C27B0;', apiUrl);
    
    try {
        const response = await fetch(apiUrl);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        const studies = data.studies || [];
        const totalCount = data.totalCount || studies.length;
        
        console.log('%c✅ Client-side search successful:', 'color: #4CAF50; font-weight: bold;', 
            `${totalCount} trials found, ${studies.length} returned`);
        
        // Transform to our trial format
        const trials = studies.map(study => {
            const protocol = study.protocolSection || {};
            const id = protocol.identificationModule || {};
            const statusModule = protocol.statusModule || {};
            const design = protocol.designModule || {};
            const sponsor = protocol.sponsorCollaboratorsModule || {};
            const desc = protocol.descriptionModule || {};
            const conditions = protocol.conditionsModule || {};
            const interventions = protocol.armsInterventionsModule || {};
            const eligibility = protocol.eligibilityModule || {};
            const contacts = protocol.contactsLocationsModule || {};
            
            const phases = design.phases || [];
            const phaseStr = phases.join(', ') || 'N/A';
            
            const conditionsList = conditions.conditions || [];
            const interventionsList = (interventions.interventions || []).map(i => i.name);
            
            const locations = (contacts.locations || []).slice(0, 3).map(loc => 
                `${loc.city || ''}${loc.state ? ', ' + loc.state : ''}`
            ).filter(Boolean);
            
            return {
                nct_id: id.nctId || 'N/A',
                title: id.briefTitle || 'Untitled',
                status: statusModule.overallStatus || 'Unknown',
                phase: phaseStr,
                phase_display: phaseStr,
                sponsor: sponsor.leadSponsor?.name || 'Unknown',
                conditions: conditionsList.slice(0, 3).join(', ') || 'Not specified',
                interventions: interventionsList.slice(0, 3).join(', ') || 'Not specified',
                enrollment: design.enrollmentInfo?.count || 'N/A',
                eligibility: {
                    minAge: eligibility.minimumAge || 'N/A',
                    maxAge: eligibility.maximumAge || 'N/A',
                    sex: eligibility.sex || 'All'
                },
                locations: locations.join('; ') || 'Not specified',
                summary: (desc.briefSummary || '').substring(0, 300),
                link: `https://clinicaltrials.gov/study/${id.nctId}`
            };
        });
        
        // Build search URL for the indicator
        const searchUrl = `https://clinicaltrials.gov/search?cond=${encodeURIComponent(condition || '')}&locn=${encodeURIComponent(location || '')}&aggFilters=status:rec`;
        
        // Add to trial cache
        const searchEntry = {
            query: query_params || { condition, intervention, location, status },
            results_count: trials.length,
            url: searchUrl
        };
        
        // Merge with existing cache
        trialCache.searches.push(searchEntry);
        
        // Add trials (avoid duplicates by NCT ID)
        const existingIds = new Set(trialCache.allTrials.map(t => t.nct_id));
        trials.forEach(trial => {
            if (!existingIds.has(trial.nct_id)) {
                trialCache.allTrials.push(trial);
                existingIds.add(trial.nct_id);
            }
        });
        trialCache.totalCount = trialCache.allTrials.length;
        
        console.log('%c💾 Updated trial cache:', 'color: #FF9800; font-weight: bold;', 
            `${trialCache.totalCount} total trials from ${trialCache.searches.length} searches`);
        
        // Update search indicator
        completeSearchIndicator(trialCache.totalCount, trialCache.searches);
        
        // Show the results
        if (trialCache.allTrials.length > 0) {
            showTrialResultsPage(trialCache);
        }
        
    } catch (error) {
        console.error('%c❌ Client-side search failed:', 'color: #F44336; font-weight: bold;', error);
        
        // Show a helpful message to the user
        const searchUrl = `https://clinicaltrials.gov/search?cond=${encodeURIComponent(condition || '')}&locn=${encodeURIComponent(location || '')}&aggFilters=status:rec`;
        
        // Add a "failed" search entry
        trialCache.searches.push({
            query: query_params || { condition, intervention, location, status },
            results_count: 0,
            url: searchUrl,
            error: error.message
        });
        
        completeSearchIndicator(trialCache.totalCount, trialCache.searches);
    }
}
