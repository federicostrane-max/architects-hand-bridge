const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Config
  getConfig: () => ipcRenderer.invoke('config:get'),
  saveConfig: (config) => ipcRenderer.invoke('config:save', config),
  
  // Auth
  login: (email, password) => ipcRenderer.invoke('auth:login', email, password),
  logout: () => ipcRenderer.invoke('auth:logout'),
  getSession: () => ipcRenderer.invoke('auth:getSession'),
  onAuthChange: (callback) => ipcRenderer.on('auth:changed', (event, data) => callback(data)),
  
  // Bridge control
  startBridge: () => ipcRenderer.invoke('bridge:start'),
  stopBridge: () => ipcRenderer.invoke('bridge:stop'),
  pauseBridge: () => ipcRenderer.invoke('bridge:pause'),
  resumeBridge: () => ipcRenderer.invoke('bridge:resume'),
  getBridgeState: () => ipcRenderer.invoke('bridge:getState'),
  
  // Folder selection
  selectFolder: (options) => ipcRenderer.invoke('dialog:selectFolder', options),
  
  // Event listeners
  onLog: (callback) => ipcRenderer.on('log', (event, data) => callback(data)),
  onStatusChange: (callback) => ipcRenderer.on('status:changed', (event, data) => callback(data)),
  onTaskUpdate: (callback) => ipcRenderer.on('task:updated', (event, data) => callback(data)),
  onStepUpdate: (callback) => ipcRenderer.on('step:updated', (event, data) => callback(data)),
  onScreenshot: (callback) => ipcRenderer.on('screenshot', (event, data) => callback(data))
});
