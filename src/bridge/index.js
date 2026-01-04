/**
 * Architect's Hand Bridge - Main Entry Point
 * Routes tasks to appropriate executor based on lux_mode or computer_use_provider
 * v3.5 - Added Gemini Computer Use support (Playwright)
 */

const supabaseClient = require('./supabase-client');
const luxClient = require('./lux-client');

class Bridge {
  constructor() {
    this.isRunning = false;
    this.isPaused = false;
    this.currentTask = null;
    this.pollInterval = null;
    this.config = null;
    this.supabase = null;
    this.taskerStatus = null;

    // Callbacks
    this.callbacks = {
      sendLog: null,
      sendStatus: null,
      sendTaskUpdate: null,
      sendStepUpdate: null,
      sendScreenshot: null,
      minimizeWindow: null,
      restoreWindow: null
    };
  }

  /**
   * Set callbacks (called by main.js)
   */
  setCallbacks(callbacks) {
    this.callbacks = { ...this.callbacks, ...callbacks };
    console.log('[Bridge] Callbacks configured');
  }

  /**
   * Log message
   */
  log(level, message) {
    console.log(`[Bridge] [${level}] ${message}`);
    if (this.callbacks.sendLog) {
      this.callbacks.sendLog(level, message);
    }
  }

  /**
   * Start the bridge (called by main.js with config and supabase)
   */
  async start(config, supabase) {
    if (this.isRunning) {
      this.log('WARN', 'Bridge already running');
      return;
    }

    this.config = config;
    this.supabase = supabase;

    this.log('INFO', 'Initializing bridge...');

    // Initialize supabase client module
    if (config.supabaseUrl && config.supabaseAnonKey) {
      supabaseClient.initialize(config.supabaseUrl, config.supabaseAnonKey);
      this.log('INFO', 'Supabase client configured');
    }

    // Initialize Lux client
    if (config.openAgiApiKey) {
      luxClient.initialize(config.openAgiApiKey);
      this.log('INFO', 'Lux API configured');
    }

    // Try to get current user from passed supabase instance
    if (supabase) {
      try {
        const { data: { user } } = await supabase.auth.getUser();
        if (user) {
          supabaseClient.user = user;
          this.log('INFO', `User: ${user.email}`);
        }
      } catch (e) {
        this.log('WARN', 'Could not get user from session');
      }
    }

    this.isRunning = true;
    this.isPaused = false;

    // Check Tasker Service availability
    this.log('INFO', 'Checking Tasker Service...');
    await this.checkTaskerService();

    // Start polling for tasks
    this.startPolling();
    this.log('INFO', 'Bridge started - polling for tasks every 3 seconds');

    if (this.callbacks.sendStatus) {
      this.callbacks.sendStatus('running');
    }
  }

  /**
   * Check Tasker Service status
   */
  async checkTaskerService() {
    try {
      this.taskerStatus = await luxClient.checkTaskerService();
      this.log('INFO', `Tasker Service v${this.taskerStatus.version}`);
      this.log('INFO', `  OAGI Available: ${this.taskerStatus.oagiAvailable ? '✅' : '❌'}`);
      this.log('INFO', `  Gemini Available: ${this.taskerStatus.geminiAvailable ? '✅' : '❌'}`);
      this.log('INFO', `  Playwright Available: ${this.taskerStatus.playwrightAvailable ? '✅' : '❌'}`);
      this.log('INFO', `  Modes: ${this.taskerStatus.modes.join(', ')}`);
    } catch (e) {
      this.log('WARN', 'Tasker Service not available - start python-service/tasker_service.py');
      this.taskerStatus = { available: false, oagiAvailable: false, geminiAvailable: false, playwrightAvailable: false };
    }
  }

  /**
   * Stop the bridge
   */
  async stop() {
    this.isRunning = false;
    this.isPaused = false;
    this.stopPolling();
    this.log('INFO', 'Bridge stopped');

    if (this.callbacks.sendStatus) {
      this.callbacks.sendStatus('stopped');
    }
  }

