const supabase = require('./supabase-client');
const lux = require('./lux-client');
const browser = require('./browser-controller');

class Bridge {
  constructor() {
    this.isRunning = false;
    this.isPaused = false;
    this.currentTask = null;
    this.currentStep = null;
    this.pollInterval = null;
    this.sendLog = null;
    this.sendStatus = null;
    this.sendTaskUpdate = null;
    this.sendStepUpdate = null;
    this.sendScreenshot = null;
  }

  // Set callbacks for UI updates
  setCallbacks({ sendLog, sendStatus, sendTaskUpdate, sendStepUpdate, sendScreenshot }) {
    this.sendLog = sendLog || console.log;
    this.sendStatus = sendStatus || (() => {});
    this.sendTaskUpdate = sendTaskUpdate || (() => {});
    this.sendStepUpdate = sendStepUpdate || (() => {});
    this.sendScreenshot = sendScreenshot || (() => {});
  }

  // Log helper
  log(level, message) {
    console.log(`[Bridge] [${level.toUpperCase()}] ${message}`);
    if (this.sendLog) {
      this.sendLog(level, message);
    }
  }

  // Start the bridge
  async start(config) {
    if (this.isRunning) {
      this.log('warn', 'Bridge is already running');
      return;
    }

    this.log('info', 'Starting bridge...');
    this.sendStatus('connecting');

    try {
      // Validate config
      if (!config.supabaseUrl || !config.supabaseAnonKey) {
        throw new Error('Supabase configuration is missing');
      }
      if (!config.openAgiApiKey) {
        throw new Error('OpenAGI API key is missing');
      }

      // Connect to Supabase (with optional task secret for RLS)
      this.log('info', 'Connecting to Supabase...');
      supabase.connect(config.supabaseUrl, config.supabaseAnonKey, config.taskSecret);
      
      if (config.taskSecret) {
        this.log('info', 'Task secret configured for RLS authentication');
      } else {
        this.log('warn', 'No task secret configured - will have limited access until task is assigned');
      }
      
      // Test connection (might fail if no task secret - that's ok)
      try {
        await supabase.testConnection();
        this.log('success', 'Connected to Supabase');
      } catch (connError) {
        this.log('warn', `Supabase connection test: ${connError.message} - This is OK if no task is assigned yet`);
      }

      // Set Lux API key
      lux.setApiKey(config.openAgiApiKey);
      this.log('info', 'Lux API configured');

      // Launch browser
      this.log('info', 'Launching browser...');
      await browser.launch();
      this.log('success', 'Browser launched');

      // Mark as running BEFORE setting up subscriptions
      // This ensures the UI shows "connected" even if Realtime fails
      this.isRunning = true;
      this.sendStatus('connected');
      this.log('success', 'Bridge started successfully');

      // Setup realtime subscriptions (non-blocking, failures are OK)
      this.setupRealtimeSubscriptions();

      // Start polling for tasks (this is the reliable method)
      this.startPolling();

    } catch (error) {
      this.log('error', `Failed to start: ${error.message}`);
      this.sendStatus('disconnected');
      await this.cleanup();
      throw error;
    }
  }

  // Setup realtime subscriptions (best-effort, polling is fallback)
  setupRealtimeSubscriptions() {
    try {
      // Subscribe to new steps
      supabase.subscribeToSteps((step) => {
        this.log('info', `New step received via Realtime: ${step.instruction?.substring(0, 50)}...`);
        if (!this.isPaused) {
          this.processStep(step);
        }
      });

      // Subscribe to task updates
      supabase.subscribeToTasks((task, eventType) => {
        this.log('info', `Task ${eventType} via Realtime: ${task.task_description?.substring(0, 50)}...`);
        this.sendTaskUpdate(task);
      });

      this.log('info', 'Realtime subscriptions setup (polling active as fallback)');
    } catch (error) {
      // Realtime is optional - polling will handle everything
      this.log('warn', `Realtime setup failed (using polling only): ${error.message}`);
    }
  }

  // Start polling for pending steps
  startPolling() {
    this.log('info', 'Starting task polling (every 2 seconds)...');
    
    this.pollInterval = setInterval(async () => {
      if (this.isPaused || this.currentStep) {
        return; // Skip if paused or already processing a step
      }

      try {
        const step = await supabase.getNextPendingStep();
        if (step) {
          this.log('info', `Found pending step via polling: ${step.instruction?.substring(0, 50)}...`);
          await this.processStep(step);
        }
      } catch (error) {
        // Don't spam logs for expected errors (no tasks)
        if (!error.message.includes('no rows') && !error.message.includes('not found')) {
          this.log('error', `Polling error: ${error.message}`);
        }
      }
    }, 2000); // Poll every 2 seconds
  }

