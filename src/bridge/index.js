const supabase = require('./supabase-client');
const lux = require('./lux-client');
const browser = require('./browser-controller');

class Bridge {
  constructor() {
    this.isRunning = false;
    this.isPaused = false;
    this.currentTask = null;
    this.pollInterval = null;
    this.sendLog = null;
    this.sendStatus = null;
    this.sendTaskUpdate = null;
    this.sendStepUpdate = null;
    this.sendScreenshot = null;
  }

  setCallbacks({ sendLog, sendStatus, sendTaskUpdate, sendStepUpdate, sendScreenshot }) {
    this.sendLog = sendLog || console.log;
    this.sendStatus = sendStatus || (() => {});
    this.sendTaskUpdate = sendTaskUpdate || (() => {});
    this.sendStepUpdate = sendStepUpdate || (() => {});
    this.sendScreenshot = sendScreenshot || (() => {});
  }

  log(level, message) {
    console.log(`[Bridge] [${level.toUpperCase()}] ${message}`);
    if (this.sendLog) {
      this.sendLog(level, message);
    }
  }

  async start(config) {
    if (this.isRunning) {
      this.log('warn', 'Bridge is already running');
      return;
    }

    this.log('info', 'Starting bridge...');
    this.sendStatus('connecting');

    try {
      if (!config.supabaseUrl || !config.supabaseAnonKey) {
        throw new Error('Supabase configuration is missing');
      }
      if (!config.openAgiApiKey) {
        throw new Error('OpenAGI API key is missing');
      }

      this.log('info', 'Connecting to Supabase...');
      supabase.connect(config.supabaseUrl, config.supabaseAnonKey, config.taskSecret);
      
      if (config.taskSecret) {
        this.log('info', 'Task secret configured for RLS authentication');
      } else {
        this.log('warn', 'No task secret configured - will have limited access until task is assigned');
      }
      
      try {
        await supabase.testConnection();
        this.log('success', 'Connected to Supabase');
      } catch (connError) {
        this.log('warn', `Supabase connection test: ${connError.message}`);
      }

      lux.setApiKey(config.openAgiApiKey);
      this.log('info', 'Lux API configured');

      this.log('info', 'Launching browser...');
      await browser.launch();
      this.log('success', 'Browser launched');

      this.isRunning = true;
      this.sendStatus('connected');
      this.log('success', 'Bridge started successfully (TaskerAgent mode)');

      this.startPolling();

    } catch (error) {
      this.log('error', `Failed to start: ${error.message}`);
      this.sendStatus('disconnected');
      await this.cleanup();
      throw error;
    }
  }

  startPolling() {
    this.log('info', 'Starting task polling (every 2 seconds)...');
    
    this.pollInterval = setInterval(async () => {
      if (this.isPaused || this.currentTask) {
        return;
      }

      try {
        const task = await supabase.getNextPendingTask();
        if (task) {
          this.log('info', `Found pending task: ${task.task_description?.substring(0, 50)}...`);
          await this.executeTask(task);
        }
      } catch (error) {
        if (!error.message.includes('no rows') && !error.message.includes('not found')) {
          this.log('error', `Polling error: ${error.message}`);
        }
      }
    }, 2000);
  }

  /**
   * Execute a complete task using TaskerAgent strategy
   */
  async executeTask(task) {
    this.currentTask = task;
    this.sendTaskUpdate(task);

    try {
      lux.resetSession();

      await supabase.updateTask(task.id, { 
        status: 'running',
        started_at: new Date().toISOString()
      });
      task.status = 'running';
      this.sendTaskUpdate(task);

      // Get todos from task
      const todos = await this.getTodos(task);
      
      if (!todos || todos.length === 0) {
        throw new Error('No todos found for task');
      }

      this.log('info', `Task has ${todos.length} todos to execute`);

      // Navigate to start_url
      const startUrl = task.start_url || task.task_data?.start_url;
      if (startUrl) {
        this.log('info', `Navigating to: ${startUrl}`);
        await browser.navigate(startUrl);
        await browser.wait(2000);
        
        const navScreenshot = await browser.screenshotBase64();
        this.sendScreenshot(`data:image/png;base64,${navScreenshot}`);
        this.log('success', 'Navigation complete');
      } else {
        this.log('warn', 'No start_url provided for task');
      }

      // Execute todos with Lux
      await this.executeTodosWithLux(task, todos);

      // Mark task as completed
      await supabase.updateTask(task.id, {
        status: 'completed',
        completed_at: new Date().toISOString()
      });
      task.status = 'completed';
      this.sendTaskUpdate(task);
      this.log('success', `Task completed successfully`);

    } catch (error) {
      this.log('error', `Task failed: ${error.message}`);

      try {
        const screenshot = await browser.screenshotBase64();
        this.sendScreenshot(`data:image/png;base64,${screenshot}`);
      } catch (e) {}

      await supabase.updateTask(task.id, {
        status: 'failed',
        error_message: error.message,
        completed_at: new Date().toISOString()
      });
      task.status = 'failed';
      this.sendTaskUpdate(task);

    } finally {
      this.currentTask = null;
    }
  }

