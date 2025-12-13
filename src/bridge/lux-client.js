/**
 * Lux Client - Delegates to Python Tasker Service
 * The Python service handles TaskerAgent execution with OAGI SDK
 */

const http = require('http');

class LuxClient {
  constructor() {
    this.apiKey = null;
    this.serviceUrl = 'http://127.0.0.1:8765';
    this.serviceAvailable = false;
  }

  setApiKey(key) {
    this.apiKey = key;
    console.log(`[Lux] API key set (starts with: ${key?.substring(0, 8)}...)`);
  }

  /**
   * Check if Python Tasker Service is running
   */
  async checkService() {
    return new Promise((resolve) => {
      const req = http.request(
        `${this.serviceUrl}/status`,
        { method: 'GET', timeout: 2000 },
        (res) => {
          let data = '';
          res.on('data', chunk => data += chunk);
          res.on('end', () => {
            try {
              const status = JSON.parse(data);
              this.serviceAvailable = status.oagi_available;
              console.log(`[Lux] Tasker Service status: ${status.status}, OAGI: ${status.oagi_available}`);
              resolve(this.serviceAvailable);
            } catch (e) {
              resolve(false);
            }
          });
        }
      );
      req.on('error', () => {
        console.log('[Lux] Tasker Service not available');
        this.serviceAvailable = false;
        resolve(false);
      });
      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });
      req.end();
    });
  }

  /**
   * Execute a complete task using Python TaskerAgent
   * This delegates all execution to the Python service
   */
  async executeTaskWithTasker(taskDescription, todos, startUrl = null) {
    if (!this.apiKey) {
      throw new Error('API key not set');
    }

    console.log('[Lux] Delegating task to Python Tasker Service...');
    console.log(`[Lux] Task: ${taskDescription}`);
    console.log(`[Lux] Todos: ${todos.length}`);

    return new Promise((resolve, reject) => {
      const requestBody = JSON.stringify({
        api_key: this.apiKey,
        task_description: taskDescription,
        todos: todos,
        start_url: startUrl,
        max_steps: 60,
        reflection_interval: 20
      });

      const url = new URL(`${this.serviceUrl}/execute`);
      
      const options = {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(requestBody)
        },
        timeout: 600000  // 10 minutes timeout for long tasks
      };

      console.log('[Lux] Sending request to Tasker Service...');

      const req = http.request(options, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          try {
            const response = JSON.parse(data);
            console.log(`[Lux] Tasker Service response:`, response);
            
            resolve({
              success: response.success,
              message: response.message,
              completedTodos: response.completed_todos,
              totalTodos: response.total_todos,
              error: response.error
            });
          } catch (e) {
            reject(new Error(`Failed to parse response: ${e.message}`));
          }
        });
      });

      req.on('error', (e) => {
        console.error('[Lux] Request error:', e.message);
        reject(new Error(`Tasker Service request failed: ${e.message}`));
      });

      req.on('timeout', () => {
        req.destroy();
        reject(new Error('Request timed out'));
      });

      req.write(requestBody);
      req.end();
    });
  }

  /**
   * Stop the currently running task
   */
  async stopTask() {
    return new Promise((resolve) => {
      const req = http.request(
        `${this.serviceUrl}/stop`,
        { method: 'POST', timeout: 5000 },
        (res) => {
          let data = '';
          res.on('data', chunk => data += chunk);
          res.on('end', () => {
            try {
              resolve(JSON.parse(data));
            } catch (e) {
              resolve({ message: 'Stop requested' });
            }
          });
        }
      );
      req.on('error', () => resolve({ message: 'Stop request failed' }));
      req.end();
    });
  }

  resetSession() {
    console.log('[Lux] Session reset');
  }
}

module.exports = new LuxClient();
