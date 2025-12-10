/**
 * Lux Client - OpenAGI Lux API Integration
 * Handles communication with lux-actor-1 model for browser automation
 */

const https = require('https');
const crypto = require('crypto');

class LuxClient {
  constructor() {
    this.apiKey = null;
    this.baseUrl = 'api.agiopen.org';
    this.model = 'lux-actor-1';
    this.taskId = null;
    this.messagesHistory = [];
  }

  /**
   * Set the API key
   */
  setApiKey(key) {
    this.apiKey = key;
    console.log(`[Lux] API key set (starts with: ${key?.substring(0, 8)}...)`);
  }

  /**
   * Generate a new task ID (UUID v4)
   */
  generateTaskId() {
    return crypto.randomUUID();
  }

  /**
   * Execute a step - send screenshot and instruction to Lux
   */
  async executeStep(screenshotBase64, instruction, context = '') {
    if (!this.apiKey) {
      throw new Error('API key not set');
    }

    // Generate task_id if not already set
    if (!this.taskId) {
      this.taskId = this.generateTaskId();
      console.log(`[Lux] New task_id generated: ${this.taskId}`);
    }

    try {
      // Step 1: Get presigned URL for upload
      console.log('[Lux] Getting presigned URL...');
      const uploadInfo = await this.getPresignedUrl();
      console.log('[Lux] Got presigned URL');
      
      // Step 2: Upload screenshot to S3
      console.log('[Lux] Uploading screenshot to S3...');
      await this.uploadToS3(uploadInfo.url, screenshotBase64);
      console.log('[Lux] Screenshot uploaded successfully');
      
      // Step 3: Call Lux API with the download_url
      console.log('[Lux] Calling Lux API...');
      const result = await this.callLuxApi(uploadInfo.download_url, instruction, context);
      
      return result;
    } catch (error) {
      console.error('[Lux] Error:', error.message);
      return {
        status: 'error',
        actions: [],
        feedback: error.message,
        raw: null
      };
    }
  }

  /**
   * Get presigned URL for S3 upload
   */
  async getPresignedUrl() {
    return new Promise((resolve, reject) => {
      const options = {
        hostname: this.baseUrl,
        port: 443,
        path: '/v1/file/upload',
        method: 'GET',
        headers: {
          'x-api-key': this.apiKey
        }
      };

      const req = https.request(options, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          try {
            if (res.statusCode !== 200) {
              reject(new Error(`Failed to get presigned URL: ${res.statusCode} - ${data}`));
              return;
            }
            const parsed = JSON.parse(data);
            console.log('[Lux] Presigned URL fields:', Object.keys(parsed).join(', '));
            if (!parsed.url || !parsed.download_url) {
              reject(new Error(`Invalid presigned URL response - missing url or download_url`));
              return;
            }
            resolve(parsed);
          } catch (e) {
            reject(new Error(`Failed to parse presigned URL response: ${e.message}`));
          }
        });
      });