  /**
   * Pause the bridge
   */
  pause() {
    this.isPaused = true;
    this.log('INFO', 'Bridge paused');

    if (this.callbacks.sendStatus) {
      this.callbacks.sendStatus('paused');
    }
  }

  /**
   * Resume the bridge
   */
  resume() {
    this.isPaused = false;
    this.log('INFO', 'Bridge resumed');

    if (this.callbacks.sendStatus) {
      this.callbacks.sendStatus('running');
    }
  }

  /**
   * Start polling for tasks
   */
  startPolling() {
    this.pollInterval = setInterval(async () => {
      if (!this.isRunning || this.isPaused || this.currentTask) {
        return;
      }

      await this.checkForPendingTasks();
    }, 3000);
  }

  /**
   * Stop polling
   */
  stopPolling() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  /**
   * Check for pending tasks in lux_tasks table
   */
  async checkForPendingTasks() {
    if (!this.supabase) return;

    try {
      const { data: tasks, error } = await this.supabase
        .from('lux_tasks')
        .select('*')
        .eq('status', 'pending')
        .order('created_at', { ascending: true })
        .limit(1);

      if (error) {
        this.log('ERROR', `Error polling tasks: ${error.message}`);
        return;
      }

      if (tasks && tasks.length > 0) {
        await this.handleNewTask(tasks[0]);
      }
    } catch (e) {
      this.log('ERROR', `Poll error: ${e.message}`);
    }
  }

  /**
   * Handle new task from Supabase
   */
  async handleNewTask(task) {
    if (!this.isRunning || this.isPaused) {
      this.log('WARN', 'Bridge not running or paused, skipping task');
      return;
    }

    if (this.currentTask) {
      this.log('WARN', 'Already executing a task, skipping');
      return;
    }

    // Check Tasker Service before processing
    if (!this.taskerStatus || !this.taskerStatus.available) {
      await this.checkTaskerService();
    }

    this.currentTask = task;
    
    // Determine provider: use computer_use_provider if set, otherwise infer from lux_mode
    const provider = task.computer_use_provider || 'lux';
    const luxMode = task.lux_mode || 'actor';
    
    this.log('INFO', `New task: ${task.task_description}`);
    this.log('INFO', `Provider: ${provider} | Mode: ${luxMode} | Model: ${task.lux_model || 'default'}`);

    if (this.callbacks.sendTaskUpdate) {
      this.callbacks.sendTaskUpdate(task);
    }

    try {
      // Update status to running
      await this.updateTaskStatus(task.id, 'running');

      let success = false;

      // Route based on provider
      if (provider === 'gemini') {
        // ================================================
        // GEMINI EXECUTION (Playwright - no window minimize needed)
        // ================================================
        success = await this.executeGeminiMode(task);
      } else {
        // ================================================
        // LUX EXECUTION (PyAutoGUI - needs window minimize)
        // ================================================
        
        // Minimize window before Lux execution
        if (this.callbacks.minimizeWindow) {
          this.log('INFO', 'Minimizing window for Lux execution...');
          this.callbacks.minimizeWindow();
          await new Promise(resolve => setTimeout(resolve, 500));
        }

        // Route based on lux_mode
        switch (luxMode) {
          case 'tasker':
            success = await this.executeTaskerMode(task);
            break;
          case 'thinker':
            success = await this.executeThinkerMode(task);
            break;
          case 'actor':
          default:
            success = await this.executeActorMode(task);
            break;
        }

        // Restore window after Lux execution
        if (this.callbacks.restoreWindow) {
          this.log('INFO', 'Restoring window after Lux execution...');
          this.callbacks.restoreWindow();
        }
      }

      // Update final status
      await this.updateTaskStatus(task.id, success ? 'completed' : 'failed', {
        progress: 100
      });

      this.log(success ? 'INFO' : 'ERROR', `Task ${success ? 'completed successfully' : 'failed'}`);

    } catch (error) {
      this.log('ERROR', `Task execution failed: ${error.message}`);
      await this.updateTaskStatus(task.id, 'failed', {
        error_message: error.message
      });

      // Restore window if Lux was running
      if (task.computer_use_provider !== 'gemini' && this.callbacks.restoreWindow) {
        this.callbacks.restoreWindow();
      }
    } finally {
      this.currentTask = null;
      if (this.callbacks.sendTaskUpdate) {
        this.callbacks.sendTaskUpdate(null);
      }
    }
  }

