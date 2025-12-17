/**
 * Architect's Hand Bridge - Electron Main Process
 * Handles window management, IPC, and bridge coordination
 * v3.2 - Added persistent config and encrypted password storage
 */

const { app, BrowserWindow, ipcMain, shell, Notification, safeStorage } = require('electron');
const path = require('path');
const { createClient } = require('@supabase/supabase-js');
const fs = require('fs');

// Bridge module
const bridge = require('./bridge/index');

// Global references
let mainWindow = null;
let supabase = null;
let config = {};

// Config file path
const CONFIG_PATH = path.join(app.getPath('userData'), 'config.json');

/**
 * Load configuration from file
 */
function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const data = fs.readFileSync(CONFIG_PATH, 'utf8');
      config = JSON.parse(data);
      console.log('Config loaded from:', CONFIG_PATH);
      
      // Decrypt password if present
      if (config.encryptedPassword && safeStorage.isEncryptionAvailable()) {
        try {
          const decrypted = safeStorage.decryptString(Buffer.from(config.encryptedPassword, 'base64'));
          config.password = decrypted;
        } catch (e) {
          console.log('Could not decrypt password:', e.message);
          config.password = '';
        }
      }
    }
  } catch (e) {
    console.error('Error loading config:', e.message);
  }
  return config;
}

/**
 * Save configuration to file
 */
function saveConfig(newConfig) {
  try {
    // Merge with existing config
    config = { ...config, ...newConfig };
    
    // Create a copy for saving (without plain password)
    const configToSave = { ...config };
    
    // Encrypt password before saving
    if (newConfig.password && safeStorage.isEncryptionAvailable()) {
      const encrypted = safeStorage.encryptString(newConfig.password);
      configToSave.encryptedPassword = encrypted.toString('base64');
    }
    
    // Don't save plain password to file
    delete configToSave.password;
    
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(configToSave, null, 2));
    console.log('Config saved to:', CONFIG_PATH);
  } catch (e) {
    console.error('Error saving config:', e.message);
  }
}

/**
 * Initialize Supabase client
 */
function initSupabase() {
  if (config.supabaseUrl && config.supabaseAnonKey) {
    supabase = createClient(config.supabaseUrl, config.supabaseAnonKey);
    console.log('Supabase client initialized');
    return true;
  }
  return false;
}

/**
 * Create the main window
 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 700,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    icon: path.join(__dirname, '../assets/icon.png'),
    title: 'Architect\'s Hand Bridge',
    show: false
  });

  // Load the HTML file
  mainWindow.loadFile(path.join(__dirname, 'renderer/index.html'));

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    
    // Open DevTools in dev mode
    if (process.argv.includes('--dev')) {
      mainWindow.webContents.openDevTools();
    }
  });

  // Handle window close
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Handle external links
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

/**
 * Setup IPC handlers
 */
