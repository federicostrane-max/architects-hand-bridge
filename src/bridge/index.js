/**
 * Bridge Index - v3.4
 * Routes tasks to appropriate execution mode (Lux or Gemini)
 * Compatible with tasker_service.py v5.9.0
 */

const { createClient } = require('@supabase/supabase-js');
const LuxClient = require('./lux-client');

class Bridge {
    constructor(config) {
        this.config = config;
        this.supabase = createClient(config.supabaseUrl, config.supabaseKey);
        this.luxClient = new LuxClient();
        this.isRunning = false;
        this.currentTask = null;
        this.taskerStatus = null;
        
        // Polling interval (3 seconds)
        this.pollInterval = 3000;
    }

    async start() {
        console.log('🌉 Bridge starting...');
        
        // Check tasker service status
        await this.checkTaskerService();
        
        this.isRunning = true;
        this.poll();
        
        console.log('✅ Bridge started, polling for tasks...');
    }

    async stop() {
        this.isRunning = false;
        console.log('🛑 Bridge stopped');
    }

    async checkTaskerService() {
        try {
            this.taskerStatus = await this.luxClient.checkTaskerService();
            console.log(`📡 Tasker Service: ${this.taskerStatus.status}`);
            console.log(`   Version: ${this.taskerStatus.version}`);
            console.log(`   OAGI Available: ${this.taskerStatus.oagiAvailable ? '✅' : '❌'}`);
            console.log(`   Gemini Available: ${this.taskerStatus.geminiAvailable ? '✅' : '❌'}`);
            console.log(`   Playwright Available: ${this.taskerStatus.playwrightAvailable ? '✅' : '❌'}`);
            console.log(`   Modes: ${this.taskerStatus.modes.join(', ')}`);
            return this.taskerStatus;
        } catch (error) {
            console.error('❌ Tasker service not available:', error.message);
            this.taskerStatus = null;
            return null;
        }
    }

    async poll() {
        if (!this.isRunning) return;

        try {
            // Fetch pending tasks
            const { data: tasks, error } = await this.supabase
                .from('lux_tasks')
                .select('*')
                .eq('status', 'pending')
                .order('created_at', { ascending: true })
                .limit(1);

            if (error) {
                console.error('❌ Supabase error:', error.message);
            } else if (tasks && tasks.length > 0) {
                await this.handleNewTask(tasks[0]);
            }
        } catch (error) {
            console.error('❌ Poll error:', error.message);
        }

        // Schedule next poll
        setTimeout(() => this.poll(), this.pollInterval);
    }

    async handleNewTask(task) {
        console.log(`\n📥 New task received: ${task.id}`);
        console.log(`   Mode: ${task.lux_mode}`);
        console.log(`   Task: ${task.task_description?.substring(0, 100)}...`);

        this.currentTask = task;

        try {
            // Update status to running
            await this.updateTaskStatus(task.id, 'running');

            // Check service availability
            if (!this.taskerStatus) {
                await this.checkTaskerService();
            }

            // Route based on mode
            let result;
            switch (task.lux_mode) {
                case 'gemini':
                    if (!this.taskerStatus?.geminiAvailable) {
                        throw new Error('Gemini mode not available on tasker service');
                    }
                    if (!this.taskerStatus?.playwrightAvailable) {
                        throw new Error('Playwright not available. Run: pip install playwright && playwright install chromium');
                    }
                    result = await this.executeGeminiMode(task);
                    break;
                    
                case 'actor':
                case 'thinker':
                case 'tasker':
                    if (!this.taskerStatus?.oagiAvailable) {
                        throw new Error('Lux/OAGI mode not available on tasker service');
                    }
                    result = await this.executeLuxMode(task);
                    break;
                    
                default:
                    throw new Error(`Unknown mode: ${task.lux_mode}`);
            }

            // Update task with result
            await this.updateTaskResult(task.id, result);
            console.log(`✅ Task ${task.id} completed`);

        } catch (error) {
            console.error(`❌ Task ${task.id} failed:`, error.message);
            await this.updateTaskError(task.id, error.message);
        }

        this.currentTask = null;
    }

    async executeLuxMode(task) {
        console.log(`🔷 Executing with Lux (${task.lux_mode})...`);
        
        const apiKey = task.oagi_api_key || this.config.oagiApiKey;
        if (!apiKey) {
            throw new Error('OAGI API key not configured');
        }

        // Determine which method to use based on mode
        if (task.lux_mode === 'tasker') {
            return await this.luxClient.executeTaskerTask({
                apiKey: apiKey,
                instruction: task.task_description,
                maxSteps: task.max_steps || 15,
                startUrl: task.start_url
            });
        } else {
            return await this.luxClient.executeDirectTask({
                apiKey: apiKey,
                instruction: task.task_description,
                mode: task.lux_mode,
                maxSteps: task.max_steps || 15,
                startUrl: task.start_url
            });
        }
    }

    async executeGeminiMode(task) {
        console.log(`🔵 Executing with Gemini Computer Use (Playwright)...`);
        
        const apiKey = task.gemini_api_key || this.config.geminiApiKey;
        if (!apiKey) {
            throw new Error('Gemini API key not configured');
        }

        return await this.luxClient.executeGeminiTask({
            apiKey: apiKey,
            instruction: task.task_description,
            maxSteps: task.max_steps || 15,
            startUrl: task.start_url,
            headless: task.headless || false,
            highlightMouse: task.highlight_mouse || false
        });
    }

    async updateTaskStatus(taskId, status) {
        const { error } = await this.supabase
            .from('lux_tasks')
            .update({ 
                status: status,
                updated_at: new Date().toISOString()
            })
            .eq('id', taskId);

        if (error) {
            console.error('Failed to update task status:', error.message);
        }
    }

    async updateTaskResult(taskId, result) {
        const { error } = await this.supabase
            .from('lux_tasks')
            .update({
                status: result.success ? 'completed' : 'failed',
                result: result,
                completed_at: new Date().toISOString(),
                updated_at: new Date().toISOString()
            })
            .eq('id', taskId);

        if (error) {
            console.error('Failed to update task result:', error.message);
        }
    }

    async updateTaskError(taskId, errorMessage) {
        const { error } = await this.supabase
            .from('lux_tasks')
            .update({
                status: 'failed',
                error: errorMessage,
                updated_at: new Date().toISOString()
            })
            .eq('id', taskId);

        if (error) {
            console.error('Failed to update task error:', error.message);
        }
    }
}

module.exports = Bridge;