      req.on('error', reject);
      req.end();
    });
  }

  /**
   * Upload image to S3 using presigned URL
   */
  async uploadToS3(presignedUrl, base64Image) {
    return new Promise((resolve, reject) => {
      const imageBuffer = Buffer.from(base64Image, 'base64');
      
      let url;
      try {
        url = new URL(presignedUrl);
      } catch (e) {
        reject(new Error(`Invalid S3 URL format`));
        return;
      }
      
      const options = {
        hostname: url.hostname,
        port: 443,
        path: url.pathname + url.search,
        method: 'PUT',
        headers: {
          'Content-Length': imageBuffer.length
        }
      };

      const req = https.request(options, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve();
          } else {
            reject(new Error(`S3 upload failed: ${res.statusCode}`));
          }
        });
      });

      req.on('error', reject);
      req.write(imageBuffer);
      req.end();
    });
  }

  /**
   * Call Lux API with image and instruction
   */
  async callLuxApi(imageUrl, instruction, context) {
    return new Promise((resolve, reject) => {
      const taskDescription = context 
        ? `${context}\n\nCurrent instruction: ${instruction}`
        : instruction;

      const messages = [
        {
          role: 'user',
          content: [
            {
              type: 'image_url',
              image_url: { url: imageUrl }
            },
            {
              type: 'text',
              text: instruction
            }
          ]
        }
      ];

      const requestBody = JSON.stringify({
        model: this.model,
        task_id: this.taskId,
        messages: messages,
        task_description: taskDescription,
        max_tokens: 1024
      });

      console.log('[Lux] Request body (truncated):', requestBody.substring(0, 200) + '...');

      const options = {
        hostname: this.baseUrl,
        port: 443,
        path: '/v2/message',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': this.apiKey,
          'Content-Length': Buffer.byteLength(requestBody)
        }
      };

      const req = https.request(options, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          try {
            if (res.statusCode !== 200) {
              reject(new Error(`Lux API error: ${res.statusCode} - ${data.substring(0, 300)}`));
              return;
            }

            const response = JSON.parse(data);
            console.log('[Lux] Raw response:', JSON.stringify(response).substring(0, 500));
            const result = this.parseResponse(response);
            console.log('[Lux] Parsed actions:', JSON.stringify(result.actions));
            resolve(result);
          } catch (e) {
            reject(new Error(`Failed to parse Lux response: ${e.message}`));
          }
        });
      });

      req.on('error', reject);
      req.write(requestBody);
      req.end();
    });
  }

  /**
   * Parse Lux API response into actions
   * Lux returns: { actions: [{type, argument, coordinates, ...}], reason: "..." }
   */
  parseResponse(response) {
    const actions = [];
    let feedback = response.reason || '';
    
    // Lux returns actions directly in response.actions array
    if (response.actions && Array.isArray(response.actions)) {
      for (const luxAction of response.actions) {
        const action = this.convertLuxAction(luxAction);
        if (action) {
          actions.push(action);
        }
      }
    }
    
    // Also check for content array (Claude-style format, just in case)
    if (response.content && Array.isArray(response.content)) {
      for (const block of response.content) {
        if (block.type === 'text') {
          feedback = block.text || feedback;
        }
        if (block.type === 'tool_use') {
          const action = this.parseToolUse(block);
          if (action) {
            actions.push(action);
          }
        }
      }
    }

    return {
      status: actions.length > 0 ? 'success' : 'no_action',
      actions,
      feedback,
      raw: response
    };
  }

  /**
   * Convert Lux action format to our internal format
   * Lux uses: {type: "click", coordinates: [x,y]} or {type: "hotkey", argument: "enter"}
   * We use: {type: "click", x, y} or {type: "key", key: "Enter"}
   */
  convertLuxAction(luxAction) {
    const type = luxAction.type?.toLowerCase();
    
    switch (type) {
      case 'click':
      case 'left_click':
      case 'right_click':
      case 'double_click':
        // Lux uses coordinates array [x, y]
        const coords = luxAction.coordinates || luxAction.coordinate || [];
        if (coords.length >= 2) {
          return {
            type: 'click',
            x: coords[0],
            y: coords[1],
            button: type === 'right_click' ? 'right' : 'left',
            double: type === 'double_click'
          };
        }
        return null;
      
      case 'type':
      case 'input':
        return {
          type: 'type',
          text: luxAction.argument || luxAction.text || ''
        };
      
      case 'hotkey':
      case 'key':
      case 'keypress':
        // Lux uses argument for key name
        const key = luxAction.argument || luxAction.key || '';
        return {
          type: 'key',
          key: this.normalizeKeyName(key)
        };
      
      case 'scroll':
        return {
          type: 'scroll',
          x: luxAction.coordinates?.[0] || 0,
          y: luxAction.coordinates?.[1] || 0,
          direction: luxAction.direction || luxAction.argument || 'down'
        };
      
      case 'drag':
        const start = luxAction.start_coordinates || luxAction.coordinates || [];
        const end = luxAction.end_coordinates || [];
        if (start.length >= 2 && end.length >= 2) {
          return {
            type: 'drag',
            x1: start[0],
            y1: start[1],
            x2: end[0],
            y2: end[1]
          };
        }
        return null;
      
      case 'wait':
        return {
          type: 'wait',
          duration: luxAction.argument || luxAction.duration || 1000
        };
      
      case 'done':
      case 'complete':
      case 'finished':
        return { type: 'done' };
      
      default:
        console.log(`[Lux] Unknown action type: ${type}`, luxAction);
        return null;
    }
  }

  /**
   * Normalize key names to match Playwright expectations
   */
  normalizeKeyName(key) {
    const keyMap = {
      'enter': 'Enter',
      'return': 'Enter',
      'tab': 'Tab',
      'escape': 'Escape',
      'esc': 'Escape',
      'backspace': 'Backspace',
      'delete': 'Delete',
      'space': 'Space',
      'up': 'ArrowUp',
      'down': 'ArrowDown',
      'left': 'ArrowLeft',
      'right': 'ArrowRight',
      'home': 'Home',
      'end': 'End',
      'pageup': 'PageUp',
      'pagedown': 'PageDown',
      'ctrl': 'Control',
      'control': 'Control',
      'alt': 'Alt',
      'shift': 'Shift',
      'meta': 'Meta',
      'cmd': 'Meta',
      'command': 'Meta'
    };
    
    const normalized = keyMap[key.toLowerCase()] || key;
    return normalized;
  }

  /**
   * Parse tool_use block (Claude-style format)
   */
  parseToolUse(block) {
    const name = block.name?.toLowerCase();
    const input = block.input || {};

    switch (name) {
      case 'click':
      case 'mouse_click':
        return {
          type: 'click',
          x: input.x || input.coordinate?.[0],
          y: input.y || input.coordinate?.[1],
          button: input.button || 'left'
        };
      
      case 'type':
      case 'keyboard_type':
        return {
          type: 'type',
          text: input.text || input.content
        };
      
      case 'key':
      case 'keyboard_key':
        return {
          type: 'key',
          key: this.normalizeKeyName(input.key || input.name || '')
        };
      
      case 'scroll':
        return {
          type: 'scroll',
          x: input.x || 0,
          y: input.y || 0,
          direction: input.direction || 'down'
        };
      
      default:
        console.log(`[Lux] Unknown tool: ${name}`);
        return null;
    }
  }

  resetSession() {
    this.taskId = null;
    this.messagesHistory = [];
    console.log('[Lux] Session reset');
  }
}

module.exports = new LuxClient();