  /**
   * Update task status in database
   */
  async updateTaskStatus(taskId, status, additionalData = {}) {
    if (!this.supabase) return;

    const updateData = {
      status,
      ...additionalData
    };

    if (status === 'running') {
      updateData.started_at = new Date().toISOString();
    } else if (status === 'completed' || status === 'failed') {
      updateData.completed_at = new Date().toISOString();
    }

    try {
      await this.supabase
        .from('lux_tasks')
        .update(updateData)
        .eq('id', taskId);
    } catch (e) {
      this.log('ERROR', `Failed to update task status: ${e.message}`);
    }
  }

  /**
   * Execute task with GEMINI (Playwright browser)
   */
  async executeGeminiMode(task) {
    this.log('INFO', '🔵 [Gemini Mode] Executing with Playwright browser...');

    // Check availability
    if (!this.taskerStatus?.geminiAvailable) {
      throw new Error('Gemini not available on tasker service');
    }
    if (!this.taskerStatus?.playwrightAvailable) {
      throw new Error('Playwright not available. Run: pip install playwright && playwright install chromium');
    }

    const apiKey = task.gemini_api_key || this.config.geminiApiKey;
    if (!apiKey) {
      throw new Error('Gemini API key not configured');
    }

    const params = {
      apiKey: apiKey,
      instruction: task.task_description,
      maxSteps: task.max_steps || 15,
      startUrl: task.start_url,
      headless: task.headless || false,
      highlightMouse: task.highlight_mouse || false
    };

    this.log('INFO', `[Gemini] Max Steps: ${params.maxSteps}`);
    if (params.startUrl) {
      this.log('INFO', `[Gemini] Start URL: ${params.startUrl}`);
    }
    this.log('INFO', `[Gemini] Headless: ${params.headless}, Highlight: ${params.highlightMouse}`);

    const result = await luxClient.executeGeminiTask(params);

    return result.success;
  }

  /**
   * Execute task in ACTOR mode (simple, direct execution)
   */
  async executeActorMode(task) {
    this.log('INFO', '🟢 [Actor Mode] Executing direct task...');

    if (!this.taskerStatus?.oagiAvailable) {
      throw new Error('OAGI/Lux not available on tasker service');
    }

    const params = {
      instruction: task.task_description,
      model: task.lux_model || 'lux-actor-1',
      maxSteps: task.max_steps || 20,
      temperature: task.temperature || 0.1,
      startUrl: task.start_url
    };

    this.log('INFO', `[Actor] Model: ${params.model}, Max Steps: ${params.maxSteps}`);
    if (params.startUrl) {
      this.log('INFO', `[Actor] Start URL: ${params.startUrl}`);
    }

    const result = await luxClient.executeDirectTask(params);

    return result.success;
  }

  /**
   * Execute task in THINKER mode (complex, multi-step reasoning)
   */
  async executeThinkerMode(task) {
    this.log('INFO', '🟣 [Thinker Mode] Executing complex task...');

    if (!this.taskerStatus?.oagiAvailable) {
      throw new Error('OAGI/Lux not available on tasker service');
    }

    const params = {
      instruction: task.task_description,
      model: task.lux_model || 'lux-thinker-1',
      maxSteps: task.max_steps || 100,
      temperature: task.temperature || 0.1,
      startUrl: task.start_url
    };

    this.log('INFO', `[Thinker] Model: ${params.model}, Max Steps: ${params.maxSteps}`);
    if (params.startUrl) {
      this.log('INFO', `[Thinker] Start URL: ${params.startUrl}`);
    }

    const result = await luxClient.executeDirectTask(params);

    return result.success;
  }

