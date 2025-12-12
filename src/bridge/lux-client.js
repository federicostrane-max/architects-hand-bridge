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

  setApiKey(key) {
    this.apiKey = key;
    console.log(`[Lux] API key set (starts with: ${key?.substring(0, 8)}...)`);
  }

  generateTaskId() {
    return crypto.randomUUID();
  }

  async executeStep(screenshotBase64, instruction, context = '') {
    if (!this.apiKey) {
      throw new Error('API key not set');
    }

    if (!this.taskId) {
      this.taskId = this.generateTaskId();
      console.log(`[Lux] New task_id generated: ${this.taskId}`);
    }

    try {
      console.log('[Lux] Getting presigned URL...');
      const uploadInfo = await this.getPresignedUrl();
      console.log('[Lux] Got presigned URL');
      
      console.log('[Lux] Uploading screenshot to S3...');
      await this.uploadToS3(uploadInfo.url, screenshotBase64);
      console.log('[Lux] Screenshot uploaded successfully');
      
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

  async callLuxApi(imageUrl, instruction, context) {
    return new Promise((resolve, reject) => {
      // Keep task_description simple for Actor mode
      const taskDescription = context || instruction;

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

  parseResponse(response) {
    const actions = [];
    let feedback = response.reason || '';
    
    // Lux returns actions in response.actions array
    if (response.actions && Array.isArray(response.actions)) {
      console.log('[Lux] Found', response.actions.length, 'actions in response');
      for (const luxAction of response.actions) {
        console.log('[Lux] Processing action:', JSON.stringify(luxAction));
        const action = this.convertLuxAction(luxAction);
        if (action) {
          actions.push(action);
        }
      }
    }
    
    // Check content array (Claude-style format)
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
   * 
   * Lux returns actions like:
   * - {type: "click", argument: "510, 510"}
   * - {type: "click", coordinates: [510, 510]}
   * - {type: "type", argument: "search text"}
   * - {type: "hotkey", argument: "enter"}
   */
  convertLuxAction(luxAction) {
    const type = luxAction.type?.toLowerCase();
    
    switch (type) {
      case 'click':
      case 'left_click':
      case 'right_click':
      case 'double_click': {
        // Try multiple coordinate formats
        let coords = luxAction.coordinates || luxAction.coordinate || [];
        
        // IMPORTANT: Parse from argument string "510, 510"
        if ((!coords || coords.length < 2) && luxAction.argument) {
          const argStr = String(luxAction.argument);
          const parts = argStr.split(',').map(s => parseInt(s.trim()));
          if (parts.length >= 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
            coords = parts;
            console.log('[Lux] Parsed coordinates from argument:', coords);
          }
        }
        
        if (coords && coords.length >= 2) {
          return {
            type: 'click',
            x: coords[0],
            y: coords[1],
            button: type === 'right_click' ? 'right' : 'left',
            double: type === 'double_click'
          };
        }
        console.log('[Lux] Could not parse click coordinates from:', JSON.stringify(luxAction));
        return null;
      }
      
      case 'type':
      case 'input': {
        const text = luxAction.argument || luxAction.text || '';
        if (text) {
          return {
            type: 'type',
            text: text
          };
        }
        return null;
      }
      
      case 'hotkey':
      case 'key':
      case 'keypress': {
        const key = luxAction.argument || luxAction.key || '';
        if (key) {
          return {
            type: 'key',
            key: this.normalizeKeyName(key)
          };
        }
        return null;
      }
      
      case 'scroll': {
        let coords = luxAction.coordinates || [];
        // Parse coordinates from argument if needed
        if ((!coords || coords.length < 2) && luxAction.argument) {
          const parts = String(luxAction.argument).split(',').map(s => s.trim());
          if (parts.length >= 2 && !isNaN(parseInt(parts[0]))) {
            coords = parts.map(p => parseInt(p));
          }
        }
        return {
          type: 'scroll',
          x: coords[0] || 0,
          y: coords[1] || 0,
          direction: luxAction.direction || (typeof luxAction.argument === 'string' && isNaN(parseInt(luxAction.argument)) ? luxAction.argument : 'down')
        };
      }
      
      case 'drag': {
        let start = luxAction.start_coordinates || luxAction.coordinates || [];
        let end = luxAction.end_coordinates || [];
        
        // Parse from argument: "x1, y1, x2, y2"
        if ((!start.length || !end.length) && luxAction.argument) {
          const parts = String(luxAction.argument).split(',').map(s => parseInt(s.trim()));
          if (parts.length >= 4) {
            start = [parts[0], parts[1]];
            end = [parts[2], parts[3]];
          }
        }
        
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
      }
      
      case 'wait':
        return {
          type: 'wait',
          duration: parseInt(luxAction.argument) || luxAction.duration || 1000
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
    
    return keyMap[key.toLowerCase()] || key;
  }

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
