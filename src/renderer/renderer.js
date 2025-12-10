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
  openagiKey: document.getElementById('openagi-key'),
  outputFolder: document.getElementById('output-folder'),
  btnSelectOutput: document.getElementById('btn-select-output'),
  saveStatus: document.getElementById('save-status'),
  
  // Auth elements
  loginForm: document.getElementById('login-form'),
  loginEmail: document.getElementById('login-email'),
  loginPassword: document.getElementById('login-password'),
  loginError: document.getElementById('login-error'),
  loginSection: document.getElementById('login-section'),
  userSection: document.getElementById('user-section'),
  userEmail: document.getElementById('user-email'),
  btnLogout: document.getElementById('btn-logout'),
  
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
  tasks: [],
  isLoggedIn: false,
  user: null
};

// Initialize
async function init() {
  // Load config
  const config = await window.electronAPI.getConfig();
  if (config) {
    if (elements.supabaseUrl) elements.supabaseUrl.value = config.supabaseUrl || '';
    if (elements.supabaseKey) elements.supabaseKey.value = config.supabaseAnonKey || '';
    if (elements.openagiKey) elements.openagiKey.value = config.openAgiApiKey || '';
    if (elements.outputFolder) elements.outputFolder.value = config.outputFolder || '';
  }
  
  // Check current session
  const session = await window.electronAPI.getSession();
  if (session) {
    updateAuthUI(true, session.user);
  }
  
  // Update connection info
  updateConnectionInfo(config || {});
  
  // Setup event listeners
  setupEventListeners();
  
  // Setup IPC listeners
  setupIPCListeners();
  
  addLog('info', 'App initialized. Login and configure settings to start.');
}

// Update connection info display
function updateConnectionInfo(config) {
  const hasSupabase = config.supabaseUrl && config.supabaseAnonKey;
  const hasOpenAgi = config.openAgiApiKey;
  
  let html = '<ul style="list-style: none; padding: 0; margin: 0;">';
  html += `<li>${hasSupabase ? '✅' : '❌'} Supabase configured</li>`;
  html += `<li>${state.isLoggedIn ? '✅' : '❌'} User logged in</li>`;
  html += `<li>${hasOpenAgi ? '✅' : '❌'} OpenAGI (Lux) configured</li>`;
  html += '</ul>';
  
  if (hasSupabase && hasOpenAgi && state.isLoggedIn) {
    html += '<p style="margin-top: 0.5rem; color: #22c55e;">Ready to start!</p>';
  } else if (!state.isLoggedIn) {
    html += '<p style="margin-top: 0.5rem; color: #f59e0b;">Login required to start</p>';
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
  
  // Auth
  elements.loginForm.addEventListener('submit', handleLogin);
  elements.btnLogout.addEventListener('click', handleLogout);
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
  
  window.electronAPI.onAuthChange((data) => {
    if (data.event === 'SIGNED_IN') {
      updateAuthUI(true, data.session.user);
    } else if (data.event === 'SIGNED_OUT') {
      updateAuthUI(false, null);
    }
  });
}

// Handle login
async function handleLogin(e) {
  e.preventDefault();
  
  const email = elements.loginEmail.value.trim();
  const password = elements.loginPassword.value;
  
  elements.loginError.textContent = '';
  elements.loginForm.querySelector('button[type="submit"]').disabled = true;
  elements.loginForm.querySelector('button[type="submit"]').textContent = '🔄 Logging in...';
  
  try {
    const result = await window.electronAPI.login(email, password);
    
    if (result.success) {
      updateAuthUI(true, result.user);
      addLog('success', `Logged in as ${result.user.email}`);
      elements.loginPassword.value = ''; // Clear password
    } else {
      elements.loginError.textContent = result.error;
      addLog('error', `Login failed: ${result.error}`);
    }
  } catch (error) {
    elements.loginError.textContent = error.message;
    addLog('error', `Login error: ${error.message}`);
  } finally {
    elements.loginForm.querySelector('button[type="submit"]').disabled = false;
    elements.loginForm.querySelector('button[type="submit"]').textContent = '🔓 Login';
  }
}

// Handle logout
async function handleLogout() {
  try {
    // Stop bridge if running
    if (state.running) {
      await stopBridge();
    }
    
    const result = await window.electronAPI.logout();
    
    if (result.success) {
      updateAuthUI(false, null);
      addLog('info', 'Logged out');
    } else {
      addLog('error', `Logout failed: ${result.error}`);
    }
  } catch (error) {
    addLog('error', `Logout error: ${error.message}`);
  }
}

// Update auth UI
function updateAuthUI(isLoggedIn, user) {
  state.isLoggedIn = isLoggedIn;
  state.user = user;
  
  if (isLoggedIn && user) {
    elements.loginSection.style.display = 'none';
    elements.userSection.style.display = 'block';
    elements.userEmail.textContent = user.email;
    elements.btnStart.disabled = false;
  } else {
    elements.loginSection.style.display = 'block';
    elements.userSection.style.display = 'none';
    elements.userEmail.textContent = '-';
    elements.btnStart.disabled = true;
  }
  
  // Update connection info
  window.electronAPI.getConfig().then(config => {
    updateConnectionInfo(config || {});
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
  if (!state.isLoggedIn) {
    addLog('error', 'Please login first');
    return;
  }
  
  addLog('info', 'Starting bridge...');
  
  try {
    const result = await window.electronAPI.startBridge();
    if (result.success) {
      state.running = true;
      updateControlButtons();
      updateStatus('connecting');
    } else {
      addLog('error', `Failed to start: ${result.error}`);
    }
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
  elements.btnStart.disabled = state.running || !state.isLoggedIn;
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
      addLog('success', 'Connected to Supabase - listening for tasks');
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
    openAgiApiKey: elements.openagiKey.value.trim(),
    outputFolder: elements.outputFolder.value.trim()
  };
  
  const success = await window.electronAPI.saveConfig(config);
  
  if (success) {
    elements.saveStatus.textContent = '✓ Saved!';
    elements.saveStatus.style.color = '#22c55e';
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