  /**
   * Get todos from task - supports multiple sources for backwards compatibility
   */
  async getTodos(task) {
    // 1. Try direct todos column (new format)
    if (task.todos && Array.isArray(task.todos) && task.todos.length > 0) {
      this.log('info', 'Using todos from task.todos column');
      return task.todos;
    }

    // 2. Try task_data.todos (alternative format)
    if (task.task_data?.todos && Array.isArray(task.task_data.todos)) {
      this.log('info', 'Using todos from task_data.todos');
      return task.task_data.todos;
    }

    // 3. Fallback: build from browser_task_steps (current format)
    this.log('info', 'Building todos from browser_task_steps table');
    const steps = await supabase.getStepsForTask(task.id);
    if (steps && steps.length > 0) {
      return steps.map(step => step.instruction);
    }

    return [];
  }

  /**
   * Execute all todos with Lux - TaskerAgent strategy
   */
  async executeTodosWithLux(task, todos) {
    const maxIterations = task.max_steps || 50;
    let iteration = 0;
    let currentTodoIndex = 0;

    while (currentTodoIndex < todos.length && iteration < maxIterations) {
      iteration++;
      
      if (this.isPaused) {
        this.log('warn', 'Task paused');
        break;
      }

      const currentTodo = todos[currentTodoIndex];
      this.log('info', `[${currentTodoIndex + 1}/${todos.length}] ${currentTodo}`);

      // Update UI
      this.sendStepUpdate({
        step_number: currentTodoIndex + 1,
        instruction: currentTodo,
        status: 'running',
        total_steps: todos.length
      });

      // Take screenshot
      const screenshot = await browser.screenshotBase64();
      this.sendScreenshot(`data:image/png;base64,${screenshot}`);

      // Build full context for Lux
      const context = this.buildLuxContext(task, todos, currentTodoIndex);

      // Send to Lux
      this.log('info', 'Sending to Lux for analysis...');
      const luxResult = await lux.executeStep(screenshot, currentTodo, context);

      this.log('info', `Lux response: ${luxResult.status} - ${luxResult.feedback?.substring(0, 100) || 'No feedback'}`);

      // Check if Lux says task is complete
      if (luxResult.raw?.is_complete) {
        this.log('success', 'Lux indicates task is complete');
        break;
      }

      // Execute actions
      if (luxResult.actions && luxResult.actions.length > 0) {
        for (const action of luxResult.actions) {
          if (action.type === 'done' || action.type === 'complete') {
            this.log('info', 'Action indicates step complete');
            break;
          }

          this.log('info', `Executing: ${action.type}`);
          await browser.executeAction(action);
        }

        // Move to next todo
        currentTodoIndex++;
        
        // Update step as completed
        this.sendStepUpdate({
          step_number: currentTodoIndex,
          instruction: currentTodo,
          status: 'completed',
          total_steps: todos.length
        });

        // Update step in database
        await this.updateStepStatus(task.id, currentTodoIndex, 'completed', luxResult);

      } else {
        this.log('warn', 'No actions received from Lux, retrying...');
        await browser.wait(1000);
      }

      await browser.wait(500);
    }

    if (iteration >= maxIterations) {
      throw new Error(`Max iterations (${maxIterations}) reached`);
    }

    this.log('success', `Completed ${currentTodoIndex} of ${todos.length} todos`);
  }

  /**
   * Build context string for Lux Actor mode
   * Keep it simple - Actor works best with direct instructions
   */
  buildLuxContext(task, todos, currentIndex) {
    // For Actor mode, just provide the overall goal - keep it simple
    return task.task_description;
  }

  /**
   * Update step status in database
   */
  async updateStepStatus(taskId, stepNumber, status, luxResult = null) {
    try {
      const steps = await supabase.getStepsForTask(taskId);
      const step = steps.find(s => s.step_number === stepNumber);
      
      if (step) {
        await supabase.updateStep(step.id, {
          status: status,
          completed_at: status === 'completed' ? new Date().toISOString() : null,
          lux_feedback: luxResult?.raw || null,
          lux_actions: luxResult?.actions || null
        });
      }
    } catch (e) {
      console.log('[Bridge] Failed to update step status:', e.message);
    }
  }

  pause() {
    this.isPaused = true;
    this.log('info', 'Bridge paused');
  }

  resume() {
    this.isPaused = false;
    this.log('info', 'Bridge resumed');
  }

  async stop() {
    this.log('info', 'Stopping bridge...');
    
    this.isRunning = false;
    this.isPaused = false;
    
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }

    await this.cleanup();
    
    this.sendStatus('disconnected');
    this.log('info', 'Bridge stopped');
  }

  async cleanup() {
    try {
      await browser.close();
    } catch (e) {}

    try {
      supabase.disconnect();
    } catch (e) {}

    this.currentTask = null;
  }

  async cancelTask(taskId) {
    this.log('info', `Cancelling task: ${taskId}`);
    
    try {
      await supabase.updateTask(taskId, { 
        status: 'cancelled',
        completed_at: new Date().toISOString()
      });
      
      if (this.currentTask?.id === taskId) {
        this.currentTask = null;
        this.sendTaskUpdate(null);
        this.sendStepUpdate(null);
      }
      
      this.log('success', 'Task cancelled');
    } catch (error) {
      this.log('error', `Failed to cancel task: ${error.message}`);
      throw error;
    }
  }

  getState() {
    return {
      isRunning: this.isRunning,
      isPaused: this.isPaused,
      currentTask: this.currentTask,
      browserActive: browser.isActive()
    };
  }
}

module.exports = new Bridge();