  /**
   * Execute task in TASKER mode (step-by-step with todos)
   */
  async executeTaskerMode(task) {
    this.log('INFO', '🔷 [Tasker Mode] Executing with todos...');

    if (!this.taskerStatus?.oagiAvailable) {
      throw new Error('OAGI/Lux not available on tasker service');
    }

    // Load todos from database
    let todos = [];
    if (this.supabase) {
      const { data, error } = await this.supabase
        .from('lux_todos')
        .select('*')
        .eq('task_id', task.id)
        .order('todo_index', { ascending: true });

      if (!error && data) {
        todos = data;
      }
    }

    if (todos.length === 0) {
      this.log('WARN', '[Tasker] No todos found - falling back to Actor mode');
      return await this.executeActorMode(task);
    }

    this.log('INFO', `[Tasker] Loaded ${todos.length} todos`);

    // Log each todo
    todos.forEach((todo, i) => {
      this.log('INFO', `  ${i + 1}. ${todo.todo_description}`);
    });

    // Send step update
    if (this.callbacks.sendStepUpdate) {
      this.callbacks.sendStepUpdate({
        total: todos.length,
        current: 0,
        description: 'Starting...'
      });
    }

    // Convert todos to array of strings
    const todosArray = todos.map(t => t.todo_description);

    const params = {
      taskDescription: task.task_description,
      todos: todosArray,
      model: task.lux_model || 'lux-actor-1',
      maxSteps: task.max_steps || 60,
      reflectionInterval: 20,
      temperature: task.temperature || 0.1,
      startUrl: task.start_url,
      onTodoStart: async (index, todo) => {
        this.log('INFO', `[Tasker] Starting todo ${index + 1}: ${todo}`);
        if (todos[index] && this.supabase) {
          await this.supabase
            .from('lux_todos')
            .update({ status: 'running', started_at: new Date().toISOString() })
            .eq('id', todos[index].id);
        }
        if (this.callbacks.sendStepUpdate) {
          this.callbacks.sendStepUpdate({
            total: todos.length,
            current: index + 1,
            description: todo
          });
        }
      },
      onTodoComplete: async (index, success, result) => {
        this.log('INFO', `[Tasker] Todo ${index + 1} ${success ? 'completed' : 'failed'}`);
        if (todos[index] && this.supabase) {
          await this.supabase
            .from('lux_todos')
            .update({
              status: success ? 'completed' : 'failed',
              completed_at: new Date().toISOString(),
              result: result?.message
            })
            .eq('id', todos[index].id);
        }
        // Update progress
        const progress = Math.round(((index + 1) / todos.length) * 100);
        await this.updateTaskStatus(task.id, 'running', { progress });
      }
    };

    this.log('INFO', '[Tasker] Delegating to Tasker Service...');
    if (params.startUrl) {
      this.log('INFO', `[Tasker] Start URL: ${params.startUrl}`);
    }

    const result = await luxClient.executeTaskerTask(params);

    this.log('INFO', `[Tasker] Completed ${result.completedTodos}/${result.totalTodos} todos`);

    return result.success;
  }

  /**
   * Cancel a task
   */
  async cancelTask(taskId) {
    this.log('INFO', `Cancelling task: ${taskId}`);

    if (this.currentTask && this.currentTask.id === taskId) {
      await luxClient.stopTask();
      this.currentTask = null;

      // Restore window if it was minimized (only for Lux tasks)
      if (this.callbacks.restoreWindow) {
        this.callbacks.restoreWindow();
      }
    }

    if (this.supabase) {
      await this.supabase
        .from('lux_tasks')
        .update({ status: 'failed', error_message: 'Cancelled by user' })
        .eq('id', taskId);
    }
  }

  /**
   * Retry a step/todo
   */
  async retryStep(stepId) {
    this.log('INFO', `Retrying step: ${stepId}`);

    if (this.supabase) {
      const { data } = await this.supabase
        .from('lux_todos')
        .update({ status: 'pending', retry_count: 0 })
        .eq('id', stepId)
        .select()
        .single();

      return data;
    }
    return null;
  }

  /**
   * Get bridge state
   */
  getState() {
    return {
      isRunning: this.isRunning,
      isPaused: this.isPaused,
      hasCurrentTask: this.currentTask !== null,
      currentTask: this.currentTask
    };
  }
}

// Export singleton
module.exports = new Bridge();
