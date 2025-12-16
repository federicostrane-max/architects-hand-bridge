/**
 * Architect's Hand Bridge - Main Entry Point
 * Routes tasks to appropriate executor based on lux_mode
 */

const supabase = require('./supabase-client');
const luxClient = require('./lux-client');

class Bridge {
  constructor() {
    this.isRunning = false;
    this.isPaused = false;
    this.currentTask = null;
    this.pollInterval = null;
    this.onLog = null;
    this.onTaskUpdate = null;
    this.onStepUpdate = null;
  }

  /**
   * Set log callback
   */
  setLogCallback(callback) {
    this.onLog = callback;
  }

  /**
   * Set task update callback
   */
  setTaskUpdateCallback(callback) {
    this.onTaskUpdate = callback;
  }

  /**
   * Set step update callback
   */
  setStepUpdateCallback(callback) {
    this.onStepUpdate = callback;
  }

  /**
   * Log message
   */
  log(message, level = 'INFO') {
    const timestamp = new Date().toLocaleTimeString();
    const logMessage = `[${timestamp}] ${message}`;
    console.log(`[Bridge] [${level}] ${message}`);
    if (this.onLog) {
      this.onLog(logMessage, level);
    }
  }

  /**
   * Initialize the bridge
   */
  async initialize(config) {
    this.log('Initializing bridge...');

    // Initialize Supabase
    if (config.supabaseUrl && config.supabaseKey) {
      supabase.initialize(config.supabaseUrl, config.supabaseKey);
      this.log('Supabase configured');
    }

    // Initialize Lux client
    if (config.luxApiKey) {
      luxClient.initialize(config.luxApiKey);
      this.log('Lux API configured');
    }

    return true;
  }

  /**
   * Start the bridge
   */
  async start() {
    if (this.isRunning) {
      this.log('Bridge already running', 'WARN');
      return;
    }

    this.isRunning = true;
    this.isPaused = false;
    this.log('Bridge started successfully', 'SUCCESS');

    // Check Tasker Service availability
    this.log('Checking Tasker Service...');
    const taskerStatus = await luxClient.checkTaskerService();
    if (taskerStatus.available) {
      this.log('Tasker Service available - OAGI: ' + taskerStatus.oagiAvailable, 'SUCCESS');
    } else {
      this.log('Tasker Service not available - tasks will wait', 'WARN');
    }

    // Subscribe to realtime updates
    supabase.subscribeToTasks(
      (task) => this.handleNewTask(task),
      (todoPayload) => this.handleTodoChange(todoPayload),
      (task) => this.handleTaskStatusChange(task)
    );
    this.log('Connected to Supabase - listening for tasks');

    // Start polling as fallback
    this.startPolling();
    this.log('Starting task polling (every 3 seconds)...');
  }

  /**
   * Stop the bridge
   */
  stop() {
    this.isRunning = false;
    this.isPaused = false;
    this.stopPolling();
    supabase.unsubscribe();
    this.log('Bridge stopped');
  }

  /**
   * Pause the bridge
   */
  pause() {
    this.isPaused = true;
    this.log('Bridge paused');
  }

  /**
   * Resume the bridge
   */
  resume() {
    this.isPaused = false;
    this.log('Bridge resumed');
  }

