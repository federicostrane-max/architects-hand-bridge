/**
 * Supabase Client for Architect's Hand Bridge
 * Handles database operations and real-time subscriptions
 */

const { createClient } = require('@supabase/supabase-js');

class SupabaseClient {
  constructor() {
    this.client = null;
    this.user = null;
    this.subscription = null;
  }

  /**
   * Initialize the Supabase client
   */
  initialize(url, anonKey) {
    this.client = createClient(url, anonKey);
    console.log('[Supabase] Client initialized');
  }

  /**
   * Get the raw Supabase client
   */
  getClient() {
    return this.client;
  }

  /**
   * Poll for pending tasks
   */
  async pollPendingTasks() {
    if (!this.client) return [];

    try {
      const { data, error } = await this.client
        .from('lux_tasks')
        .select('*')
        .eq('status', 'pending')
        .order('created_at', { ascending: true })
        .limit(1);

      if (error) {
        console.error('[Supabase] Poll error:', error.message);
        return [];
      }

      return data || [];
    } catch (e) {
      console.error('[Supabase] Poll exception:', e.message);
      return [];
    }
  }

  /**
   * Get todos for a task
   */
  async getTodosForTask(taskId) {
    if (!this.client) return [];

    try {
      const { data, error } = await this.client
        .from('lux_todos')
        .select('*')
        .eq('task_id', taskId)
        .order('todo_index', { ascending: true });

      if (error) {
        console.error('[Supabase] Get todos error:', error.message);
        return [];
      }

      return data || [];
    } catch (e) {
      console.error('[Supabase] Get todos exception:', e.message);
      return [];
    }
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

    if (status === 'running') {
      updateData.started_at = new Date().toISOString();
    } else if (status === 'completed' || status === 'failed') {
      updateData.completed_at = new Date().toISOString();
    }

    try {
      const { error } = await this.client
        .from('lux_tasks')
        .update(updateData)
        .eq('id', taskId);

      if (error) {
        console.error('[Supabase] Update task error:', error.message);
      }
    } catch (e) {
      console.error('[Supabase] Update task exception:', e.message);
    }
  }

  /**
   * Update task progress
   */
  async updateTaskProgress(taskId, progress) {
    await this.updateTaskStatus(taskId, 'running', { progress });
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

    if (status === 'running') {
      updateData.started_at = new Date().toISOString();
    } else if (status === 'completed' || status === 'failed') {
      updateData.completed_at = new Date().toISOString();
    }

    try {
      const { error } = await this.client
        .from('lux_todos')
        .update(updateData)
        .eq('id', todoId);

      if (error) {
        console.error('[Supabase] Update todo error:', error.message);
      }
    } catch (e) {
      console.error('[Supabase] Update todo exception:', e.message);
    }
  }

  /**
   * Subscribe to real-time task updates
   */
  subscribeToTasks(onNewTask, onTodoChange, onTaskStatusChange) {
    if (!this.client) return;

    // Subscribe to task changes
    this.subscription = this.client
      .channel('lux_tasks_channel')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'lux_tasks' },
        (payload) => {
          console.log('[Supabase] New task inserted');
          if (onNewTask) onNewTask(payload.new);
        }
      )
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'lux_tasks' },
        (payload) => {
          console.log('[Supabase] Task updated');
          if (onTaskStatusChange) onTaskStatusChange(payload.new);
        }
      )
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'lux_todos' },
        (payload) => {
          console.log('[Supabase] Todo changed');
          if (onTodoChange) onTodoChange(payload);
        }
      )
      .subscribe((status) => {
        console.log('[Supabase] Subscription status:', status);
      });
  }

  /**
   * Unsubscribe from real-time updates
   */
  unsubscribe() {
    if (this.subscription) {
      this.client.removeChannel(this.subscription);
      this.subscription = null;
      console.log('[Supabase] Unsubscribed from channels');
    }
  }
}

// Export singleton
module.exports = new SupabaseClient();
