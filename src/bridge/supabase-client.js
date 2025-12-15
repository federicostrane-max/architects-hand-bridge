/**
 * Supabase Client for Architect's Hand Bridge
 * Handles authentication and realtime subscriptions to lux_tasks and lux_todos
 */

const { createClient } = require('@supabase/supabase-js');
const path = require('path');
const fs = require('fs');
const os = require('os');

// Config file path
const CONFIG_DIR = path.join(os.homedir(), 'AppData', 'Roaming', 'architects-hand-bridge');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json');

class SupabaseClient {
  constructor() {
    this.client = null;
    this.user = null;
    this.config = null;
    this.taskChannel = null;
    this.onTaskCallback = null;
    this.onTodoCallback = null;
    this.onStatusChange = null;
  }

  /**
   * Load configuration from file
   */
  loadConfig() {
    try {
      if (fs.existsSync(CONFIG_FILE)) {
        const data = fs.readFileSync(CONFIG_FILE, 'utf8');
        this.config = JSON.parse(data);
        console.log('Config loaded from:', CONFIG_FILE);
        return this.config;
      }
    } catch (error) {
      console.error('Error loading config:', error);
    }
    return null;
  }

  /**
   * Save configuration to file
   */
  saveConfig(config) {
    try {
      if (!fs.existsSync(CONFIG_DIR)) {
        fs.mkdirSync(CONFIG_DIR, { recursive: true });
      }
      fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
      this.config = config;
      console.log('Config saved to:', CONFIG_FILE);
    } catch (error) {
      console.error('Error saving config:', error);
    }
  }

