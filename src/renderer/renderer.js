// DOM Elements
const elements = {
  // Status
  statusIndicator: document.getElementById('status-indicator'),
  statusDot: document.querySelector('.status-dot'),
  statusText: document.querySelector('.status-text'),
  
  // Control buttons
  btnStart: document.getElementById('btn-start'),
  btnPause: document.getElementById('btn-pause'),
  btnStop: document.getElementById('btn-stop'),
  
  // Info
  connectionInfo: document.getElementById('connection-info'),
  currentTaskContent: document.getElementById('current-task-content'),
  currentStepContent: document.getElementById('current-step-content'),
  stepProgress: document.getElementById('step-progress'),
  progressFill: document.getElementById('progress-fill'),
  progressText: document.getElementById('progress-text'),
  screenshotContainer: document.getElementById('screenshot-container'),
  
  // Log
  logContainer: document.getElementById('log-container'),
  btnClearLog: document.getElementById('btn-clear-log'),
  
  // Tasks
  taskList: document.getElementById('task-list'),
  
  // Settings
  settingsForm: document.getElementById('settings-form'),
  supabaseUrl: document.getElementById('supabase-url'),
  supabaseKey: document.getElementById('supabase-key'),
  taskSecret: document.getElementById('task-secret'),
  openagiKey: document.getElementById('openagi-key'),
  outputFolder: document.getElementById('output-folder'),
  btnSelectOutput: document.getElementById('btn-select-output'),
  saveStatus: document.getElementById('save-status'),
  
  // Tabs
  navTabs: document.querySelectorAll('.nav-tab'),
  tabContents: document.querySelectorAll('.tab-content')
};

// State
let state = {
  connected: false,
  running: false,
  paused: false,
  currentTask: null,
  currentStep: null,
  tasks: []
};

// Initialize
async function init() {
  // Load config
  const config = await window.electronAPI.getConfig();
  if (config) {
    elements.supabaseUrl.value = config.supabaseUrl || '';
    elements.supabaseKey.value = config.supabaseAnonKey || '';
    elements.taskSecret.value = config.taskSecret || '';
    elements.openagiKey.value = config.openAgiApiKey || '';
    elements.outputFolder.value = config.outputFolder || '';
    
    updateConnectionInfo(config);
  }
  
  // Setup event listeners
  setupEventListeners();
  
  // Setup IPC listeners
  setupIPCListeners();
  
  addLog('info', 'App initialized. Configure your settings and click Start.');
}

// Update connection info display
function updateConnectionInfo(config) {
  const hasSupabase = config.supabaseUrl && config.supabaseAnonKey;
  const hasTaskSecret = config.taskSecret;
  const hasOpenAgi = config.openAgiApiKey;
  
  let html = '<ul style="list-style: none; padding: 0; margin: 0;">';
  html += `<li>${hasSupabase ? '✅' : '❌'} Supabase configured</li>`;
  html += `<li>${hasTaskSecret ? '✅' : '⚠️'} Task Secret ${hasTaskSecret ? 'configured' : '(optional until task assigned)'}</li>`;
  html += `<li>${hasOpenAgi ? '✅' : '❌'} OpenAGI (Lux) configured</li>`;
  html += '</ul>';
  
  if (hasSupabase && hasOpenAgi) {
    html += '<p style="margin-top: 0.5rem; color: #22c55e;">Ready to start!</p>';
  }
  
  elements.connectionInfo.innerHTML = html;
}

// Setup event listeners
function setupEventListeners() {
  // Tab navigation
  elements.navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const tabId = tab.dataset.tab;
      switchTab(tabId);
    });
  });
  
  // Control buttons
  elements.btnStart.addEventListener('click', startBridge);
  elements.btnPause.addEventListener('click', togglePause);
  elements.btnStop.addEventListener('click', stopBridge);
  
  // Clear log
  elements.btnClearLog.addEventListener('click', clearLog);
  
  // Settings form
  elements.settingsForm.addEventListener('submit', saveSettings);
  
  // Folder selection
  elements.btnSelectOutput.addEventListener('click', async () => {
    const folder = await window.electronAPI.selectFolder({ title: 'Select Output Folder' });
    if (folder) {
      elements.outputFolder.value = folder;
    }
  });
}

// Setup IPC listeners
function setupIPCListeners() {
  window.electronAPI.onLog((data) => {
    addLog(data.level, data.message);
  });
  
  window.electronAPI.onStatusChange((data) => {
    updateStatus(data.status);
  });
  
  window.electronAPI.onTaskUpdate((data) => {
    updateCurrentTask(data);
  });
  
  window.electronAPI.onStepUpdate((data) => {
    updateCurrentStep(data);
  });
  
  window.electronAPI.onScreenshot((data) => {
    updateScreenshot(data.url);
  });
}

// Switch tab
function switchTab(tabId) {
  elements.navTabs.forEach(t => t.classList.remove('active'));
  elements.tabContents.forEach(c => c.classList.remove('active'));
  
  document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');
  document.getElementById(`tab-${tabId}`).classList.add('active');
}

