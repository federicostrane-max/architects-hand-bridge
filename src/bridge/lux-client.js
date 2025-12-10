/**
 * Lux Client for The Architect's Hand Bridge
 * Based on official oagi-python SDK v0.11.0
 * 
 * Endpoints:
 * - GET  /v1/file/upload  → Get presigned S3 URL
 * - PUT  {presigned_url}  → Upload screenshot to S3
 * - POST /v2/message      → Main inference endpoint
 */

const https = require('https');
const http = require('http');

class LuxClient {
    constructor(config = {}) {
        this.apiKey = config.apiKey || process.env.OAGI_API_KEY;
        this.baseUrl = config.baseUrl || 'https://api.agiopen.org';
        this.model = config.model || 'lux-actor-1';
        this.temperature = config.temperature || 0.5;
        this.timeout = config.timeout || 60000;
        
        // Session state
        this.taskId = null;
        this.messagesHistory = [];
        
        if (!this.apiKey) {
            throw new Error('OAGI API key required. Set apiKey in config or OAGI_API_KEY env var.');
        }
        
        console.log(`[Lux] Client initialized - model: ${this.model}, base: ${this.baseUrl}`);
    }

    /**
     * Make HTTP request
     */
    _request(method, url, options = {}) {
        return new Promise((resolve, reject) => {
            const urlObj = new URL(url);
            const isHttps = urlObj.protocol === 'https:';
            const lib = isHttps ? https : http;
            
            const reqOptions = {
                hostname: urlObj.hostname,
                port: urlObj.port || (isHttps ? 443 : 80),
                path: urlObj.pathname + urlObj.search,
                method: method,
                headers: options.headers || {},
                timeout: this.timeout
            };

            const req = lib.request(reqOptions, (res) => {
                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    try {
                        const json = data ? JSON.parse(data) : {};
                        if (res.statusCode >= 400) {
                            reject(new Error(`HTTP ${res.statusCode}: ${json.error?.message || data}`));
                        } else {
                            resolve({ status: res.statusCode, data: json, headers: res.headers });
                        }
                    } catch (e) {
                        // Non-JSON response (e.g., S3 upload returns empty)
                        if (res.statusCode >= 200 && res.statusCode < 300) {
                            resolve({ status: res.statusCode, data: null, headers: res.headers });
                        } else {
                            reject(new Error(`HTTP ${res.statusCode}: ${data}`));
                        }
                    }
                });
            });

            req.on('error', reject);
            req.on('timeout', () => {
                req.destroy();
                reject(new Error('Request timeout'));
            });

            if (options.body) {
                req.write(options.body);
            }
            req.end();
        });
    }

    /**
     * Step 1: Get presigned S3 URL for screenshot upload
     */
    async getUploadUrl() {
        console.log('[Lux] Getting presigned upload URL...');
        
        const response = await this._request('GET', `${this.baseUrl}/v1/file/upload`, {
            headers: {
                'x-api-key': this.apiKey
            }
        });
        
        console.log(`[Lux] Got upload URL, expires at: ${new Date(response.data.expires_at * 1000).toISOString()}`);
        
        return {
            uploadUrl: response.data.url,
            downloadUrl: response.data.download_url,
            uuid: response.data.uuid,
            expiresAt: response.data.expires_at
        };
    }

    /**
     * Step 2: Upload screenshot to S3
     */
    async uploadScreenshot(presignedUrl, screenshotBuffer) {
        console.log(`[Lux] Uploading screenshot (${screenshotBuffer.length} bytes)...`);
        
        await this._request('PUT', presignedUrl, {
            headers: {
                'Content-Type': 'image/png',
                'Content-Length': screenshotBuffer.length
            },
            body: screenshotBuffer
        });
        
        console.log('[Lux] Screenshot uploaded successfully');
    }

    /**
     * Step 3: Call /v2/message endpoint
     */
    async createMessage(screenshotUrl, instruction = null, taskDescription = null) {
        console.log('[Lux] Calling /v2/message...');
        
        // Build user message with screenshot
        const userContent = [
            {
                type: 'image_url',
                image_url: { url: screenshotUrl }
            }
        ];
        
        if (instruction) {
            userContent.push({
                type: 'text',
                text: instruction
            });
        }
        
        const userMessage = {
            role: 'user',
            content: userContent
        };
        
        // Append to history
        this.messagesHistory.push(userMessage);
        
        // Build payload
        const payload = {
            model: this.model,
            messages: this.messagesHistory,
            temperature: this.temperature
        };
        
        // Add task_description for new sessions
        if (taskDescription) {
            payload.task_description = taskDescription;
        }
        
        // Add task_id for continuing sessions
        if (this.taskId) {
            payload.task_id = this.taskId;
        }
        
        const response = await this._request('POST', `${this.baseUrl}/v2/message`, {
            headers: {
                'x-api-key': this.apiKey,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        
        const result = response.data;
        
        // Store task_id for session continuity
        if (result.task_id) {
            this.taskId = result.task_id;
        }
        
        // Add assistant response to history
        if (result.actions && result.actions.length > 0) {
            this.messagesHistory.push({
                role: 'assistant',
                content: JSON.stringify(result.actions)
            });
        }
        
        console.log(`[Lux] Response received - task_id: ${result.task_id}, complete: ${result.is_complete}, actions: ${result.actions?.length || 0}`);
        
        return {
            taskId: result.task_id,
            isComplete: result.is_complete,
            actions: result.actions || [],
            reason: result.reason,
            usage: result.usage
        };
    }

    /**
     * Main method: Process a screenshot and get actions
     * Combines all steps: get URL → upload → inference
     */
    async processScreenshot(screenshotBuffer, instruction = null, taskDescription = null) {
        // Step 1: Get presigned URL
        const { uploadUrl, downloadUrl } = await this.getUploadUrl();
        
        // Step 2: Upload screenshot
        await this.uploadScreenshot(uploadUrl, screenshotBuffer);
        
        // Step 3: Get actions from Lux
        const result = await this.createMessage(downloadUrl, instruction, taskDescription);
        
        return result;
    }

    /**
     * Convert normalized coordinates (0-1000) to screen pixels
     */
    static normalizedToPixels(x, y, screenWidth, screenHeight) {
        return {
            x: Math.round((x / 1000) * screenWidth),
            y: Math.round((y / 1000) * screenHeight)
        };
    }

    /**
     * Parse action argument for coordinates
     */
    static parseCoords(argument) {
        const match = argument.match(/(\d+),\s*(\d+)/);
        if (!match) return null;
        return {
            x: parseInt(match[1]),
            y: parseInt(match[2])
        };
    }

    /**
     * Parse drag coordinates (x1, y1, x2, y2)
     */
    static parseDragCoords(argument) {
        const match = argument.match(/(\d+),\s*(\d+),\s*(\d+),\s*(\d+)/);
        if (!match) return null;
        return {
            x1: parseInt(match[1]),
            y1: parseInt(match[2]),
            x2: parseInt(match[3]),
            y2: parseInt(match[4])
        };
    }

    /**
     * Parse scroll argument (x, y, direction)
     */
    static parseScroll(argument) {
        const match = argument.match(/(\d+),\s*(\d+),\s*(\w+)/);
        if (!match) return null;
        return {
            x: parseInt(match[1]),
            y: parseInt(match[2]),
            direction: match[3].toLowerCase()
        };
    }

    /**
     * Reset session state
     */
    resetSession() {
        this.taskId = null;
        this.messagesHistory = [];
        console.log('[Lux] Session reset');
    }
}

/**
 * Action types returned by Lux
 */
const ActionType = {
    CLICK: 'click',
    LEFT_DOUBLE: 'left_double',
    LEFT_TRIPLE: 'left_triple',
    RIGHT_SINGLE: 'right_single',
    DRAG: 'drag',
    HOTKEY: 'hotkey',
    TYPE: 'type',
    SCROLL: 'scroll',
    FINISH: 'finish',
    WAIT: 'wait',
    CALL_USER: 'call_user'
};

module.exports = { LuxClient, ActionType };
