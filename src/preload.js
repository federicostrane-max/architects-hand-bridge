const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods to renderer
contextBridge.exposeInMainWorld('electronAPI', {
  // Config
  getConfig: () => ipcRenderer.invoke('get-config'),
  saveConfig: (config) => ipcRenderer.invoke('save-config', config),
  
  // Dialogs
  selectFolder: (options) => ipcRenderer.invoke('select-folder', options),
  selectFiles: (options) => ipcRenderer.invoke('select-files', options),
  
  // Bridge control
  startBridge: () => ipcRenderer.invoke('start-bridge'),
  stopBridge: () => ipcRenderer.invoke('stop-bridge'),
  pauseBridge: () => ipcRenderer.invoke('pause-bridge'),
  resumeBridge: () => ipcRenderer.invoke('resume-bridge'),
  
  // Task control
  cancelTask: (taskId) => ipcRenderer.invoke('cancel-task', taskId),
  retryStep: (stepId) => ipcRenderer.invoke('retry-step', stepId),
  
  // Event listeners
  onLog: (callback) => {
    ipcRenderer.on('log', (event, data) => callback(data));
  },
  onStatusChange: (callback) => {
    ipcRenderer.on('status-change', (event, data) => callback(data));
  },
  onTaskUpdate: (callback) => {
    ipcRenderer.on('task-update', (event, data) => callback(data));
  },
  onStepUpdate: (callback) => {
    ipcRenderer.on('step-update', (event, data) => callback(data));
  },
  onScreenshot: (callback) => {
    ipcRenderer.on('screenshot', (event, data) => callback(data));
  },
  
  // Remove listeners
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  }
});