// Start bridge
async function startBridge() {
  addLog('info', 'Starting bridge...');
  
  try {
    await window.electronAPI.startBridge();
    state.running = true;
    updateControlButtons();
    updateStatus('connecting');
  } catch (error) {
    addLog('error', `Failed to start: ${error.message}`);
  }
}

// Toggle pause
async function togglePause() {
  if (state.paused) {
    await window.electronAPI.resumeBridge();
    state.paused = false;
    elements.btnPause.textContent = '⏸️ Pause';
    addLog('info', 'Bridge resumed');
  } else {
    await window.electronAPI.pauseBridge();
    state.paused = true;
    elements.btnPause.textContent = '▶️ Resume';
    addLog('info', 'Bridge paused');
  }
}

// Stop bridge
async function stopBridge() {
  addLog('info', 'Stopping bridge...');
  
  try {
    await window.electronAPI.stopBridge();
    state.running = false;
    state.paused = false;
    updateControlButtons();
    updateStatus('disconnected');
  } catch (error) {
    addLog('error', `Failed to stop: ${error.message}`);
  }
}

// Update control buttons
function updateControlButtons() {
  elements.btnStart.disabled = state.running;
  elements.btnPause.disabled = !state.running;
  elements.btnStop.disabled = !state.running;
}

// Update status
function updateStatus(status) {
  elements.statusDot.classList.remove('connected', 'connecting');
  
  switch (status) {
    case 'connected':
      elements.statusDot.classList.add('connected');
      elements.statusText.textContent = 'Connected';
      state.connected = true;
      addLog('success', 'Connected to Supabase');
      break;
    case 'connecting':
      elements.statusDot.classList.add('connecting');
      elements.statusText.textContent = 'Connecting...';
      break;
    case 'disconnected':
    default:
      elements.statusText.textContent = 'Disconnected';
      state.connected = false;
      break;
  }
}

// Update current task
function updateCurrentTask(task) {
  state.currentTask = task;
  
  if (!task) {
    elements.currentTaskContent.innerHTML = '<p class="empty-state">No active task</p>';
    return;
  }
  
  elements.currentTaskContent.innerHTML = `
    <div class="task-info">
      <h3>${task.task_description || 'Unnamed Task'}</h3>
      <p><strong>Platform:</strong> ${task.platform || 'N/A'}</p>
      <p><strong>Type:</strong> ${task.task_type || 'N/A'}</p>
      <p><strong>Status:</strong> <span class="task-status ${task.status}">${task.status}</span></p>
    </div>
  `;
  
  // Update progress
  if (task.total_steps > 0) {
    elements.stepProgress.style.display = 'block';
    elements.progressFill.style.width = `${task.progress}%`;
    elements.progressText.textContent = `${task.completed_steps}/${task.total_steps} steps (${task.progress}%)`;
  }
}

// Update current step
function updateCurrentStep(step) {
  state.currentStep = step;
  
  if (!step) {
    elements.currentStepContent.innerHTML = '<p class="empty-state">Waiting for task...</p>';
    return;
  }
  
  elements.currentStepContent.innerHTML = `
    <div class="step-info">
      <p><strong>Step ${step.step_number}:</strong> ${step.instruction}</p>
      <p><strong>Status:</strong> <span class="task-status ${step.status}">${step.status}</span></p>
      ${step.expected_outcome ? `<p><strong>Expected:</strong> ${step.expected_outcome}</p>` : ''}
      ${step.retry_count > 0 ? `<p><strong>Retries:</strong> ${step.retry_count}/${step.max_retries}</p>` : ''}
    </div>
  `;
}

// Update screenshot
function updateScreenshot(url) {
  if (!url) {
    elements.screenshotContainer.innerHTML = '<p class="empty-state">No screenshot available</p>';
    return;
  }
  
  elements.screenshotContainer.innerHTML = `<img src="${url}" alt="Browser screenshot" />`;
}

// Add log entry
function addLog(level, message) {
  const timestamp = new Date().toLocaleTimeString();
  const entry = document.createElement('p');
  entry.className = `log-entry log-${level}`;
  entry.innerHTML = `<span class="log-timestamp">[${timestamp}]</span> ${message}`;
  
  elements.logContainer.appendChild(entry);
  elements.logContainer.scrollTop = elements.logContainer.scrollHeight;
}

// Clear log
function clearLog() {
  elements.logContainer.innerHTML = '';
  addLog('info', 'Log cleared');
}

// Save settings
async function saveSettings(e) {
  e.preventDefault();
  
  const config = {
    supabaseUrl: elements.supabaseUrl.value.trim(),
    supabaseAnonKey: elements.supabaseKey.value.trim(),
    taskSecret: elements.taskSecret.value.trim(),
    openAgiApiKey: elements.openagiKey.value.trim(),
    outputFolder: elements.outputFolder.value.trim()
  };
  
  const success = await window.electronAPI.saveConfig(config);
  
  if (success) {
    elements.saveStatus.textContent = '✓ Saved!';
    updateConnectionInfo(config);
    addLog('success', 'Settings saved');
    
    setTimeout(() => {
      elements.saveStatus.textContent = '';
    }, 3000);
  } else {
    elements.saveStatus.textContent = '✗ Error saving';
    elements.saveStatus.style.color = '#ef4444';
    addLog('error', 'Failed to save settings');
  }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', init);