function setupIPC() {
  // Get config (returns all saved settings including decrypted password)
  ipcMain.handle('get-config', () => {
    return {
      // Supabase settings
      supabaseUrl: config.supabaseUrl || '',
      supabaseAnonKey: config.supabaseAnonKey || '',
      
      // OpenAGI settings
      openAgiApiKey: config.openAgiApiKey || '',
      
      // User credentials
      email: config.email || '',
      password: config.password || '',
      
      // Remember me flag
      rememberMe: config.rememberMe !== false, // Default true
      
      // Auto-start bridge
      autoStartBridge: config.autoStartBridge || false,
      
      // Last successful login
      lastLogin: config.lastLogin || null
    };
  });

  // Save config (saves all settings)
  ipcMain.handle('save-config', async (event, newConfig) => {
    saveConfig(newConfig);
    
    // Reinitialize Supabase if credentials changed
    if (newConfig.supabaseUrl || newConfig.supabaseAnonKey) {
      initSupabase();
    }
    
    return { success: true };
  });

  // Save credentials only
  ipcMain.handle('save-credentials', async (event, { email, password, rememberMe }) => {
    if (rememberMe) {
      saveConfig({ email, password, rememberMe });
    } else {
      // Clear saved credentials
      saveConfig({ email: '', password: '', rememberMe: false });
    }
    return { success: true };
  });

  // Clear saved credentials
  ipcMain.handle('clear-credentials', async () => {
    saveConfig({ email: '', password: '', encryptedPassword: '' });
    return { success: true };
  });

  // Login
  ipcMain.handle('login', async (event, { email, password, rememberMe = true }) => {
    if (!supabase) {
      if (!initSupabase()) {
        return { success: false, error: 'Supabase not configured. Please check Settings.' };
      }
    }

    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password
      });

      if (error) {
        return { success: false, error: error.message };
      }

      // Save credentials if rememberMe is checked
      if (rememberMe) {
        saveConfig({ 
          email, 
          password, 
          rememberMe: true,
          lastLogin: new Date().toISOString()
        });
      }

      return { success: true, user: data.user };
    } catch (e) {
      return { success: false, error: e.message };
    }
  });

  // Auto-login (try to login with saved credentials)
  ipcMain.handle('auto-login', async () => {
    if (!config.email || !config.password) {
      return { success: false, error: 'No saved credentials' };
    }

    if (!supabase) {
      if (!initSupabase()) {
        return { success: false, error: 'Supabase not configured' };
      }
    }

    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email: config.email,
        password: config.password
      });

      if (error) {
        return { success: false, error: error.message };
      }

      // Update last login
      saveConfig({ lastLogin: new Date().toISOString() });

      return { success: true, user: data.user };
    } catch (e) {
      return { success: false, error: e.message };
    }
  });

  // Logout
  ipcMain.handle('logout', async () => {
    if (supabase) {
      await supabase.auth.signOut();
    }
    return { success: true };
  });

  // Get current user
  ipcMain.handle('get-user', async () => {
    if (!supabase) return { user: null };
    
    try {
      const { data: { user } } = await supabase.auth.getUser();
      return { user };
    } catch (e) {
      return { user: null };
    }
  });

  // Check if config is complete
  ipcMain.handle('is-configured', () => {
    return {
      supabase: !!(config.supabaseUrl && config.supabaseAnonKey),
      openAgi: !!config.openAgiApiKey,
      credentials: !!(config.email && config.password),
      complete: !!(config.supabaseUrl && config.supabaseAnonKey && config.openAgiApiKey)
    };
  });

  // Start bridge
  ipcMain.handle('start-bridge', async () => {
    if (!supabase) {
      if (!initSupabase()) {
        return { success: false, error: 'Supabase not configured' };
      }
    }

    try {
      // Set up bridge callbacks
      bridge.setCallbacks({
        sendLog: (level, message) => {
          if (mainWindow) {
            mainWindow.webContents.send('bridge-log', { level, message });
          }
        },
        sendStatus: (status) => {
          if (mainWindow) {
            mainWindow.webContents.send('bridge-status', status);
          }
        },
        sendTaskUpdate: (task) => {
          if (mainWindow) {
            mainWindow.webContents.send('task-update', task);
          }
        },
        sendStepUpdate: (step) => {
          if (mainWindow) {
            mainWindow.webContents.send('step-update', step);
          }
        },
        // Window control for Lux execution
        minimizeWindow: () => {
          if (mainWindow && !mainWindow.isMinimized()) {
            mainWindow.minimize();
            console.log('[Main] Window minimized for Lux execution');
          }
        },
        restoreWindow: () => {
          if (mainWindow && mainWindow.isMinimized()) {
            mainWindow.restore();
            console.log('[Main] Window restored after Lux execution');
          }
        }
      });

      // Start the bridge
      await bridge.start(config, supabase);
      
      return { success: true };
    } catch (e) {
      return { success: false, error: e.message };
    }
  });

  // Stop bridge
  ipcMain.handle('stop-bridge', async () => {
    try {
      await bridge.stop();
      return { success: true };
    } catch (e) {
      return { success: false, error: e.message };
    }
  });

  // Pause bridge
  ipcMain.handle('pause-bridge', async () => {
    bridge.pause();
    return { success: true };
  });

  // Resume bridge
  ipcMain.handle('resume-bridge', async () => {
    bridge.resume();
    return { success: true };
  });

  // Get bridge state
  ipcMain.handle('get-bridge-state', () => {
    return bridge.getState();
  });

  // Cancel task
  ipcMain.handle('cancel-task', async (event, taskId) => {
    try {
      await bridge.cancelTask(taskId);
      return { success: true };
    } catch (e) {
      return { success: false, error: e.message };
    }
  });

  // Retry step
  ipcMain.handle('retry-step', async (event, stepId) => {
    try {
      const result = await bridge.retryStep(stepId);
      return { success: true, data: result };
    } catch (e) {
      return { success: false, error: e.message };
    }
  });

  // Show notification
  ipcMain.handle('show-notification', async (event, { title, body }) => {
    if (Notification.isSupported()) {
      new Notification({ title, body }).show();
    }
    return { success: true };
  });

  // Open external URL
  ipcMain.handle('open-external', async (event, url) => {
    await shell.openExternal(url);
    return { success: true };
  });
  
  // Manual window minimize
  ipcMain.handle('minimize-window', async () => {
    if (mainWindow && !mainWindow.isMinimized()) {
      mainWindow.minimize();
      return { success: true };
    }
    return { success: false, error: 'Window already minimized or not available' };
  });
  
  // Manual window restore
  ipcMain.handle('restore-window', async () => {
    if (mainWindow && mainWindow.isMinimized()) {
      mainWindow.restore();
      return { success: true };
    }
    return { success: false, error: 'Window not minimized or not available' };
  });

  // Get app version
  ipcMain.handle('get-app-version', () => {
    return app.getVersion();
  });

  // Get config path (for debugging)
  ipcMain.handle('get-config-path', () => {
    return CONFIG_PATH;
  });
}

/**
 * App ready handler
 */
app.whenReady().then(() => {
  loadConfig();
  initSupabase();
  createWindow();
  setupIPC();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

/**
 * App window-all-closed handler
 */
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

/**
 * App before-quit handler
 */
app.on('before-quit', async () => {
  // Stop bridge before quitting
  try {
    await bridge.stop();
  } catch (e) {
    console.error('Error stopping bridge:', e.message);
  }
});
