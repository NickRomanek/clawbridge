/**
 * ClawBridge Dashboard - Frontend Application
 *
 * Communicates with the local ClawBridge service via REST API and WebSocket.
 * No build step required -- vanilla JS served directly from FastAPI.
 */

// ─── State ───────────────────────────────────────────────────────────────────

const state = {
  ws: null,
  tasks: [],
  engines: [],
  config: {},
  connected: false,
};

// ─── API Helpers ─────────────────────────────────────────────────────────────

const API_BASE = '';

async function api(method, path, body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(`${API_BASE}${path}`, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || 'API error');
  }
  return resp.json();
}

// ─── WebSocket ───────────────────────────────────────────────────────────────

function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${location.host}/ws`;

  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    state.connected = true;
    updateConnectionStatus(true);
    console.log('WebSocket connected');
  };

  state.ws.onclose = () => {
    state.connected = false;
    updateConnectionStatus(false);
    console.log('WebSocket disconnected -- reconnecting in 3s');
    setTimeout(connectWebSocket, 3000);
  };

  state.ws.onerror = () => {
    state.connected = false;
    updateConnectionStatus(false);
  };

  state.ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleWSMessage(msg);
  };
}

function handleWSMessage(msg) {
  switch (msg.type) {
    case 'task_update':
      upsertTask(msg.payload);
      break;
    case 'task_list':
      state.tasks = msg.payload;
      renderTasks();
      updateBrowserStatus();
      break;
    case 'engine_status':
      state.engines = msg.payload;
      renderEngines();
      break;
    case 'audit_event':
      addActivityEvent(msg.payload);
      break;
    case 'approval_request':
      showApprovalRequest(msg.payload);
      break;
    case 'browser_frame':
      console.log('Received browser frame:', msg.payload.frame?.substring(0, 50) + '...');
      updateLiveBrowser(msg.payload.frame);
      break;
    case 'pong':
      break;
    default:
      console.log('Unknown WS message:', msg.type);
  }
}

function updateLiveBrowser(frameBase64) {
  const card = document.getElementById('liveBrowserCard');
  const img = document.getElementById('browserFrame');
  const placeholder = document.getElementById('browserPlaceholder');
  const status = document.getElementById('browserStatus');

  if (!frameBase64) return;

  // Show card if hidden
  if (card.style.display === 'none') {
    card.style.display = 'flex';
  }

  // Update image
  img.src = `data:image/jpeg;base64,${frameBase64}`;
  img.style.display = 'block';
  placeholder.style.display = 'none';

  // Update status
  status.textContent = 'Active';
  status.className = 'status-badge status-active';
}

// ─── Task Management ─────────────────────────────────────────────────────────

async function submitTask(prompt, engine) {
  try {
    const task = await api('POST', '/api/tasks', { prompt, engine });
    upsertTask(task);
    return task;
  } catch (e) {
    alert(`Failed to submit task: ${e.message}`);
  }
}

function upsertTask(task) {
  const idx = state.tasks.findIndex(t => t.id === task.id);
  if (idx >= 0) {
    state.tasks[idx] = task;
  } else {
    state.tasks.unshift(task);
  }
  renderTasks();
  updateBrowserStatus();
}

function updateBrowserStatus() {
  const anyRunning = state.tasks.some(t => t.status === 'running');
  const status = document.getElementById('browserStatus');
  if (!anyRunning && status) {
    status.textContent = 'Idle';
    status.className = 'status-badge status-idle';
  }
}

async function pauseTask(id) {
  const task = await api('PATCH', `/api/tasks/${id}`, { action: 'pause' });
  upsertTask(task);
}

async function resumeTask(id) {
  const task = await api('PATCH', `/api/tasks/${id}`, { action: 'resume' });
  upsertTask(task);
}

async function cancelTask(id) {
  const task = await api('PATCH', `/api/tasks/${id}`, { action: 'cancel' });
  upsertTask(task);
}

// ─── Rendering ───────────────────────────────────────────────────────────────

function updateConnectionStatus(connected) {
  const el = document.getElementById('connectionStatus');
  const dot = el.querySelector('.status-dot');
  const text = el.querySelector('.status-text');

  dot.className = `status-dot ${connected ? 'connected' : 'error'}`;
  text.textContent = connected ? 'Connected' : 'Disconnected';
}

function renderEngines() {
  const container = document.getElementById('engineList');
  if (!state.engines.length) {
    container.innerHTML = '<p class="muted">No engines registered</p>';
    return;
  }

  container.innerHTML = state.engines.map(e => `
    <div class="engine-item">
      <span class="engine-name">${escapeHtml(e.display_name)}</span>
      <span class="engine-status ${e.status}">${e.status}</span>
    </div>
  `).join('');
}

function renderTasks() {
  const container = document.getElementById('taskList');
  const count = document.getElementById('taskCount');

  count.textContent = `${state.tasks.length} task${state.tasks.length !== 1 ? 's' : ''}`;

  if (!state.tasks.length) {
    container.innerHTML = '<p class="muted center">No tasks yet. Submit one to get started.</p>';
    return;
  }

  container.innerHTML = state.tasks.map(t => renderTaskItem(t)).join('');

  // Auto-scroll to bottom
  container.scrollTop = container.scrollHeight;
}

function renderTaskItem(task) {
  const time = new Date(task.created_at).toLocaleTimeString();
  const engine = task.engine === 'auto' ? 'Auto' : task.engine;

  let controls = '';
  if (task.status === 'running') {
    controls = `
      <button class="btn btn-sm btn-warning" onclick="pauseTask('${task.id}')">Pause</button>
      <button class="btn btn-sm btn-danger" onclick="cancelTask('${task.id}')">Stop</button>
    `;
  } else if (task.status === 'paused') {
    controls = `
      <button class="btn btn-sm btn-primary" onclick="resumeTask('${task.id}')">Resume</button>
      <button class="btn btn-sm btn-danger" onclick="cancelTask('${task.id}')">Cancel</button>
    `;
  }

  let result = '';
  if (task.result && task.result.summary) {
    const citations = (task.result.citations || []).map(c =>
      `<a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.title || c.url)}</a>`
    ).join('');

    result = `
      <div class="task-result-label">Result</div>
      <div class="task-result">${escapeHtml(task.result.summary)}</div>
      ${citations ? `<div class="task-citations">${citations}</div>` : ''}
    `;
  }

  let error = '';
  if (task.error) {
    error = `<div class="task-error">${escapeHtml(task.error)}</div>`;
  }

  return `
    <div class="task-item">
      <div class="task-header">
        <span class="task-prompt">${escapeHtml(task.prompt)}</span>
        <span class="task-badge ${task.status}">${task.status}</span>
      </div>
      <div class="task-meta">
        <span>${time}</span>
        <span>Engine: ${escapeHtml(engine)}</span>
        ${task.result ? `<span>${task.result.total_duration_ms}ms</span>` : ''}
      </div>
      ${controls ? `<div class="task-controls">${controls}</div>` : ''}
      ${result}
      ${error}
    </div>
  `;
}

function addActivityEvent(event) {
  const container = document.getElementById('activityFeed');

  // Remove placeholder text
  if (container.querySelector('.muted')) {
    container.innerHTML = '';
  }

  const time = new Date(event.timestamp).toLocaleTimeString();
  const html = `
    <div class="activity-item ${event.event_type}">
      <div>
        <span class="activity-time">${time}</span>
        <strong>${escapeHtml(event.event_type)}</strong>
      </div>
      <div class="activity-detail">${escapeHtml(event.detail || '')}</div>
    </div>
  `;

  container.insertAdjacentHTML('afterbegin', html);

  // Keep feed manageable
  while (container.children.length > 100) {
    container.removeChild(container.lastChild);
  }
}

async function loadConfig() {
  try {
    const config = await api('GET', '/api/config');
    state.config = config;

    const container = document.getElementById('configSummary');
    container.innerHTML = `
      <div class="config-row">
        <span class="config-label">Anthropic Key</span>
        <span class="config-value ${config.keys.anthropic_configured ? 'yes' : 'no'}">
          ${config.keys.anthropic_configured ? 'Configured' : 'Not set'}
        </span>
      </div>
      <div class="config-row">
        <span class="config-label">OpenAI Key</span>
        <span class="config-value ${config.keys.openai_configured ? 'yes' : 'no'}">
          ${config.keys.openai_configured ? 'Configured' : 'Not set'}
        </span>
      </div>
      <div class="config-row">
        <span class="config-label">OpenRouter Key</span>
        <span class="config-value ${config.keys.has_openrouter_key ? 'yes' : 'no'}">
          ${config.keys.has_openrouter_key ? 'Configured' : 'Not set'}
        </span>
      </div>
      <div class="config-row">
        <span class="config-label">Model</span>
        <span class="config-value">${escapeHtml(config.keys.default_model)}</span>
      </div>
      <div class="config-row">
        <span class="config-label">Policy</span>
        <span class="config-value">${escapeHtml(config.policy.mode)}</span>
      </div>
      <div class="config-row">
        <span class="config-label">Max Tasks</span>
        <span class="config-value">${config.policy.max_concurrent_tasks}</span>
      </div>
    `;
  } catch (e) {
    console.error('Failed to load config:', e);
  }
}

function showApprovalRequest(payload) {
  const result = confirm(
    `ClawBridge needs approval for a ${payload.action_class} action:\n\n` +
    `Action: ${payload.action}\n` +
    `Target: ${payload.target}\n` +
    `Reason: ${payload.reason}\n\n` +
    `Allow this action?`
  );

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({
      type: 'approval_response',
      step_id: payload.step_id,
      approved: result,
    }));
  }
}

// ─── Utilities ───────────────────────────────────────────────────────────────

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ─── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Form submission
  document.getElementById('taskForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const prompt = document.getElementById('taskPrompt').value.trim();
    const engine = document.getElementById('engineSelect').value;

    if (!prompt) return;

    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = 'Submitting...';

    await submitTask(prompt, engine);

    const taskPrompt = document.getElementById('taskPrompt');
    taskPrompt.value = '';
    taskPrompt.style.height = '48px'; // Reset height
    btn.disabled = false;
    btn.textContent = 'send'; // Keep icon
  });

  // Textarea auto-resize
  const taskPrompt = document.getElementById('taskPrompt');
  taskPrompt.addEventListener('input', function () {
    this.style.height = '48px';
    this.style.height = (this.scrollHeight) + 'px';
  });

  taskPrompt.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      document.getElementById('taskForm').dispatchEvent(new Event('submit'));
    }
  });

  // Load initial data
  loadConfig();

  // Settings Modal
  const modal = document.getElementById('settingsModal');
  const settingsBtn = document.getElementById('settingsBtn');
  const closeBtn = document.querySelector('.close-modal');
  const keysForm = document.getElementById('keysForm');

  settingsBtn.onclick = () => {
    // Fill form with current state
    document.getElementById('anthropicKey').value = '';
    document.getElementById('openaiKey').value = '';
    document.getElementById('openrouterKey').value = '';
    document.getElementById('defaultModel').value = state.config.keys?.default_model || '';
    document.getElementById('browserHeadless').checked = state.config.engines?.browser_use?.config?.headless ?? true;
    modal.classList.add('active');
  };

  closeBtn.onclick = () => modal.classList.remove('active');
  window.onclick = (e) => { if (e.target === modal) modal.classList.remove('active'); };

  keysForm.onsubmit = async (e) => {
    e.preventDefault();
    const saveBtn = document.getElementById('saveKeysBtn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    const payload = {
      default_model: document.getElementById('defaultModel').value.trim(),
      browser_headless: document.getElementById('browserHeadless').checked
    };

    const ant = document.getElementById('anthropicKey').value.trim();
    const oai = document.getElementById('openaiKey').value.trim();
    const or = document.getElementById('openrouterKey').value.trim();

    if (ant) payload.anthropic_api_key = ant;
    if (oai) payload.openai_api_key = oai;
    if (or) payload.openrouter_api_key = or;

    try {
      await api('POST', '/api/config/keys', payload);
      modal.classList.remove('active');
      await loadConfig();
      alert('Configuration saved. Engines are reloading.');
    } catch (err) {
      alert(`Failed to save: ${err.message}`);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Configuration';
    }
  };

  // Connect WebSocket for live updates
  connectWebSocket();

  // Sidebar Togle
  const toggleBtn = document.getElementById('toggleSidebar');
  const mainLayout = document.getElementById('mainLayout');
  if (toggleBtn && mainLayout) {
    toggleBtn.onclick = () => {
      mainLayout.classList.toggle('sidebar-collapsed');
    };
  }

  // Keepalive ping
  setInterval(() => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: 'ping' }));
    }
  }, 30000);
});
