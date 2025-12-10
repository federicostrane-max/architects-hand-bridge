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
      
      // Step 2: Upload screenshot to S3 using the "url" field
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
   * IMPORTANT: Do NOT include Content-Type header - the presigned URL is not signed with it
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
          // NO Content-Type header! The presigned URL is not signed with it
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
        task_id: this.taskId,  // Required field!
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
   */
  parseResponse(response) {
    const actions = [];
    let feedback = '';
    
    const content = response.content || [];
    
    for (const block of content) {
      if (block.type === 'text') {
        feedback = block.text || '';
        const parsedActions = this.parseActionsFromText(block.text);
        actions.push(...parsedActions);
      }
      
      if (block.type === 'tool_use') {
        const action = this.parseToolUse(block);
        if (action) {
          actions.push(action);
        }
      }
    }

    if (response.computer_call) {
      const action = this.parseComputerCall(response.computer_call);
      if (action) {
        actions.push(action);
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
   * Parse actions from text response
   */
  parseActionsFromText(text) {
    const actions = [];
    if (!text) return actions;

    const actionPattern = /\b(click|type|scroll|key|drag|wait|done|complete)\s*\(([^)]*)\)/gi;
    
    let match;
    while ((match = actionPattern.exec(text)) !== null) {
      const actionType = match[1].toLowerCase();
      const params = match[2].trim();
      
      let action = null;
      
      switch (actionType) {
        case 'click':
          action = this._parseClick(params);
          break;
        case 'type':
          action = this._parseType(params);
          break;
        case 'scroll':
          action = this._parseScroll(params);
          break;
        case 'key':
          action = this._parseKey(params);
          break;
        case 'drag':
          action = this._parseDrag(params);
          break;
        case 'wait':
          action = { type: 'wait', duration: parseInt(params) || 1000 };
          break;
        case 'done':
        case 'complete':
          action = { type: 'done' };
          break;
      }
      
      if (action) {
        actions.push(action);
      }
    }

    return actions;
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
          key: input.key || input.name
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

  parseComputerCall(call) {
    const action = call.action?.toLowerCase();
    
    switch (action) {
      case 'click':
        return {
          type: 'click',
          x: call.coordinate?.[0],
          y: call.coordinate?.[1],
          button: call.button || 'left'
        };
      
      case 'type':
        return {
          type: 'type',
          text: call.text
        };
      
      case 'key':
        return {
          type: 'key',
          key: call.key
        };
      
      case 'scroll':
        return {
          type: 'scroll',
          x: call.coordinate?.[0] || 0,
          y: call.coordinate?.[1] || 0,
          direction: call.direction || 'down'
        };
      
      case 'drag':
        return {
          type: 'drag',
          x1: call.start_coordinate?.[0],
          y1: call.start_coordinate?.[1],
          x2: call.end_coordinate?.[0],
          y2: call.end_coordinate?.[1]
        };
      
      default:
        console.log(`[Lux] Unknown computer_call action: ${action}`);
        return null;
    }
  }

  _parseClick(arg) {
    const coords = arg.split(',').map(s => parseInt(s.trim()));
    if (coords.length >= 2 && !isNaN(coords[0]) && !isNaN(coords[1])) {
      return { type: 'click', x: coords[0], y: coords[1], button: 'left' };
    }
    return null;
  }

  _parseType(arg) {
    const text = arg.replace(/^["']|["']$/g, '').trim();
    if (text) {
      return { type: 'type', text: text };
    }
    return null;
  }

  _parseKey(arg) {
    const key = arg.replace(/^["']|["']$/g, '').trim();
    if (key) {
      return { type: 'key', key: key };
    }
    return null;
  }

  _parseScroll(arg) {
    const parts = arg.split(',').map(s => s.trim());
    if (parts.length >= 3) {
      return {
        type: 'scroll',
        x: parseInt(parts[0]) || 0,
        y: parseInt(parts[1]) || 0,
        direction: parts[2].toLowerCase()
      };
    }
    if (parts.length === 1) {
      return { type: 'scroll', x: 0, y: 0, direction: parts[0].toLowerCase() };
    }
    return null;
  }

  _parseDrag(arg) {
    const coords = arg.split(',').map(s => parseInt(s.trim()));
    if (coords.length >= 4) {
      return {
        type: 'drag',
        x1: coords[0],
        y1: coords[1],
        x2: coords[2],
        y2: coords[3]
      };
    }
    return null;
  }

  resetSession() {
    this.taskId = null;
    this.messagesHistory = [];
    console.log('[Lux] Session reset');
  }
}

module.exports = new LuxClient();