  // Process a step
  async processStep(step) {
    if (this.currentStep) {
      this.log('warn', 'Already processing a step, queueing...');
      return;
    }

    this.currentStep = step;
    this.sendStepUpdate(step);

    try {
      // Load task info if not already loaded
      const isNewTask = !this.currentTask || this.currentTask.id !== step.task_id;
      
      if (isNewTask) {
        this.currentTask = await supabase.getTask(step.task_id);
        this.sendTaskUpdate(this.currentTask);
        
        // Reset Lux session for new task
        lux.resetSession();
        
        // Navigate to start_url if provided
        if (this.currentTask.start_url) {
          this.log('info', `Navigating to start URL: ${this.currentTask.start_url}`);
          await browser.navigate(this.currentTask.start_url);
          await browser.wait(2000); // Wait for page to load
          this.log('success', 'Navigation complete');
          
          // Take screenshot after navigation
          const navScreenshot = await browser.screenshotBase64();
          this.sendScreenshot(`data:image/png;base64,${navScreenshot}`);
        } else {
          this.log('warn', 'No start_url provided for task - browser may be on blank page');
        }
      }

      this.log('info', `Processing step ${step.step_number}: ${step.instruction.substring(0, 100)}...`);

      // Mark step as running
      await supabase.markStepRunning(step.id);
      step.status = 'running';
      this.sendStepUpdate(step);

      // Take screenshot before action
      const screenshotBefore = await browser.screenshotBase64();
      
      // Update UI with current screenshot
      this.sendScreenshot(`data:image/png;base64,${screenshotBefore}`);

      // Save screenshot before
      const beforeUrl = await supabase.uploadScreenshot(
        step.task_id, 
        step.step_number, 
        Buffer.from(screenshotBefore, 'base64'), 
        'before'
      );
      await supabase.updateStep(step.id, { screenshot_before: beforeUrl });

      // Send to Lux for action
      this.log('info', 'Sending to Lux for analysis...');
      const luxResult = await lux.executeStep(screenshotBefore, step.instruction, step.instruction_context);

      this.log('info', `Lux response: ${luxResult.status} - ${luxResult.feedback || 'No feedback'}`);

      // Execute actions in browser
      if (luxResult.actions && luxResult.actions.length > 0) {
        this.log('info', `Executing ${luxResult.actions.length} actions...`);
        
        for (const action of luxResult.actions) {
          if (this.isPaused) {
            this.log('warn', 'Paused during action execution');
            break;
          }

          if (action.type === 'done' || action.type === 'complete') {
            this.log('info', 'Step marked as done by Lux');
            break;
          }

          this.log('info', `Executing: ${action.type}`);
          await browser.executeAction(action);
        }
      } else {
        this.log('warn', 'No actions received from Lux');
      }

      // Take screenshot after actions
      await browser.wait(500); // Wait for page to settle
      const screenshotAfter = await browser.screenshotBase64();
      this.sendScreenshot(`data:image/png;base64,${screenshotAfter}`);

      // Upload screenshot after
      const afterUrl = await supabase.uploadScreenshot(
        step.task_id, 
        step.step_number, 
        Buffer.from(screenshotAfter, 'base64'), 
        'after'
      );

      // Mark step as completed
      await supabase.markStepCompleted(
        step.id,
        afterUrl,
        luxResult.raw,
        luxResult.actions
      );

      this.log('success', `Step ${step.step_number} completed`);

      // Update UI
      step.status = 'completed';
      step.screenshot_after = afterUrl;
      this.sendStepUpdate(step);

      // Refresh task to get updated progress
      this.currentTask = await supabase.getTask(step.task_id);
      this.sendTaskUpdate(this.currentTask);

    } catch (error) {
      this.log('error', `Step failed: ${error.message}`);

      // Take error screenshot
      let errorScreenshot = null;
      try {
        const screenshot = await browser.screenshotBase64();
        errorScreenshot = await supabase.uploadScreenshot(
          step.task_id, 
          step.step_number, 
          Buffer.from(screenshot, 'base64'), 
          'error'
        );
        this.sendScreenshot(`data:image/png;base64,${screenshot}`);
      } catch (e) {
        console.error('Failed to capture error screenshot:', e);
      }

      // Mark step as failed
      await supabase.markStepFailed(step.id, error.message, errorScreenshot);

      // Check if we should retry
      const retried = await supabase.incrementRetryCount(step.id);
      if (retried) {
        this.log('info', `Retrying step (attempt ${retried.retry_count + 1}/${retried.max_retries})`);
      } else {
        this.log('error', 'Max retries reached, marking task as failed');
        await supabase.markTaskFailed(step.task_id, `Step ${step.step_number} failed: ${error.message}`);
      }

      step.status = 'failed';
      step.error_message = error.message;
      this.sendStepUpdate(step);

    } finally {
      this.currentStep = null;
    }
  }

  // Pause the bridge
  pause() {
    this.isPaused = true;
    this.log('info', 'Bridge paused');
  }

  // Resume the bridge
  resume() {
    this.isPaused = false;
    this.log('info', 'Bridge resumed');
  }

  // Stop the bridge
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

  // Cleanup resources
  async cleanup() {
    try {
      await browser.close();
    } catch (e) {
      console.error('Error closing browser:', e);
    }

    try {
      supabase.disconnect();
    } catch (e) {
      console.error('Error disconnecting Supabase:', e);
    }

    this.currentTask = null;
    this.currentStep = null;
  }

  // Cancel current task
  async cancelTask(taskId) {
    this.log('info', `Cancelling task: ${taskId}`);
    
    try {
      await supabase.updateTask(taskId, { 
        status: 'cancelled',
        completed_at: new Date().toISOString()
      });
      
      if (this.currentTask?.id === taskId) {
        this.currentTask = null;
        this.currentStep = null;
        this.sendTaskUpdate(null);
        this.sendStepUpdate(null);
      }
      
      this.log('success', 'Task cancelled');
    } catch (error) {
      this.log('error', `Failed to cancel task: ${error.message}`);
      throw error;
    }
  }

  // Retry a failed step
  async retryStep(stepId) {
    this.log('info', `Retrying step: ${stepId}`);
    
    try {
      const step = await supabase.updateStep(stepId, {
        status: 'pending',
        error_message: null,
        started_at: null,
        completed_at: null
      });
      
      this.log('success', 'Step queued for retry');
      return step;
    } catch (error) {
      this.log('error', `Failed to retry step: ${error.message}`);
      throw error;
    }
  }

  // Get current state
  getState() {
    return {
      isRunning: this.isRunning,
      isPaused: this.isPaused,
      currentTask: this.currentTask,
      currentStep: this.currentStep,
      browserActive: browser.isActive()
    };
  }
}

module.exports = new Bridge();
