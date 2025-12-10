const { chromium } = require('playwright');
const path = require('path');

class BrowserController {
  constructor() {
    this.browser = null;
    this.context = null;
    this.page = null;
    this.isRunning = false;
    
    // Viewport dimensions (Lux coordinates are normalized 0-1000)
    this.viewportWidth = 1280;
    this.viewportHeight = 800;
  }

  /**
   * Convert normalized coordinates (0-1000) to actual pixels
   * Lux uses 0-1000 range, we need to convert to viewport pixels
   */
  convertCoords(x, y, normalized = false) {
    if (normalized) {
      return {
        x: Math.round((x / 1000) * this.viewportWidth),
        y: Math.round((y / 1000) * this.viewportHeight)
      };
    }
    return { x, y };
  }

  // Launch browser
  async launch(options = {}) {
    if (this.browser) {
      await this.close();
    }

    console.log('[Browser] Launching Chromium...');

    const launchOptions = {
      headless: false,
      args: [
        '--disable-blink-features=AutomationControlled',
        '--disable-web-security',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        `--window-size=${this.viewportWidth},${this.viewportHeight}`
      ],
      ...options
    };

    this.browser = await chromium.launch(launchOptions);

    // Create context with viewport
    this.context = await this.browser.newContext({
      viewport: { width: this.viewportWidth, height: this.viewportHeight },
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      ...options.context
    });

    // Create page
    this.page = await this.context.newPage();
    this.isRunning = true;

    console.log(`[Browser] Launched successfully (viewport: ${this.viewportWidth}x${this.viewportHeight})`);
    return this.page;
  }

  // Get current page
  getPage() {
    return this.page;
  }

  // Get viewport size
  getViewportSize() {
    return {
      width: this.viewportWidth,
      height: this.viewportHeight
    };
  }

  // Navigate to URL
  async goto(url, options = {}) {
    if (!this.page) {
      throw new Error('Browser not launched');
    }

    console.log(`[Browser] Navigating to: ${url}`);
    await this.page.goto(url, { 
      waitUntil: 'domcontentloaded',
      timeout: 30000,
      ...options 
    });
  }

  // Take screenshot
  async screenshot(options = {}) {
    if (!this.page) {
      throw new Error('Browser not launched');
    }

    const buffer = await this.page.screenshot({
      type: 'png',
      fullPage: false,
      ...options
    });

    return buffer;
  }

  // Take screenshot as base64
  async screenshotBase64() {
    const buffer = await this.screenshot();
    return buffer.toString('base64');
  }

  // Execute action from Lux
  async executeAction(action) {
    if (!this.page) {
      throw new Error('Browser not launched');
    }

    console.log(`[Browser] Executing action: ${action.type}`, action);

    // Check if coordinates need conversion (Lux sends normalized 0-1000)
    const normalized = action.normalized === true;

    switch (action.type) {
      case 'click': {
        const { x, y } = this.convertCoords(action.x, action.y, normalized);
        await this.click(x, y);
        break;
      }

      case 'double_click':
      case 'doubleClick':
      case 'doubleclick': {
        const { x, y } = this.convertCoords(action.x, action.y, normalized);
        await this.doubleClick(x, y);
        break;
      }

      case 'right_click':
      case 'rightClick':
      case 'rightclick': {
        const { x, y } = this.convertCoords(action.x, action.y, normalized);
        await this.rightClick(x, y);
        break;
      }

      case 'type':
      case 'input':
        await this.type(action.text);
        break;

      case 'hotkey': {
        // Handle hotkey combinations like ['ctrl', 'c'] or 'ctrl+c'
        const keys = action.keys || action.combo?.split('+') || [];
        await this.hotkey(keys);
        break;
      }

      case 'press':
      case 'key':
        await this.press(action.key);
        break;

      case 'scroll': {
        // Lux sends x, y, direction for scroll
        if (action.x !== undefined && action.y !== undefined) {
          const { x, y } = this.convertCoords(action.x, action.y, normalized);
          await this.scrollAt(x, y, action.direction || 'down', action.count || 1);
        } else {
          await this.scroll(action.direction || 'down', action.amount || 300);
        }
        break;
      }

      case 'wait':
        await this.wait(action.duration || 1000);
        break;

      case 'goto':
      case 'navigate':
        await this.goto(action.url);
        break;

      case 'hover': {
        const { x, y } = this.convertCoords(action.x, action.y, normalized);
        await this.hover(x, y);
        break;
      }

      case 'drag': {
        const start = this.convertCoords(action.startX, action.startY, normalized);
        const end = this.convertCoords(action.endX, action.endY, normalized);
        await this.drag(start.x, start.y, end.x, end.y);
        break;
      }

      case 'select':
        await this.selectOption(action.selector, action.value);
        break;

      case 'upload':
        await this.uploadFile(action.selector, action.files);
        break;

      case 'done':
      case 'complete':
        // No action needed, step is complete
        console.log('[Browser] Step marked as complete');
        break;

      case 'call_user':
        // Lux is asking for user intervention
        console.log('[Browser] Lux requests user intervention:', action.message);
        break;

      default:
        console.warn(`[Browser] Unknown action type: ${action.type}`);
    }

    // Small delay after action for page to update
    await this.wait(300);
  }

