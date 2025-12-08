const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { createClient } = require('@supabase/supabase-js');

// Store windows
let mainWindow = null;
let browserWindow = null;

// Store config
let config = {
  supabaseUrl: '',
  supabaseServiceKey: '',
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
    return true;
  } catch (error) {
    console.error('Error saving config:', error);
    return false;
  }
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
        mainWindow.webContents.send('status-change', { status });
      }
    },
    sendTaskUpdate: (task) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('task-update', task);
      }
    },
    sendStepUpdate: (step) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('step-update', step);
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

// Get config
ipcMain.handle('get-config', () => {
  return loadConfig();
});

// Save config
ipcMain.handle('save-config', (event, newConfig) => {
  return saveConfig(newConfig);
});

// Select folder dialog
ipcMain.handle('select-folder', async (event, options) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: options?.title || 'Select Folder'
  });
  
  if (result.canceled) {
    return null;
  }
  return result.filePaths[0];
});

// Select files dialog
ipcMain.handle('select-files', async (event, options) => {
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

// Start bridge
ipcMain.handle('start-bridge', async () => {
  try {
    setupBridgeCallbacks();
    await bridge.start(config);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Stop bridge
ipcMain.handle('stop-bridge', async () => {
  try {
    await bridge.stop();
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
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

// Cancel task
ipcMain.handle('cancel-task', async (event, taskId) => {
  try {
    await bridge.cancelTask(taskId);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Retry step
ipcMain.handle('retry-step', async (event, stepId) => {
  try {
    const step = await bridge.retryStep(stepId);
    return { success: true, step };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Get bridge state
ipcMain.handle('get-bridge-state', () => {
  return bridge.getState();
});

// Export for use in other modules
module.exports = {
  getMainWindow: () => mainWindow,
  getBrowserWindow: () => browserWindow,
  setBrowserWindow: (win) => { browserWindow = win; },
  getConfig: () => config,
  sendLog
};
