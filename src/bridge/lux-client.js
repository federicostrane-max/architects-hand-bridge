const https = require('https');

class LuxClient {
  constructor() {
    this.apiKey = null;
    this.baseUrl = 'api.agiopen.org';
  }

  setApiKey(key) {
    this.apiKey = key;
  }

  async request(endpoint, body) {
    if (!this.apiKey) {
      throw new Error('OpenAGI API key not set');
    }

    return new Promise((resolve, reject) => {
      const postData = JSON.stringify(body);

      const options = {
        hostname: this.baseUrl,
        port: 443,
        path: endpoint,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Length': Buffer.byteLength(postData)
        }
      };

      const req = https.request(options, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            const parsed = JSON.parse(data);
            if (res.statusCode >= 400) {
              reject(new Error(parsed.error?.message || `API error: ${res.statusCode}`));
            } else {
              resolve(parsed);
            }
          } catch (e) {
            reject(new Error(`Failed to parse response: ${data}`));
          }
        });
      });

      req.on('error', (e) => {
        reject(new Error(`Request failed: ${e.message}`));
      });

      req.setTimeout(60000, () => {
        req.destroy();
        reject(new Error('Request timeout'));
      });

      req.write(postData);
      req.end();
    });
  }

  async act(screenshotBase64, goal, context = null) {
    const body = {
      model: 'lux-actor',
      screenshot: screenshotBase64,
      goal: goal,
      context: context
    };

    const response = await this.request('/v1/act', body);
    return this.parseActionResponse(response);
  }

  async think(screenshotBase64, goal, history = [], context = null) {
    const body = {
      model: 'lux-thinker',
      screenshot: screenshotBase64,
      goal: goal,
      history: history,
      context: context
    };

    const response = await this.request('/v1/think', body);
    return this.parseActionResponse(response);
  }

  async task(screenshotBase64, instruction, context = null) {
    const body = {
      model: 'lux-tasker',
      screenshot: screenshotBase64,
      instruction: instruction,
      context: context
    };

    const response = await this.request('/v1/task', body);
    return this.parseActionResponse(response);
  }

  parseActionResponse(response) {
    const result = {
      action: null,
      actions: [],
      status: 'unknown',
      feedback: null,
      reasoning: null,
      raw: response
    };

    if (response.action) {
      result.action = this.normalizeAction(response.action);
      result.actions = [result.action];
    }

    if (response.actions && Array.isArray(response.actions)) {
      result.actions = response.actions.map(a => this.normalizeAction(a));
      result.action = result.actions[0] || null;
    }

    result.status = response.status || 'completed';
    result.feedback = response.feedback || response.message || null;
    result.reasoning = response.reasoning || response.thought || null;

    if (response.done || response.completed || response.status === 'done') {
      result.status = 'done';
    }

    if (response.error || response.status === 'error') {
      result.status = 'error';
      result.feedback = response.error || response.message || 'Unknown error';
    }

    return result;
  }

  normalizeAction(action) {
    if (typeof action === 'string') {
      return this.parseActionString(action);
    }

    return {
      type: action.type || action.action || 'unknown',
      x: action.x || action.coordinate?.[0] || null,
      y: action.y || action.coordinate?.[1] || null,
      text: action.text || action.value || null,
      key: action.key || null,
      direction: action.direction || null,
      amount: action.amount || action.delta || null,
      selector: action.selector || null,
      url: action.url || null,
      ...action
    };
  }

  parseActionString(str) {
    const action = { type: 'unknown', raw: str };

    const clickMatch = str.match(/click\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)/i);
    if (clickMatch) {
      return { type: 'click', x: parseInt(clickMatch[1]), y: parseInt(clickMatch[2]) };
    }

    const typeMatch = str.match(/type\s*\(\s*["'](.*)["']\s*\)/i);
    if (typeMatch) {
      return { type: 'type', text: typeMatch[1] };
    }

    const scrollMatch = str.match(/scroll\s*\(\s*(?:["']?(\w+)["']?\s*,\s*)?(-?\d+)\s*\)/i);
    if (scrollMatch) {
      return { 
        type: 'scroll', 
        direction: scrollMatch[1] || 'down', 
        amount: parseInt(scrollMatch[2]) 
      };
    }

    const pressMatch = str.match(/press\s*\(\s*["'](.+)["']\s*\)/i);
    if (pressMatch) {
      return { type: 'press', key: pressMatch[1] };
    }

    const waitMatch = str.match(/wait\s*\(\s*(\d+)\s*\)/i);
    if (waitMatch) {
      return { type: 'wait', duration: parseInt(waitMatch[1]) };
    }

    if (/done|complete|finished/i.test(str)) {
      return { type: 'done' };
    }

    return action;
  }

  async executeStep(screenshotBase64, instruction, context = null) {
    console.log(`[Lux] Executing step: ${instruction.substring(0, 100)}...`);
    
    try {
      const result = await this.task(screenshotBase64, instruction, context);
      console.log(`[Lux] Result:`, result.status, result.feedback);
      return result;
    } catch (error) {
      console.error(`[Lux] Error:`, error.message);
      throw error;
    }
  }

  async verifyStep(screenshotBase64, expectedOutcome) {
    const verifyGoal = `Check if the following is true: ${expectedOutcome}. Respond with 'yes' if true, 'no' if false.`;
    
    try {
      const result = await this.act(screenshotBase64, verifyGoal);
      const isVerified = /yes|true|correct|confirmed/i.test(result.feedback || '');
      return {
        verified: isVerified,
        feedback: result.feedback,
        raw: result
      };
    } catch (error) {
      return {
        verified: false,
        feedback: `Verification failed: ${error.message}`,
        raw: null
      };
    }
  }
}

module.exports = new LuxClient();