  /**
   * Initialize Supabase client
   */
  initialize(supabaseUrl, supabaseKey) {
    this.client = createClient(supabaseUrl, supabaseKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true
      },
      realtime: {
        params: {
          eventsPerSecond: 10
        }
      }
    });

    // Save to config
    this.saveConfig({
      ...this.config,
      supabaseUrl,
      supabaseKey
    });

    console.log('Supabase client initialized');
    return this.client;
  }

  /**
   * Login with email and password
   */
  async login(email, password) {
    if (!this.client) {
      throw new Error('Supabase client not initialized');
    }

    const { data, error } = await this.client.auth.signInWithPassword({
      email,
      password
    });

    if (error) {
      throw error;
    }

    this.user = data.user;

    // Save credentials
    this.saveConfig({
      ...this.config,
      email,
      lastLogin: new Date().toISOString()
    });

    console.log('Logged in as:', this.user.email);
    return this.user;
  }

  /**
   * Logout
   */
  async logout() {
    if (this.client) {
      await this.client.auth.signOut();
      this.user = null;
      this.unsubscribe();
    }
  }

  /**
   * Get current user
   */
  async getCurrentUser() {
    if (!this.client) return null;

    const { data: { user } } = await this.client.auth.getUser();
    this.user = user;
    return user;
  }

  /**
   * Subscribe to lux_tasks and lux_todos for the current user
   */
  subscribeToTasks(onNewTask, onTodoChange, onStatusChange) {
    if (!this.client || !this.user) {
      console.error('Cannot subscribe: client or user not available');
      return;
    }

    this.onTaskCallback = onNewTask;
    this.onTodoCallback = onTodoChange;
    this.onStatusChange = onStatusChange;

    // Unsubscribe from any existing channel
    this.unsubscribe();

    // Create channel for lux_tasks and lux_todos
    this.taskChannel = this.client
      .channel('lux-realtime')
      // Listen for new tasks (INSERT)
      .on('postgres_changes', {
        event: 'INSERT',
        schema: 'public',
        table: 'lux_tasks',
        filter: `user_id=eq.${this.user.id}`
      }, (payload) => {
        console.log('[Supabase] New lux_task received:', payload.new.id);
        if (this.onTaskCallback) {
          this.onTaskCallback(payload.new);
        }
      })
      // Listen for task updates (UPDATE)
      .on('postgres_changes', {
        event: 'UPDATE',
        schema: 'public',
        table: 'lux_tasks',
        filter: `user_id=eq.${this.user.id}`
      }, (payload) => {
        console.log('[Supabase] lux_task updated:', payload.new.id, 'status:', payload.new.status);
        if (this.onStatusChange) {
          this.onStatusChange(payload.new);
        }
      })
      // Listen for todo changes (INSERT, UPDATE, DELETE)
      .on('postgres_changes', {
        event: '*',
        schema: 'public',
        table: 'lux_todos'
      }, (payload) => {
        console.log('[Supabase] lux_todo change:', payload.eventType, payload.new?.id || payload.old?.id);
        if (this.onTodoCallback) {
          this.onTodoCallback(payload);
        }
      })
      .subscribe((status) => {
        console.log('[Supabase] Realtime subscription status:', status);
      });

    console.log('[Supabase] Subscribed to lux_tasks and lux_todos');
  }

  /**
   * Unsubscribe from realtime
   */
  unsubscribe() {
    if (this.taskChannel) {
      this.client.removeChannel(this.taskChannel);
      this.taskChannel = null;
      console.log('[Supabase] Unsubscribed from realtime');
    }
  }

  /**
   * Poll for pending tasks (fallback if realtime doesn't work)
   */
  async pollPendingTasks() {
    if (!this.client || !this.user) return [];

    const { data, error } = await this.client
      .from('lux_tasks')
      .select('*')
      .eq('user_id', this.user.id)
      .eq('status', 'pending')
      .order('created_at', { ascending: true })
      .limit(1);

    if (error) {
      console.error('[Supabase] Error polling tasks:', error);
      return [];
    }

    return data || [];
  }

  /**
   * Get todos for a task (only for tasker mode)
   */
  async getTodosForTask(taskId) {
    if (!this.client) return [];

    const { data, error } = await this.client
      .from('lux_todos')
      .select('*')
      .eq('task_id', taskId)
      .order('todo_index', { ascending: true });

    if (error) {
      console.error('[Supabase] Error fetching todos:', error);
      return [];
    }

    return data || [];
  }

  /**
   * Update task status
   */
  async updateTaskStatus(taskId, status, additionalData = {}) {
    if (!this.client) return;

    const updateData = {
      status,
      ...additionalData
    };

    // Add timestamps based on status
    if (status === 'running') {
      updateData.started_at = new Date().toISOString();
    } else if (status === 'completed' || status === 'failed') {
      updateData.completed_at = new Date().toISOString();
    }

    const { error } = await this.client
      .from('lux_tasks')
      .update(updateData)
      .eq('id', taskId);

    if (error) {
      console.error('[Supabase] Error updating task status:', error);
      throw error;
    }

    console.log(`[Supabase] Task ${taskId} updated to ${status}`);
  }

  /**
   * Update task progress
   */
  async updateTaskProgress(taskId, progress) {
    if (!this.client) return;

    const { error } = await this.client
      .from('lux_tasks')
      .update({ progress })
      .eq('id', taskId);

    if (error) {
      console.error('[Supabase] Error updating task progress:', error);
    }
  }

  /**
   * Update todo status
   */
  async updateTodoStatus(todoId, status, additionalData = {}) {
    if (!this.client) return;

    const updateData = {
      status,
      ...additionalData
    };

    // Add timestamps based on status
    if (status === 'running') {
      updateData.started_at = new Date().toISOString();
    } else if (status === 'completed' || status === 'failed') {
      updateData.completed_at = new Date().toISOString();
    }

    const { error } = await this.client
      .from('lux_todos')
      .update(updateData)
      .eq('id', todoId);

    if (error) {
      console.error('[Supabase] Error updating todo status:', error);
      throw error;
    }

    console.log(`[Supabase] Todo ${todoId} updated to ${status}`);
  }

  /**
   * Save todo execution results
   */
  async saveTodoResults(todoId, results) {
    if (!this.client) return;

    const { error } = await this.client
      .from('lux_todos')
      .update({
        status: results.success ? 'completed' : 'failed',
        completed_at: new Date().toISOString(),
        result: results.result,
        error_message: results.error,
        screenshot_before: results.screenshotBefore,
        screenshot_after: results.screenshotAfter,
        lux_feedback: results.luxFeedback,
        lux_actions: results.luxActions
      })
      .eq('id', todoId);

    if (error) {
      console.error('[Supabase] Error saving todo results:', error);
    }
  }

  /**
   * Increment todo retry count
   */
  async incrementTodoRetry(todoId) {
    if (!this.client) return;

    const { data: todo } = await this.client
      .from('lux_todos')
      .select('retry_count')
      .eq('id', todoId)
      .single();

    if (todo) {
      await this.client
        .from('lux_todos')
        .update({
          retry_count: (todo.retry_count || 0) + 1,
          status: 'pending'
        })
        .eq('id', todoId);
    }
  }

  /**
   * Check if Supabase is configured
   */
  isConfigured() {
    return this.client !== null;
  }

  /**
   * Check if user is logged in
   */
  isLoggedIn() {
    return this.user !== null;
  }

  /**
   * Get Supabase client instance
   */
  getClient() {
    return this.client;
  }
}

// Export singleton
module.exports = new SupabaseClient();
