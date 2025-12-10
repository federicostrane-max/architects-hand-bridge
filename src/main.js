const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { createClient } = require('@supabase/supabase-js');

// Store windows
let mainWindow = null;
let browserWindow = null;

// Supabase client
let supabase = null;

// Store config
let config = {
  supabaseUrl: '',
  supabaseAnonKey: '',
  taskSecret: '',
  openAgiApiKey: '',
  inputFolders: [],
  outputFolder: ''
};

// Config file path
const configPath = path.join(app.getPath('userData'), 'config.json');

// Load config from file
function loadConfig() {
  try {
    if (fs.existsSync(configPath)) {
      const data = fs.readFileSync(configPath, 'utf8');
      config = { ...config, ...JSON.parse(data) };
      console.log('Config loaded from:', configPath);
    }
  } catch (error) {
    console.error('Error loading config:', error);
  }
  return config;
}

// Save config to file
function saveConfig(newConfig) {
  try {
    config = { ...config, ...newConfig };
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
    console.log('Config saved to:', configPath);
    
    // Reinitialize Supabase if URL/key changed
    if (newConfig.supabaseUrl && newConfig.supabaseAnonKey) {
      initSupabase();
    }
    
    return true;
  } catch (error) {
    console.error('Error saving config:', error);
    return false;
  }
}

// Initialize Supabase client
function initSupabase() {
  if (config.supabaseUrl && config.supabaseAnonKey) {
    supabase = createClient(config.supabaseUrl, config.supabaseAnonKey);
    console.log('Supabase client initialized');
    return true;
  }
  return false;
}

// Create main window
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    icon: path.join(__dirname, '../assets/icon.ico'),
    title: "Architect's Hand - Local Bridge"
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer/index.html'));

  // Open DevTools in development
  if (process.argv.includes('--dev')) {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
    // Close browser window if main window is closed
    if (browserWindow && !browserWindow.isDestroyed()) {
      browserWindow.close();
    }
  });
}

// App ready
app.whenReady().then(() => {
  loadConfig();
  initSupabase();
  createMainWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

// Quit when all windows are closed
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Bridge module
const bridge = require('./bridge');

// Setup bridge callbacks
function setupBridgeCallbacks() {
  bridge.setCallbacks({
    sendLog: (level, message) => {
      sendLog(level, message);
    },
    sendStatus: (status) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('status:changed', { status });
      }
    },
    sendTaskUpdate: (task) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('task:updated', task);
      }
    },
    sendStepUpdate: (step) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('step:updated', step);
      }
    },
    sendScreenshot: (url) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('screenshot', { url });
      }
    }
  });
}

// IPC Handlers

// Config handlers
ipcMain.handle('config:get', () => {
  return loadConfig();
});

ipcMain.handle('config:save', (event, newConfig) => {
  return saveConfig(newConfig);
});

// Auth handlers
ipcMain.handle('auth:login', async (event, email, password) => {
  try {
    if (!supabase) {
      // Try to initialize
      if (!initSupabase()) {
        return { success: false, error: 'Supabase not configured. Please add Supabase URL and Key in Settings.' };
      }
    }
    
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password
    });
    
    if (error) {
      return { success: false, error: error.message };
    }
    
    // Notify renderer of auth change
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('auth:changed', { event: 'SIGNED_IN', session: data.session });
    }
    
    return { success: true, user: data.user, session: data.session };
  } catch (error) {
    console.error('Login error:', error);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('auth:logout', async () => {
  try {
    if (!supabase) {
      return { success: true };
    }
    
    const { error } = await supabase.auth.signOut();
    
    if (error) {
      return { success: false, error: error.message };
    }
    
    // Notify renderer of auth change
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('auth:changed', { event: 'SIGNED_OUT', session: null });
    }
    
    return { success: true };
  } catch (error) {
    console.error('Logout error:', error);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('auth:getSession', async () => {
  try {
    if (!supabase) {
      return null;
    }
    const { data: { session } } = await supabase.auth.getSession();
    return session;
  } catch (error) {
    console.error('Get session error:', error);
    return null;
  }
});

// Dialog handlers
ipcMain.handle('dialog:selectFolder', async (event, options) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: options?.title || 'Select Folder'
  });
  
  if (result.canceled) {
    return null;
  }
  return result.filePaths[0];
});

ipcMain.handle('dialog:selectFiles', async (event, options) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    title: options?.title || 'Select Files',
    filters: options?.filters || [{ name: 'All Files', extensions: ['*'] }]
  });
  
  if (result.canceled) {
    return null;
  }
  return result.filePaths;
});

// Send log to renderer
function sendLog(level, message, data = null) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('log', { level, message, data, timestamp: new Date().toISOString() });
  }
}

// Bridge IPC Handlers
ipcMain.handle('bridge:start', async () => {
  try {
    setupBridgeCallbacks();
    await bridge.start(config, supabase);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('bridge:stop', async () => {
  try {
    await bridge.stop();
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('bridge:pause', async () => {
  bridge.pause();
  return { success: true };
});

ipcMain.handle('bridge:resume', async () => {
  bridge.resume();
  return { success: true };
});

// Cancel task
ipcMain.handle('task:cancel', async (event, taskId) => {
  try {
    await bridge.cancelTask(taskId);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Retry step
ipcMain.handle('step:retry', async (event, stepId) => {
  try {
    const step = await bridge.retryStep(stepId);
    return { success: true, step };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Get bridge state
ipcMain.handle('bridge:getState', () => {
  return bridge.getState();
});

// Export for use in other modules
module.exports = {
  getMainWindow: () => mainWindow,
  getBrowserWindow: () => browserWindow,
  setBrowserWindow: (win) => { browserWindow = win; },
  getConfig: () => config,
  getSupabase: () => supabase,
  sendLog
};