  // Click at coordinates
  async click(x, y) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Clicking at (${x}, ${y})`);
    await this.page.mouse.click(x, y);
  }

  // Double click at coordinates
  async doubleClick(x, y) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Double clicking at (${x}, ${y})`);
    await this.page.mouse.dblclick(x, y);
  }

  // Right click at coordinates
  async rightClick(x, y) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Right clicking at (${x}, ${y})`);
    await this.page.mouse.click(x, y, { button: 'right' });
  }

  // Hover at coordinates
  async hover(x, y) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Hovering at (${x}, ${y})`);
    await this.page.mouse.move(x, y);
  }

  // Type text
  async type(text) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Typing: "${text.substring(0, 50)}${text.length > 50 ? '...' : ''}"`);
    await this.page.keyboard.type(text, { delay: 50 });
  }

  // Press key
  async press(key) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Pressing key: ${key}`);
    await this.page.keyboard.press(key);
  }

  // Press hotkey combination (e.g., ['ctrl', 'c'] or ['Control', 'Shift', 'T'])
  async hotkey(keys) {
    if (!this.page) throw new Error('Browser not launched');
    
    // Normalize key names for Playwright
    const normalizedKeys = keys.map(key => {
      const lower = key.toLowerCase();
      switch (lower) {
        case 'ctrl': return 'Control';
        case 'cmd': return 'Meta';
        case 'command': return 'Meta';
        case 'alt': return 'Alt';
        case 'shift': return 'Shift';
        case 'enter': return 'Enter';
        case 'tab': return 'Tab';
        case 'escape': return 'Escape';
        case 'esc': return 'Escape';
        case 'backspace': return 'Backspace';
        case 'delete': return 'Delete';
        case 'space': return 'Space';
        case 'up': return 'ArrowUp';
        case 'down': return 'ArrowDown';
        case 'left': return 'ArrowLeft';
        case 'right': return 'ArrowRight';
        default: return key;
      }
    });

    console.log(`[Browser] Pressing hotkey: ${normalizedKeys.join('+')}`);
    
    // Press modifier keys down
    for (const key of normalizedKeys.slice(0, -1)) {
      await this.page.keyboard.down(key);
    }
    
    // Press the final key
    const finalKey = normalizedKeys[normalizedKeys.length - 1];
    await this.page.keyboard.press(finalKey);
    
    // Release modifier keys
    for (const key of normalizedKeys.slice(0, -1).reverse()) {
      await this.page.keyboard.up(key);
    }
  }

  // Scroll at specific position
  async scrollAt(x, y, direction = 'down', count = 1) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Scrolling ${direction} at (${x}, ${y}) x${count}`);
    
    // Move mouse to position first
    await this.page.mouse.move(x, y);
    
    // Scroll amount per step
    const scrollAmount = 100;
    const deltaY = direction === 'up' ? -scrollAmount : scrollAmount;
    
    for (let i = 0; i < count; i++) {
      await this.page.mouse.wheel(0, deltaY);
      await this.wait(100);
    }
  }

  // Scroll (simple version)
  async scroll(direction = 'down', amount = 300) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Scrolling ${direction} by ${amount}`);
    
    const deltaY = direction === 'up' ? -amount : amount;
    await this.page.mouse.wheel(0, deltaY);
  }

  // Wait
  async wait(ms) {
    console.log(`[Browser] Waiting ${ms}ms`);
    await new Promise(resolve => setTimeout(resolve, ms));
  }

  // Drag from one point to another
  async drag(startX, startY, endX, endY) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Dragging from (${startX}, ${startY}) to (${endX}, ${endY})`);
    
    await this.page.mouse.move(startX, startY);
    await this.page.mouse.down();
    await this.page.mouse.move(endX, endY, { steps: 10 });
    await this.page.mouse.up();
  }

  // Select option in dropdown
  async selectOption(selector, value) {
    if (!this.page) throw new Error('Browser not launched');
    console.log(`[Browser] Selecting option: ${value} in ${selector}`);
    await this.page.selectOption(selector, value);
  }

  // Upload file(s)
  async uploadFile(selector, filePaths) {
    if (!this.page) throw new Error('Browser not launched');
    
    const files = Array.isArray(filePaths) ? filePaths : [filePaths];
    console.log(`[Browser] Uploading files: ${files.join(', ')}`);
    
    // Find file input
    const fileInput = await this.page.locator(selector || 'input[type="file"]');
    await fileInput.setInputFiles(files);
  }

  // Upload file at coordinates (click, then set files)
  async uploadFileAtCoords(x, y, filePaths) {
    if (!this.page) throw new Error('Browser not launched');
    
    const files = Array.isArray(filePaths) ? filePaths : [filePaths];
    console.log(`[Browser] Uploading files at (${x}, ${y}): ${files.join(', ')}`);
    
    // Set up file chooser listener before clicking
    const fileChooserPromise = this.page.waitForEvent('filechooser');
    await this.click(x, y);
    
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(files);
  }

  // Get current URL
  getUrl() {
    if (!this.page) return null;
    return this.page.url();
  }

  // Get page title
  async getTitle() {
    if (!this.page) return null;
    return await this.page.title();
  }

  // Close browser
  async close() {
    console.log('[Browser] Closing...');
    
    if (this.page) {
      await this.page.close().catch(() => {});
      this.page = null;
    }
    
    if (this.context) {
      await this.context.close().catch(() => {});
      this.context = null;
    }
    
    if (this.browser) {
      await this.browser.close().catch(() => {});
      this.browser = null;
    }
    
    this.isRunning = false;
    console.log('[Browser] Closed');
  }

  // Check if browser is running
  isActive() {
    return this.isRunning && this.browser !== null && this.page !== null;
  }
}

module.exports = new BrowserController();
