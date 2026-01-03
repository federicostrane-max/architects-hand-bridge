/**
 * Lux Client - v3.4
 * Communicates with Python tasker_service.py
 * Supports: Lux (actor/thinker/tasker) + Gemini Computer Use
 * Compatible with tasker_service.py v5.9.0
 */

const fetch = require('node-fetch');

class LuxClient {
    constructor(baseUrl = 'http://127.0.0.1:8765') {
        this.baseUrl = baseUrl;
        this.timeout = 300000; // 5 minutes timeout for long tasks
    }

    /**
     * Check if tasker service is running and get its capabilities
     */
    async checkTaskerService() {
        try {
            const response = await fetch(`${this.baseUrl}/status`, {
                method: 'GET',
                timeout: 5000
            });

            if (!response.ok) {
                throw new Error(`Status check failed: ${response.status}`);
            }

            const data = await response.json();
            
            return {
                status: data.status,
                version: data.version,
                oagiAvailable: data.oagi_available,
                geminiAvailable: data.gemini_available,
                modes: data.modes || []
            };
        } catch (error) {
            throw new Error(`Tasker service unreachable: ${error.message}`);
        }
    }

    /**
     * Execute task with Lux Actor or Thinker mode
     */
    async executeDirectTask({ apiKey, instruction, mode = 'actor', maxSteps = 15, startUrl = null }) {
        console.log(`📤 Sending ${mode} task to tasker service...`);

        const payload = {
            api_key: apiKey,
            task_description: instruction,
            mode: mode,
            max_steps_per_todo: maxSteps
        };

        if (startUrl) {
            payload.start_url = startUrl;
        }

        return await this._executeRequest(payload);
    }

    /**
     * Execute task with Lux TaskerAgent mode
     */
    async executeTaskerTask({ apiKey, instruction, maxSteps = 15, startUrl = null }) {
        console.log('📤 Sending tasker task to service...');

        const payload = {
            api_key: apiKey,
            task_description: instruction,
            mode: 'tasker',
            max_steps_per_todo: maxSteps
        };

        if (startUrl) {
            payload.start_url = startUrl;
        }

        return await this._executeRequest(payload);
    }

    /**
     * Execute task with Gemini Computer Use
     */
    async executeGeminiTask({ apiKey, instruction, maxSteps = 15, startUrl = null }) {
        console.log('📤 Sending Gemini Computer Use task to service...');

        const payload = {
            api_key: apiKey,
            task_description: instruction,
            mode: 'gemini',
            max_steps_per_todo: maxSteps
        };

        if (startUrl) {
            payload.start_url = startUrl;
        }

        return await this._executeRequest(payload);
    }

    /**
     * Internal method to execute request to tasker service
     */
    async _executeRequest(payload) {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), this.timeout);

            const response = await fetch(`${this.baseUrl}/execute`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload),
                signal: controller.signal
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }

            const result = await response.json();
            
            console.log(`📥 Response received:`);
            console.log(`   Success: ${result.success}`);
            console.log(`   Steps: ${result.steps_executed}`);
            console.log(`   Message: ${result.message?.substring(0, 100)}...`);

            return result;

        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error('Task execution timed out');
            }
            throw error;
        }
    }

    /**
     * Test Gemini API key
     */
    async testGeminiApiKey(apiKey) {
        try {
            const response = await fetch(
                `${this.baseUrl}/debug/test_gemini?api_key=${encodeURIComponent(apiKey)}`,
                {
                    method: 'POST',
                    timeout: 10000
                }
            );

            return await response.json();
        } catch (error) {
            return {
                success: false,
                error: error.message
            };
        }
    }
}

module.exports = LuxClient;
