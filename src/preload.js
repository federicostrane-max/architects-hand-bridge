/**
 * Preload script for Architect's Hand Bridge
 * Exposes IPC APIs to renderer process securely
 * v3.2 - Added credential management APIs
 */

const { contextBridge, ipcRenderer } = require('electron');

// Expose APIs to renderer
contextBridge.exposeInMainWorld('api', {
  // ==========================================
  // CONFIG & SETTINGS
  // ==========================================
  
  /**
   * Get all saved configuration
   * Returns: { supabaseUrl, supabaseAnonKey, openAgiApiKey, email, password, rememberMe, autoStartBridge }
   */
  getConfig: () => ipcRenderer.invoke('get-config'),
  
  /**
   * Save configuration
   * @param {Object} config - Configuration object to save
   */
  saveConfig: (config) => ipcRenderer.invoke('save-config', config),
  
  /**
   * Check if app is fully configured
   * Returns: { supabase: bool, openAgi: bool, credentials: bool, complete: bool }
   */
  isConfigured: () => ipcRenderer.invoke('is-configured'),
  
  /**
   * Get config file path (for debugging)
   */
  getConfigPath: () => ipcRenderer.invoke('get-config-path'),
  
  // ==========================================
  // AUTHENTICATION
  // ==========================================
  
  /**
   * Login with email and password
   * @param {string} email 
   * @param {string} password 
   * @param {boolean} rememberMe - If true, credentials are saved encrypted
   */
  login: (email, password, rememberMe = true) => 
    ipcRenderer.invoke('login', { email, password, rememberMe }),
  
  /**
   * Auto-login with saved credentials
   * Returns: { success: bool, user?: object, error?: string }
   */
  autoLogin: () => ipcRenderer.invoke('auto-login'),
  
  /**
   * Logout current user
   */
  logout: () => ipcRenderer.invoke('logout'),
  
  /**
   * Get current user
   */
  getUser: () => ipcRenderer.invoke('get-user'),
  
  /**
   * Save credentials only
   */
  saveCredentials: (email, password, rememberMe) => 
    ipcRenderer.invoke('save-credentials', { email, password, rememberMe }),
  
  /**
   * Clear saved credentials
   */
  clearCredentials: () => ipcRenderer.invoke('clear-credentials'),
  
  // ==========================================
  // BRIDGE CONTROL
  // ==========================================
  
  /**
   * Start the bridge
   */
  startBridge: () => ipcRenderer.invoke('start-bridge'),
  
  /**
   * Stop the bridge
   */
  stopBridge: () => ipcRenderer.invoke('stop-bridge'),
  
  /**
   * Pause the bridge
   */
  pauseBridge: () => ipcRenderer.invoke('pause-bridge'),
  
  /**
   * Resume the bridge
   */
  resumeBridge: () => ipcRenderer.invoke('resume-bridge'),
  
  /**
   * Get bridge state
   */
  getBridgeState: () => ipcRenderer.invoke('get-bridge-state'),
  
  // ==========================================
  // TASK CONTROL
  // ==========================================
  
  /**
   * Cancel a running task
   */
  cancelTask: (taskId) => ipcRenderer.invoke('cancel-task', taskId),
  
  /**
   * Retry a failed step
   */
  retryStep: (stepId) => ipcRenderer.invoke('retry-step', stepId),
  
  // ==========================================
  // WINDOW CONTROL
  // ==========================================
  
  /**
   * Minimize window
   */
  minimizeWindow: () => ipcRenderer.invoke('minimize-window'),
  
  /**
   * Restore window
   */
  restoreWindow: () => ipcRenderer.invoke('restore-window'),
  
  // ==========================================
  // UTILITIES
  // ==========================================
  
  /**
   * Show system notification
   */
  showNotification: (title, body) => 
    ipcRenderer.invoke('show-notification', { title, body }),
  
  /**
   * Open external URL in default browser
   */
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  
  /**
   * Get app version
   */
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  
  // ==========================================
  // EVENT LISTENERS
  // ==========================================
  
  /**
   * Listen for bridge log messages
   */
  onBridgeLog: (callback) => {
    ipcRenderer.on('bridge-log', (event, data) => callback(data));
  },
  
  /**
   * Listen for bridge status changes
   */
  onBridgeStatus: (callback) => {
    ipcRenderer.on('bridge-status', (event, status) => callback(status));
  },
  
  /**
   * Listen for task updates
   */
  onTaskUpdate: (callback) => {
    ipcRenderer.on('task-update', (event, task) => callback(task));
  },
  
  /**
   * Listen for step updates
   */
  onStepUpdate: (callback) => {
    ipcRenderer.on('step-update', (event, step) => callback(step));
  },
  
  /**
   * Remove all listeners for a channel
   */
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  }
});

console.log('Preload script loaded - API exposed to renderer');
