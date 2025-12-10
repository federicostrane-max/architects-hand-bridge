/**
 * Lux Client for The Architect's Hand Bridge
 * Based on official oagi-python SDK v0.11.0
 * 
 * CORRECT Endpoints:
 * - GET  /v1/file/upload  → Get presigned S3 URL
 * - PUT  {presigned_url}  → Upload screenshot to S3
 * - POST /v2/message      → Main inference endpoint
 * 
 * CORRECT Auth Header: x-api-key (NOT Authorization: Bearer)
 */

const https = require('https');

class LuxClient {
    constructor() {
        this.apiKey = null;
        this.baseUrl = 'api.agiopen.org';
        this.model = 'lux-actor-1';
        this.temperature = 0.5;
        this.timeout = 60000;
        
        // Session state
        this.taskId = null;
        this.messagesHistory = [];
    }

    setApiKey(key) {
        this.apiKey = key;
        console.log(`[Lux] API key set (starts with: ${key?.substring(0, 8)}...)`);
    }

    setModel(model) {
        this.model = model;
        console.log(`[Lux] Model set to: ${model}`);
    }

    /**
     * Make HTTPS request
     */
    _request(method, path, options = {}) {
        return new Promise((resolve, reject) => {
            const reqOptions = {
                hostname: this.baseUrl,
                port: 443,
                path: path,
                method: method,
                headers: {
                    'x-api-key': this.apiKey,
                    ...options.headers
                },
                timeout: this.timeout
            };

            const req = https.request(reqOptions, (res) => {
                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    try {
                        const json = data ? JSON.parse(data) : {};
                        if (res.statusCode >= 400) {
                            const errorMsg = json.error?.message || json.message || data;
                            reject(new Error(`HTTP ${res.statusCode}: ${errorMsg}`));
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
     * Upload to S3 using presigned URL
     */
    _uploadToS3(presignedUrl, imageBuffer) {
        return new Promise((resolve, reject) => {
            const url = new URL(presignedUrl);
            
            const reqOptions = {
                hostname: url.hostname,
                port: 443,
                path: url.pathname + url.search,
                method: 'PUT',
                headers: {
                    'Content-Type': 'image/png',
                    'Content-Length': imageBuffer.length
                },
                timeout: this.timeout
            };

            const req = https.request(reqOptions, (res) => {
                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    if (res.statusCode >= 200 && res.statusCode < 300) {
                        resolve({ status: res.statusCode });
                    } else {
                        reject(new Error(`S3 upload failed: ${res.statusCode} - ${data}`));
                    }
                });
            });

            req.on('error', reject);
            req.on('timeout', () => {
                req.destroy();
                reject(new Error('S3 upload timeout'));
            });

            req.write(imageBuffer);
            req.end();
        });
    }

    /**
     * Step 1: Get presigned S3 URL for screenshot upload
     */
    async getUploadUrl() {
        console.log('[Lux] Getting presigned upload URL...');
        
        const response = await this._request('GET', '/v1/file/upload');
        
        console.log(`[Lux] Got upload URL, uuid: ${response.data.uuid}`);
        
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
        
        await this._uploadToS3(presignedUrl, screenshotBuffer);
        
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
        if (taskDescription && !this.taskId) {
            payload.task_description = taskDescription;
        }
        
        // Add task_id for continuing sessions
        if (this.taskId) {
            payload.task_id = this.taskId;
        }
        
        const response = await this._request('POST', '/v2/message', {
            headers: {
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
        
        console.log(`[Lux] Response - task_id: ${result.task_id}, complete: ${result.is_complete}, actions: ${result.actions?.length || 0}`);
        
        return result;
    }

    /**
     * Main method used by bridge: executeStep
     * Takes base64 screenshot, instruction, and context
     * Returns { status, feedback, actions, raw }
     */
    async executeStep(screenshotBase64, instruction, instructionContext = null) {
        if (!this.apiKey) {
            throw new Error('OpenAGI API key not set');
        }

        try {
            // Convert base64 to buffer
            const screenshotBuffer = Buffer.from(screenshotBase64, 'base64');
            
            // Step 1: Get presigned URL
            const { uploadUrl, downloadUrl } = await this.getUploadUrl();
            
            // Step 2: Upload screenshot to S3
            await this.uploadScreenshot(uploadUrl, screenshotBuffer);
            
            // Build full instruction with context
            let fullInstruction = instruction;
            if (instructionContext) {
                fullInstruction = `Context: ${instructionContext}\n\nInstruction: ${instruction}`;
            }
            
            // Step 3: Get actions from Lux
            const result = await this.createMessage(downloadUrl, fullInstruction, instruction);
            
            // Convert to expected format
            const actions = (result.actions || []).map(action => {
                return this._convertAction(action);
            });

            // Determine status
            let status = 'success';
            if (result.is_complete) {
                status = 'complete';
            } else if (result.error) {
                status = 'error';
            }

            return {
                status: status,
                feedback: result.reason || null,
                actions: actions,
                raw: result
            };

        } catch (error) {
            console.error('[Lux] Error:', error.message);
            return {
                status: 'error',
                feedback: error.message,
                actions: [],
                raw: null
            };
        }
    }

    /**
     * Convert Lux action to browser-controller format
     * Lux uses normalized 0-1000 coordinates
     */
    _convertAction(action) {
        const type = action.type;
        const arg = action.argument || '';

        switch (type) {
            case 'click':
            case 'left_double':
            case 'left_triple':
            case 'right_single': {
                const coords = this._parseCoords(arg);
                if (coords) {
                    return {
                        type: type === 'left_double' ? 'doubleClick' : 
                              type === 'right_single' ? 'rightClick' : 'click',
                        x: coords.x,
                        y: coords.y,
                        normalized: true  // Flag that coords are 0-1000 normalized
                    };
                }
                break;
            }

            case 'type': {
                return {
                    type: 'type',
                    text: arg
                };
            }

            case 'hotkey': {
                return {
                    type: 'hotkey',
                    keys: arg.split('+').map(k => k.trim())
                };
            }

            case 'scroll': {
                const scroll = this._parseScroll(arg);
                if (scroll) {
                    return {
                        type: 'scroll',
                        x: scroll.x,
                        y: scroll.y,
                        direction: scroll.direction,
                        normalized: true
                    };
                }
                break;
            }

            case 'drag': {
                const drag = this._parseDrag(arg);
                if (drag) {
                    return {
                        type: 'drag',
                        startX: drag.x1,
                        startY: drag.y1,
                        endX: drag.x2,
                        endY: drag.y2,
                        normalized: true
                    };
                }
                break;
            }

            case 'wait': {
                return {
                    type: 'wait',
                    duration: parseInt(arg) || 1000
                };
            }

            case 'finish':
            case 'done':
            case 'complete': {
                return {
                    type: 'done'
                };
            }

            case 'call_user': {
                return {
                    type: 'call_user',
                    message: arg
                };
            }
        }

        // Unknown action type
        return {
            type: type,
            raw: arg
        };
    }

    /**
     * Parse coordinates from "x, y" format
     */
    _parseCoords(arg) {
        const match = arg.match(/(\d+),\s*(\d+)/);
        if (!match) return null;
        return {
            x: parseInt(match[1]),
            y: parseInt(match[2])
        };
    }

    /**
     * Parse scroll from "x, y, direction" format
     */
    _parseScroll(arg) {
        const match = arg.match(/(\d+),\s*(\d+),\s*(\w+)/);
        if (!match) return null;
        return {
            x: parseInt(match[1]),
            y: parseInt(match[2]),
            direction: match[3].toLowerCase()
        };
    }

    /**
     * Parse drag from "x1, y1, x2, y2" format
     */
    _parseDrag(arg) {
        const match = arg.match(/(\d+),\s*(\d+),\s*(\d+),\s*(\d+)/);
        if (!match) return null;
        return {
            x1: parseInt(match[1]),
            y1: parseInt(match[2]),
            x2: parseInt(match[3]),
            y2: parseInt(match[4])
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

// Export singleton instance (same interface as before)
module.exports = new LuxClient();