  /**
   * Start polling for tasks
   */
  startPolling() {
    this.pollInterval = setInterval(async () => {
      if (!this.isRunning || this.isPaused || this.currentTask) {
        return;
      }

      const tasks = await supabase.pollPendingTasks();
      if (tasks.length > 0) {
        await this.handleNewTask(tasks[0]);
      }
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
   * Handle new task from Supabase
   */
  async handleNewTask(task) {
    if (!this.isRunning || this.isPaused) {
      this.log('Bridge not running or paused, skipping task');
      return;
    }

    if (this.currentTask) {
      this.log('Already executing a task, skipping');
      return;
    }

    // Check Tasker Service before processing
    const taskerStatus = await luxClient.checkTaskerService();
    if (!taskerStatus.available || !taskerStatus.oagiAvailable) {
      this.log('Tasker Service not ready - waiting...', 'WARN');
      return;
    }

    this.currentTask = task;
    this.log(`Found pending task: ${task.task_description}...`);
    this.log(`Mode: ${task.lux_mode || 'actor'} | Model: ${task.lux_model || 'lux-actor-1'}`);

    if (this.onTaskUpdate) {
      this.onTaskUpdate(task);
    }

    try {
      // Update status to running
      await supabase.updateTaskStatus(task.id, 'running');

      // Route based on lux_mode
      let success = false;
      const luxMode = task.lux_mode || 'actor';

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

      // Update final status
      await supabase.updateTaskStatus(task.id, success ? 'completed' : 'failed', {
        progress: 100
      });

      this.log(`Task ${success ? 'completed successfully' : 'failed'}`, success ? 'SUCCESS' : 'ERROR');

    } catch (error) {
      this.log(`Task execution failed: ${error.message}`, 'ERROR');
      await supabase.updateTaskStatus(task.id, 'failed', {
        error_message: error.message
      });
    } finally {
      this.currentTask = null;
    }
  }

  /**
   * Execute task in ACTOR mode (simple, direct execution)
   */
  async executeActorMode(task) {
    this.log('[Actor Mode] Executing direct task...');

    const params = {
      instruction: task.task_description,
      model: task.lux_model || 'lux-actor-1',
      maxSteps: task.max_steps || 20,
      temperature: task.temperature || 0.1,
      startUrl: task.start_url
    };

    this.log(`[Actor] Instruction: ${params.instruction}`);
    this.log(`[Actor] Model: ${params.model}, Max Steps: ${params.maxSteps}`);

    const result = await luxClient.executeDirectTask(params);

    // Save result
    await supabase.updateTaskStatus(task.id, result.success ? 'completed' : 'failed', {
      result: result.message,
      execution_summary: result.summary,
      error_message: result.error
    });

    return result.success;
  }

  /**
   * Execute task in THINKER mode (complex, multi-step reasoning)
   */
  async executeThinkerMode(task) {
    this.log('[Thinker Mode] Executing complex task...');

    const params = {
      instruction: task.task_description,
      model: task.lux_model || 'lux-thinker-1',
      maxSteps: task.max_steps || 100,
      temperature: task.temperature || 0.1,
      startUrl: task.start_url
    };

    this.log(`[Thinker] Instruction: ${params.instruction}`);
    this.log(`[Thinker] Model: ${params.model}, Max Steps: ${params.maxSteps}`);

    const result = await luxClient.executeDirectTask(params);

    // Save result
    await supabase.updateTaskStatus(task.id, result.success ? 'completed' : 'failed', {
      result: result.message,
      execution_summary: result.summary,
      error_message: result.error
    });

    return result.success;
  }

  /**
   * Execute task in TASKER mode (step-by-step with todos)
   */
  async executeTaskerMode(task) {
    this.log('[Tasker Mode] Executing with todos...');

    // Load todos from database
    const todos = await supabase.getTodosForTask(task.id);

    if (!todos || todos.length === 0) {
      this.log('[Tasker] No todos found - falling back to Actor mode', 'WARN');
      return await this.executeActorMode(task);
    }

    this.log(`[Tasker] Loaded ${todos.length} todos`);

    // Log each todo
    todos.forEach((todo, i) => {
      this.log(`  ${i + 1}. ${todo.todo_description}`);
    });

    if (this.onStepUpdate) {
      this.onStepUpdate({
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
      todoRecords: todos, // Include full records for status updates
      model: task.lux_model || 'lux-actor-1',
      maxSteps: task.max_steps || 60,
      reflectionInterval: 20,
      temperature: task.temperature || 0.1,
      startUrl: task.start_url,
      onTodoStart: async (index, todo) => {
        this.log(`[Tasker] Starting todo ${index + 1}: ${todo}`);
        if (todos[index]) {
          await supabase.updateTodoStatus(todos[index].id, 'running');
        }
        if (this.onStepUpdate) {
          this.onStepUpdate({
            total: todos.length,
            current: index + 1,
            description: todo
          });
        }
      },
      onTodoComplete: async (index, success, result) => {
        this.log(`[Tasker] Todo ${index + 1} ${success ? 'completed' : 'failed'}`);
        if (todos[index]) {
          await supabase.updateTodoStatus(todos[index].id, success ? 'completed' : 'failed', {
            result: result?.message,
            lux_actions: result?.actions
          });
        }
        // Update progress
        const progress = Math.round(((index + 1) / todos.length) * 100);
        await supabase.updateTaskProgress(task.id, progress);
      }
    };

    this.log('[Tasker] Delegating to Tasker Service...');
    const result = await luxClient.executeTaskerTask(params);

    this.log(`[Tasker] Result: ${result.success ? 'SUCCESS' : 'FAILED'}`);
    this.log(`[Tasker] Completed ${result.completedTodos}/${result.totalTodos} todos`);

    return result.success;
  }

  /**
   * Handle todo change from realtime subscription
   */
  handleTodoChange(payload) {
    // This can be used for UI updates if needed
    console.log('[Bridge] Todo change:', payload.eventType);
  }

  /**
   * Handle task status change from realtime subscription
   */
  handleTaskStatusChange(task) {
    // This can be used for UI updates
    if (this.onTaskUpdate) {
      this.onTaskUpdate(task);
    }
  }

  /**
   * Get bridge status
   */
  getStatus() {
    return {
      isRunning: this.isRunning,
      isPaused: this.isPaused,
      hasCurrentTask: this.currentTask !== null,
      currentTask: this.currentTask
    };
  }

  /**
   * Get bridge state (alias for getStatus)
   */
  getState() {
    return this.getStatus();
  }
}

// Export singleton
module.exports = new Bridge();
