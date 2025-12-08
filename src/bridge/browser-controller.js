const { chromium } = require('playwright');
const path = require('path');

class BrowserController {
  constructor() {
    this.browser = null;
    this.context = null;
    this.page = null;
    this.isRunning = false;
  }

  // Launch browser
  async launch(options = {}) {
    if (this.browser) {
      await this.close();
    }

    console.log('[Browser] Launching Chromium...');

    // Determine executable path based on environment
    let executablePath = null;
    
    // In packaged app, use bundled browser
    if (process.resourcesPath) {
      const possiblePaths = [
        path.join(process.resourcesPath, 'playwright-browsers', 'chromium-*/chrome-win/chrome.exe'),
        path.join(process.resourcesPath, 'playwright-browsers', 'chromium*/chrome.exe')
      ];
      // Will use system Playwright if bundled not found
    }

    this.browser = await chromium.launch({
      headless: false, // Show browser window
      executablePath: executablePath,
      args: [
        '--disable-blink-features=AutomationControlled',
        '--disable-web-security',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--window-size=1280,800'
      ],
      ...options
    });

    // Create context with viewport
    this.context = await this.browser.newContext({
      viewport: { width: 1280, height: 800 },
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      ...options.context
    });

    // Create page
    this.page = await this.context.newPage();
    this.isRunning = true;

    console.log('[Browser] Launched successfully');
    return this.page;
  }

  // Get current page
  getPage() {
    return this.page;
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

    switch (action.type) {
      case 'click':
        await this.click(action.x, action.y);
        break;

      case 'double_click':
      case 'doubleclick':
        await this.doubleClick(action.x, action.y);
        break;

      case 'right_click':
      case 'rightclick':
        await this.rightClick(action.x, action.y);
        break;

      case 'type':
      case 'input':
        await this.type(action.text);
        break;

      case 'press':
      case 'key':
        await this.press(action.key);
        break;

      case 'scroll':
        await this.scroll(action.direction || 'down', action.amount || 300);
        break;

      case 'wait':
        await this.wait(action.duration || 1000);
        break;

      case 'goto':
      case 'navigate':
        await this.goto(action.url);
        break;

      case 'hover':
        await this.hover(action.x, action.y);
        break;

      case 'drag':
        await this.drag(action.startX, action.startY, action.endX, action.endY);
        break;

      case 'select':
        await this.selectOption(action.selector, action.value);
        break;

      case 'upload':
        await this.uploadFile(action.selector, action.files);
        break;

      case 'done':
      case 'complete':
        // No action needed, step is complete
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

  // Scroll
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
