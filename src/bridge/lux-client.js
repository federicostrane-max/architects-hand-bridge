/**
 * Lux Client for Architect's Hand Bridge
 * Handles communication with Lux API and local Tasker Service
 * v3.6 - Fixed mode: 'direct' → dynamic mode based on model
 */

const fetch = require('node-fetch');

class LuxClient {
  constructor() {
    this.apiKey = null;
    this.baseUrl = 'https://api.agiopen.org';
    this.taskerServiceUrl = 'http://127.0.0.1:8765';
    this.taskId = null;
  }

  /**
   * Initialize the client
   */
  initialize(apiKey) {
    this.apiKey = apiKey;
    console.log('[Lux] API configured');
  }

  /**
   * Check if Tasker Service is available
   */
  async checkTaskerService() {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 2000);

      const response = await fetch(`${this.taskerServiceUrl}/status`, {
        method: 'GET',
        signal: controller.signal
      });

      clearTimeout(timeout);

      if (response.ok) {
        const data = await response.json();
        console.log(`[Lux] Tasker Service status: ${data.status}, OAGI: ${data.oagi_available}, Gemini: ${data.gemini_available}`);
        return {
          available: true,
          status: data.status,
          version: data.version || 'unknown',
          oagiAvailable: data.oagi_available,
          geminiAvailable: data.gemini_available || false,
          playwrightAvailable: data.playwright_available || false,
          modes: data.modes || []
        };
      }
    } catch (error) {
      console.log('[Lux] Tasker Service not available');
    }

    return {
      available: false,
      status: 'offline',
      version: 'unknown',
      oagiAvailable: false,
      geminiAvailable: false,
      playwrightAvailable: false,
      modes: []
    };
  }

  /**
   * Execute a direct task (Actor or Thinker mode)
   * Uses the Python Tasker Service which wraps OAGI
   */
  async executeDirectTask(params) {
    const {
      instruction,
      model = 'lux-actor-1',
      maxSteps = 30,
      temperature = 0.1,
      startUrl = null
    } = params;

    // Determine mode from model name
    const mode = model.includes('thinker') ? 'thinker' : 'actor';

    console.log(`[Lux] Executing direct task with model: ${model}`);
    console.log(`[Lux] Mode: ${mode}`);
    console.log(`[Lux] Instruction: ${instruction}`);
    if (startUrl) {
      console.log(`[Lux] Start URL: ${startUrl}`);
    }

    try {
      const response = await fetch(`${this.taskerServiceUrl}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          api_key: this.apiKey,
          task_description: instruction,
          start_url: startUrl,
          max_steps: maxSteps,
          model: model,
          temperature: temperature,
          mode: mode  // 'actor' or 'thinker' based on model
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Tasker Service error: ${response.status} - ${errorText}`);
      }

      const result = await response.json();

      return {
        success: result.success,
        message: result.message,
        summary: result.execution_summary,
        error: result.error
      };

    } catch (error) {
      console.error('[Lux] Direct task error:', error.message);
      return {
        success: false,
        message: 'Task failed with error',
        error: error.message
      };
    }
  }

  /**
   * Execute a Tasker task with todos
   */
  async executeTaskerTask(params) {
    const {
      taskDescription,
      todos,
      todoRecords = [],
      model = 'lux-actor-1',
      maxSteps = 60,
      reflectionInterval = 20,
      temperature = 0.1,
      startUrl = null,
      onTodoStart = null,
      onTodoComplete = null
    } = params;

    console.log('[Lux] Delegating task to Python Tasker Service...');
    console.log(`[Lux] Task: ${taskDescription}`);
    console.log(`[Lux] Todos: ${todos.length}`);
    if (startUrl) {
      console.log(`[Lux] Start URL: ${startUrl}`);
    }

    try {
      // Notify start of first todo
      if (onTodoStart && todos.length > 0) {
        await onTodoStart(0, todos[0]);
      }

      console.log('[Lux] Sending request to Tasker Service...');

      const response = await fetch(`${this.taskerServiceUrl}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          api_key: this.apiKey,
          task_description: taskDescription,
          todos: todos,
          start_url: startUrl,
          max_steps: maxSteps,
          reflection_interval: reflectionInterval,
          model: model,
          temperature: temperature,
          mode: 'tasker'
        })
      });

      console.log('[Lux] Tasker Service response received');

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Tasker Service error: ${response.status} - ${errorText}`);
      }

      const result = await response.json();

      console.log('[Lux] Tasker Service response:', JSON.stringify(result, null, 2));

      // Notify completion of all todos based on result
      if (onTodoComplete) {
        for (let i = 0; i < todos.length; i++) {
          const success = i < result.completed_todos;
          await onTodoComplete(i, success, { message: result.message });
        }
      }

      return {
        success: result.success,
        message: result.message,
        completedTodos: result.completed_todos,
        totalTodos: result.total_todos,
        error: result.error
      };

    } catch (error) {
      console.error('[Lux] Request error:', error.message);

      // Mark all todos as failed
      if (onTodoComplete) {
        for (let i = 0; i < todos.length; i++) {
          await onTodoComplete(i, false, { message: error.message });
        }
      }

      return {
        success: false,
        message: `Tasker Service request failed: ${error.message}`,
        completedTodos: 0,
        totalTodos: todos.length,
        error: error.message
      };
    }
  }

  /**
   * Execute task with Gemini Computer Use (Playwright)
   */
  async executeGeminiTask(params) {
    const {
      apiKey,
      instruction,
      maxSteps = 15,
      startUrl = null,
      headless = false,
      highlightMouse = false
    } = params;

    console.log('[Gemini] Executing with Playwright browser...');
    console.log(`[Gemini] Instruction: ${instruction}`);
    if (startUrl) {
      console.log(`[Gemini] Start URL: ${startUrl}`);
    }

    try {
      const response = await fetch(`${this.taskerServiceUrl}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          api_key: apiKey,
          task_description: instruction,
          mode: 'gemini',
          max_steps_per_todo: maxSteps,
          start_url: startUrl,
          headless: headless,
          highlight_mouse: highlightMouse
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Tasker Service error: ${response.status} - ${errorText}`);
      }

      const result = await response.json();

      return {
        success: result.success,
        message: result.message,
        stepsExecuted: result.steps_executed,
        finalUrl: result.final_url,
        reportPath: result.report_path,
        error: result.error
      };

    } catch (error) {
      console.error('[Gemini] Task error:', error.message);
      return {
        success: false,
        message: 'Gemini task failed with error',
        error: error.message
      };
    }
  }

  /**
   * Test Gemini API key
   */
  async testGeminiApiKey(apiKey) {
    try {
      const response = await fetch(
        `${this.taskerServiceUrl}/debug/test_gemini?api_key=${encodeURIComponent(apiKey)}`,
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

  /**
   * Stop the current task
   */
  async stopTask() {
    try {
      const response = await fetch(`${this.taskerServiceUrl}/stop`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      if (response.ok) {
        console.log('[Lux] Task stop requested');
        return true;
      }
    } catch (error) {
      console.error('[Lux] Error stopping task:', error.message);
    }
    return false;
  }

  /**
   * Check if API key is configured
   */
  isConfigured() {
    return this.apiKey !== null;
  }
}

// Export singleton
module.exports = new LuxClient();
