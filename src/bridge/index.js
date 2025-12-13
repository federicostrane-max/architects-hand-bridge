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
    this.taskerServiceAvailable = false;
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
      
      try {
        await supabase.testConnection();
        this.log('success', 'Connected to Supabase');
      } catch (connError) {
        this.log('warn', `Supabase connection test: ${connError.message}`);
      }

      // Set Lux API key
      lux.setApiKey(config.openAgiApiKey);
      this.log('info', 'Lux API configured');

      // Check if Python Tasker Service is available
      this.log('info', 'Checking Tasker Service...');
      this.taskerServiceAvailable = await lux.checkService();
      
      if (this.taskerServiceAvailable) {
        this.log('success', 'Tasker Service connected - using TaskerAgent mode');
      } else {
        this.log('warn', 'Tasker Service not available - please start it with start-tasker-service.bat');
        this.log('warn', 'Tasks will wait until Tasker Service is running');
      }

      // Don't launch browser - TaskerAgent uses its own pyautogui
      this.log('info', 'Browser control delegated to Tasker Service');

      this.isRunning = true;
      this.sendStatus('connected');
      this.log('success', 'Bridge started successfully');

      this.startPolling();

    } catch (error) {
      this.log('error', `Failed to start: ${error.message}`);
      this.sendStatus('disconnected');
      await this.cleanup();
      throw error;
    }
  }

  startPolling() {
    this.log('info', 'Starting task polling (every 3 seconds)...');
    
    this.pollInterval = setInterval(async () => {
      if (this.isPaused || this.currentTask) {
        return;
      }

      // Re-check Tasker Service availability periodically
      if (!this.taskerServiceAvailable) {
        this.taskerServiceAvailable = await lux.checkService();
        if (this.taskerServiceAvailable) {
          this.log('success', 'Tasker Service now available');
        }
      }

      try {
        const task = await supabase.getNextPendingTask();
        if (task) {
          this.log('info', `Found pending task: ${task.task_description?.substring(0, 50)}...`);
          
          if (!this.taskerServiceAvailable) {
            this.log('warn', 'Tasker Service not running - waiting...');
            return;
          }
          
          await this.executeTask(task);
        }
      } catch (error) {
        if (!error.message.includes('no rows') && !error.message.includes('not found')) {
          this.log('error', `Polling error: ${error.message}`);
        }
      }
    }, 3000);
  }

  /**
   * Execute a complete task using Python TaskerAgent
   */
  async executeTask(task) {
    this.currentTask = task;
    this.sendTaskUpdate(task);

    try {
      // Get todos from task
      const todos = await this.getTodos(task);
      
      if (!todos || todos.length === 0) {
        throw new Error('No todos found for task');
      }

      this.log('info', `Task has ${todos.length} todos`);
      todos.forEach((todo, i) => this.log('info', `  ${i+1}. ${todo}`));

      // Update task status
      await supabase.updateTask(task.id, { 
        status: 'running',
        started_at: new Date().toISOString()
      });
      task.status = 'running';
      this.sendTaskUpdate(task);

      // Get start URL
      const startUrl = task.start_url || task.task_data?.start_url;

      // Update UI with todos
      todos.forEach((todo, i) => {
        this.sendStepUpdate({
          step_number: i + 1,
          instruction: todo,
          status: 'pending',
          total_steps: todos.length
        });
      });

      // Delegate to Python Tasker Service
      this.log('info', 'Delegating to Tasker Service (TaskerAgent)...');
      
      const result = await lux.executeTaskWithTasker(
        task.task_description,
        todos,
        startUrl
      );

      this.log('info', `Tasker Service result: ${result.success ? 'SUCCESS' : 'FAILED'}`);
      this.log('info', `Completed ${result.completedTodos}/${result.totalTodos} todos`);

      // Update task status based on result
      if (result.success) {
        await supabase.updateTask(task.id, {
          status: 'completed',
          completed_at: new Date().toISOString()
        });
        task.status = 'completed';
        this.log('success', 'Task completed successfully');
      } else {
        await supabase.updateTask(task.id, {
          status: 'failed',
          error_message: result.error || result.message,
          completed_at: new Date().toISOString()
        });
        task.status = 'failed';
        this.log('error', `Task failed: ${result.error || result.message}`);
      }

      this.sendTaskUpdate(task);

      // Update step statuses
      for (let i = 0; i < todos.length; i++) {
        this.sendStepUpdate({
          step_number: i + 1,
          instruction: todos[i],
          status: i < result.completedTodos ? 'completed' : 'pending',
          total_steps: todos.length
        });
      }

    } catch (error) {
      this.log('error', `Task execution failed: ${error.message}`);

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
   * Get todos from task
   */
  async getTodos(task) {
    if (task.todos && Array.isArray(task.todos) && task.todos.length > 0) {
      this.log('info', 'Using todos from task.todos column');
      return task.todos;
    }

    if (task.task_data?.todos && Array.isArray(task.task_data.todos)) {
      this.log('info', 'Using todos from task_data.todos');
      return task.task_data.todos;
    }

    this.log('info', 'Building todos from browser_task_steps table');
    const steps = await supabase.getStepsForTask(task.id);
    if (steps && steps.length > 0) {
      return steps.map(step => step.instruction);
    }

    return [];
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

    // Stop any running task in Tasker Service
    try {
      await lux.stopTask();
    } catch (e) {}

    await this.cleanup();
    
    this.sendStatus('disconnected');
    this.log('info', 'Bridge stopped');
  }

  async cleanup() {
    try {
      // Browser is managed by Tasker Service now
      // await browser.close();
    } catch (e) {}

    try {
      supabase.disconnect();
    } catch (e) {}

    this.currentTask = null;
  }

  async cancelTask(taskId) {
    this.log('info', `Cancelling task: ${taskId}`);
    
    try {
      // Stop task in Tasker Service
      await lux.stopTask();
      
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
      taskerServiceAvailable: this.taskerServiceAvailable
    };
  }
}

module.exports = new Bridge();
