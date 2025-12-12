const { createClient } = require('@supabase/supabase-js');

class SupabaseClient {
  constructor() {
    this.client = null;
    this.subscription = null;
    this.onStepCallback = null;
    this.onTaskCallback = null;
    this.taskSecret = null;
  }

  connect(url, anonKey, taskSecret = null) {
    if (!url || !anonKey) {
      throw new Error('Supabase URL and Anon Key are required');
    }

    const options = {
      auth: {
        persistSession: false,
        autoRefreshToken: false
      }
    };

    if (taskSecret) {
      options.global = {
        headers: {
          'x-task-secret': taskSecret
        }
      };
      this.taskSecret = taskSecret;
    }

    this.client = createClient(url, anonKey, options);

    return this.client;
  }

  setTaskSecret(taskSecret) {
    this.taskSecret = taskSecret;
  }

  async testConnection() {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    const { data, error } = await this.client
      .from('browser_tasks')
      .select('id')
      .limit(1);

    if (error) {
      throw new Error(`Connection test failed: ${error.message}`);
    }

    return true;
  }

  subscribeToSteps(onStep) {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    this.onStepCallback = onStep;

    this.subscription = this.client
      .channel('browser_steps_channel')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'browser_steps',
          filter: 'status=eq.pending'
        },
        (payload) => {
          console.log('Step change received:', payload);
          if (payload.eventType === 'INSERT' && this.onStepCallback) {
            this.onStepCallback(payload.new);
          }
        }
      )
      .subscribe((status) => {
        console.log('Subscription status:', status);
      });

    return this.subscription;
  }

  subscribeToTasks(onTask) {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    this.onTaskCallback = onTask;

    this.client
      .channel('browser_tasks_channel')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'browser_tasks'
        },
        (payload) => {
          console.log('Task change received:', payload);
          if (this.onTaskCallback) {
            this.onTaskCallback(payload.new, payload.eventType);
          }
        }
      )
      .subscribe();
  }

  /**
   * Get next pending TASK (TaskerAgent mode)
   * Returns a complete task to be executed with all todos
   */
  async getNextPendingTask() {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    // First check for running tasks
    const { data: runningTasks, error: runningError } = await this.client
      .from('browser_tasks')
      .select('*')
      .eq('status', 'running')
      .order('created_at', { ascending: true })
      .limit(1);

    if (runningError) {
      throw new Error(`Failed to get running tasks: ${runningError.message}`);
    }

    if (runningTasks && runningTasks.length > 0) {
      return runningTasks[0];
    }

    // Then check for pending tasks
    const { data: pendingTasks, error: pendingError } = await this.client
      .from('browser_tasks')
      .select('*')
      .eq('status', 'pending')
      .order('created_at', { ascending: true })
      .limit(1);

    if (pendingError) {
      throw new Error(`Failed to get pending tasks: ${pendingError.message}`);
    }

    if (!pendingTasks || pendingTasks.length === 0) {
      return null;
    }

    return pendingTasks[0];
  }

  /**
   * Get all steps for a task (for building todos array)
   */
  async getStepsForTask(taskId) {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    const { data, error } = await this.client
      .from('browser_steps')
      .select('*')
      .eq('task_id', taskId)
      .order('step_number', { ascending: true });

    if (error) {
      console.error('[Supabase] Error fetching steps:', error);
      return [];
    }

    return data || [];
  }

  // Keep for backwards compatibility
  async getNextPendingStep() {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    const { data: tasks, error: taskError } = await this.client
      .from('browser_tasks')
      .select('id')
      .eq('status', 'running')
      .order('created_at', { ascending: true })
      .limit(1);

    if (taskError) {
      throw new Error(`Failed to get running tasks: ${taskError.message}`);
    }

    if (!tasks || tasks.length === 0) {
      const { data: pendingTasks, error: pendingError } = await this.client
        .from('browser_tasks')
        .select('id')
        .eq('status', 'pending')
        .order('created_at', { ascending: true })
        .limit(1);

      if (pendingError || !pendingTasks || pendingTasks.length === 0) {
        return null;
      }

      await this.updateTask(pendingTasks[0].id, { 
        status: 'running', 
        started_at: new Date().toISOString() 
      });

      return this.getNextPendingStep();
    }

    const { data: steps, error: stepError } = await this.client
      .from('browser_steps')
      .select('*')
      .eq('task_id', tasks[0].id)
      .eq('status', 'pending')
      .order('step_number', { ascending: true })
      .limit(1);

    if (stepError) {
      throw new Error(`Failed to get pending step: ${stepError.message}`);
    }

    if (!steps || steps.length === 0) {
      return null;
    }

    return steps[0];
  }

  async getTask(taskId) {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    const { data, error } = await this.client
      .from('browser_tasks')
      .select('*')
      .eq('id', taskId)
      .single();

    if (error) {
      throw new Error(`Failed to get task: ${error.message}`);
    }

    return data;
  }

  async updateStep(stepId, updates) {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    const { data, error } = await this.client
      .from('browser_steps')
      .update(updates)
      .eq('id', stepId)
      .select()
      .single();

    if (error) {
      throw new Error(`Failed to update step: ${error.message}`);
    }

    return data;
  }

  async markStepRunning(stepId) {
    return this.updateStep(stepId, {
      status: 'running',
      started_at: new Date().toISOString()
    });
  }

  async markStepCompleted(stepId, screenshotAfter, luxFeedback, luxActions) {
    return this.updateStep(stepId, {
      status: 'completed',
      completed_at: new Date().toISOString(),
      screenshot_after: screenshotAfter,
      lux_feedback: luxFeedback,
      lux_actions: luxActions,
      verification_status: 'pending'
    });
  }

  async markStepFailed(stepId, errorMessage, screenshotAfter = null) {
    return this.updateStep(stepId, {
      status: 'failed',
      error_message: errorMessage,
      screenshot_after: screenshotAfter
    });
  }

  async incrementRetryCount(stepId) {
    const { data: step } = await this.client
      .from('browser_steps')
      .select('retry_count, max_retries')
      .eq('id', stepId)
      .single();

    if (step && step.retry_count < step.max_retries) {
      return this.updateStep(stepId, {
        status: 'pending',
        retry_count: step.retry_count + 1,
        error_message: null
      });
    }

    return null;
  }

  async updateTask(taskId, updates) {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    const { data, error } = await this.client
      .from('browser_tasks')
      .update(updates)
      .eq('id', taskId)
      .select()
      .single();

    if (error) {
      throw new Error(`Failed to update task: ${error.message}`);
    }

    return data;
  }

  async markTaskFailed(taskId, errorMessage) {
    return this.updateTask(taskId, {
      status: 'failed',
      error_message: errorMessage,
      completed_at: new Date().toISOString()
    });
  }

  async uploadScreenshot(taskId, stepNumber, screenshotBuffer, type = 'after') {
    if (!this.client) {
      throw new Error('Client not initialized');
    }

    const fileName = `${taskId}/${stepNumber}_${type}_${Date.now()}.png`;
    
    const { data, error } = await this.client.storage
      .from('screenshots')
      .upload(fileName, screenshotBuffer, {
        contentType: 'image/png',
        upsert: true
      });

    if (error) {
      console.warn('Screenshot upload failed, using base64:', error.message);
      return `data:image/png;base64,${screenshotBuffer.toString('base64')}`;
    }

    const { data: urlData } = this.client.storage
      .from('screenshots')
      .getPublicUrl(fileName);

    return urlData.publicUrl;
  }

  disconnect() {
    if (this.subscription) {
      this.subscription.unsubscribe();
      this.subscription = null;
    }
    this.client = null;
    this.taskSecret = null;
  }
}

module.exports = new SupabaseClient();
