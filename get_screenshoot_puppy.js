// get_screenshoot_puppy.js

const puppeteer = require('puppeteer');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

// Helper to define delays
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  // Parse command line arguments
  const args = process.argv.slice(2);
  const url = args[0];
  const startPaused = args.includes('--pause');
  const windowSizeArg = args.find(arg => arg.startsWith('--window-size='));
  let windowWidth = 2420; // Default value
  let windowHeight = 1420; // Default value

  if (windowSizeArg) {
    const [width, height] = windowSizeArg.split('=')[1].split(',').map(Number);
    windowWidth = width || windowWidth;
    windowHeight = height || windowHeight;
  }

  if (!url) {
    console.error('URL argument is required');
    process.exit(1);
  }

  // Ensure screenshots directory exists
  const screenshotsDir = 'screenshots';
  if (!fs.existsSync(screenshotsDir)){
      fs.mkdirSync(screenshotsDir);
  }

  // Launch browser.
  // Note: To ensure "Save As" dialog appears, we rely on default non-headless behavior.
  const browser = await puppeteer.launch({
    args: [
      '--no-sandbox',
      `--window-size=${windowWidth},${windowHeight}`,
      '--disable-features=IsolateOrigins,site-per-process' // Helps with cross-origin iframe issues
    ],
    headless: false,
    protocolTimeout: 300000,
    defaultViewport: null // Important to allow dynamic resizing
  });
  const page = await browser.newPage();

  // Settings for final output
  const clipWidth = 1920;
  const clipHeight = 2560;
  
  // Set initial view for interaction
  await page.setViewport({ 
    width: windowWidth,
    height: windowHeight
  });

  console.error('Navigating to:', url); // Use stderr for logs intended for human, stdout for Python
  try {
    await page.goto(url, {
      waitUntil: 'domcontentloaded', // Faster than networkidle0 for complex sites
      timeout: 60000
    });
  } catch (e) {
    console.error("Navigation error or timeout, continuing anyway to allow manual fix.");
  }

  // Force enable scrolling
  await page.evaluate(() => {
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
    // Sometimes height: 100% prevents scrolling on body
    document.body.style.height = 'auto'; 
  });

  // --- INTERACTION LOOP SETUP ---

  // Expose function to receive uploaded file data from browser context
  let uploadedFileData = null;
  await page.exposeFunction('nodeReceiveUpload', (dataUrl, filename) => {
      uploadedFileData = { dataUrl, filename };
      console.error(`File received from browser: ${filename}`);
  });

  // Add virtual floating menu
  await addControlMenu(page);

  // Initial Auto-scroll
  console.error('Attempting initial scroll...');
  try {
    await page.evaluate(async () => {
      window.scrollTo(0, window.innerHeight / 2);
    });
    await delay(2000); // wait for load
  } catch (e) { console.error("Scroll failed, continuing."); }

  // State variables for the loop
  let isPaused = startPaused;
  let actionTaken = null; // 'CONTINUE', 'UPLOADED'
  let lastConsoleMsg = null;

  if (startPaused) {
    console.error('--- STARTED IN PAUSED MODE ---');
    console.error('Use the on-screen menu to proceed.');
  }

  // Listen for messages from browser UI
  page.on('console', msg => {
    const text = msg.text();
    if (text === 'STOP_PRESSED') lastConsoleMsg = 'STOP';
    if (text === 'CONTINUE_PRESSED') lastConsoleMsg = 'CONTINUE';
    if (text === 'SAVE_MANUAL_PRESSED') lastConsoleMsg = 'SAVE_MANUAL';
    if (text.startsWith('UPLOAD_TRIGGERED')) lastConsoleMsg = 'UPLOADING';
  });

  // Main interaction loop
  while (true) {
    
    // 1. Handle state changes based on console messages
    if (lastConsoleMsg === 'STOP') {
        isPaused = true;
        console.error('State: PAUSED via UI.');
        lastConsoleMsg = null;
    } else if (lastConsoleMsg === 'CONTINUE') {
        isPaused = false;
        console.error('State: CONTINUING to auto-screenshot.');
        actionTaken = 'CONTINUE';
        lastConsoleMsg = null;
        break; // Exit loop to take standard screenshot
    }

    // 2. Handle File Upload (replaces screenshot)
    if (uploadedFileData) {
        console.error('Processing uploaded file...');
        actionTaken = 'UPLOADED';
        break; // Exit loop to process upload
    }

    // 3. Handle "Save to Disk" (Manual Download)
    if (lastConsoleMsg === 'SAVE_MANUAL') {
        console.error('Initiating manual save to disk...');
        lastConsoleMsg = null; // Reset

        // Hide menu temporarily
        await page.evaluate(() => { document.getElementById('control-menu').style.display = 'none'; });
        await delay(200);

        // 1. Set Viewport for capture
        await page.setViewport({ width: clipWidth, height: clipHeight });
        
        // 2. Capture to buffer
        const imgBuffer = await page.screenshot({
            clip: { x: 0, y: 0, width: clipWidth, height: clipHeight },
            encoding: 'binary'
        });

        // 3. Process with Sharp to WebP Buffer
        const webpBuffer = await sharp(imgBuffer)
            .resize({
                width: Math.round(clipWidth * 0.5),
                height: Math.round(clipHeight * 0.5),
                fit: 'inside',
                withoutEnlargement: true
            })
            .webp({ quality: 80 })
            .toBuffer();

        // 4. Convert to base64 to send back to browser
        const base64Image = `data:image/webp;base64,${webpBuffer.toString('base64')}`;
        const suggestName = generateScreenshotName(page.url()) + '_manual.webp';

        // 5. Trigger download in browser context
        await page.evaluate((dataUri, filename) => {
            const a = document.createElement('a');
            a.href = dataUri;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }, base64Image, suggestName);

        console.error('Browser download triggered. Check for "Save As" dialog.');

        // Restore view and menu
        await page.setViewport({ width: windowWidth, height: windowHeight });
        await page.evaluate(() => { document.getElementById('control-menu').style.display = 'flex'; });
    }

    // Wait a bit before next iteration to prevent high CPU usage
    await delay(500);

    // If not paused and no specific action triggered, treat as auto-continue after initial delay
    if (!isPaused && !startPaused && !actionTaken) {
        await delay(5000); // Original 5 sec wait
        actionTaken = 'CONTINUE';
        break;
    }
  }

  // --- FINAL PROCESSING ---

  let finalWebpPath = '';

  if (actionTaken === 'UPLOADED' && uploadedFileData) {
      // -- PROCESS UPLOADED FILE --
      const base64Data = uploadedFileData.dataUrl.split(',')[1];
      const imgBuffer = Buffer.from(base64Data, 'base64');
      
      const rawName = path.parse(uploadedFileData.filename).name;
      // Sanitize filename
      const safeName = rawName.replace(/[^a-zA-Z0-9-_]/g, '_');
      finalWebpPath = path.join(screenshotsDir, `upload_${safeName}_${Date.now()}.webp`);

      // Process and save locally using Sharp
      await sharp(imgBuffer)
        .resize({
            width: 960, //Target width (1920 * 0.5)
            height: 1280, // Target height (2560 * 0.5)
            fit: 'inside',
            withoutEnlargement: true
        })
        .webp({ quality: 80 })
        .toFile(finalWebpPath);
        
      console.error(`Processed uploaded file saved to: ${finalWebpPath}`);

  } else if (actionTaken === 'CONTINUE') {
      // -- PROCESS AUTOMATIC SCREENSHOT --
      
      // Remove menu
      await page.evaluate(() => {
        const menu = document.getElementById('control-menu');
        if (menu) menu.remove();
      });

      // Set full size for screenshot
      await page.setViewport({ width: clipWidth, height: clipHeight });

      const baseName = generateScreenshotName(page.url());
      const tempPngPath = path.join(screenshotsDir, `${baseName}_temp.png`);
      finalWebpPath = path.join(screenshotsDir, `${baseName}.webp`);

      // Take raw screenshot
      await page.screenshot({ 
        path: tempPngPath,
        clip: { x: 0, y: 0, width: clipWidth, height: clipHeight }
      });

      // Convert/Resize to WebP
      await sharp(tempPngPath)
        .resize({
          width: Math.round(clipWidth * 0.5),
          height: Math.round(clipHeight * 0.5),
          fit: 'inside',
          withoutEnlargement: true
        })
        .webp({ quality: 80 })
        .toFile(finalWebpPath);

      // Cleanup temp file
      try { fs.unlinkSync(tempPngPath); } catch(e) {}
  }

  await browser.close();

  // CRITICAL: Output the final path to STDOUT for Python to read.
  if (finalWebpPath) {
    console.log(`Screenshot saved: ${finalWebpPath}`);
  } else {
    console.error("No image was processed.");
    process.exit(1);
  }
})();

// Function to add virtual floating menu with new buttons
async function addControlMenu(page) {
  await page.evaluate(() => {
    // Remove existing if any
    const existing = document.getElementById('control-menu');
    if(existing) existing.remove();

    const menu = document.createElement('div');
    menu.id = 'control-menu';
    // Styles for UI
    Object.assign(menu.style, {
        position: 'fixed', top: '10px', left: '10px', zIndex: '2147483647',
        background: 'rgba(30, 30, 30, 0.9)', padding: '15px', borderRadius: '8px',
        display: 'flex', flexDirection: 'column', gap: '10px',
        boxShadow: '0 4px 6px rgba(0,0,0,0.3)', fontFamily: 'sans-serif'
    });

    const createBtn = (text, color, onClickId) => {
        const btn = document.createElement('button');
        btn.innerText = text;
        Object.assign(btn.style, {
            padding: '10px 20px', fontSize: '16px', fontWeight: 'bold',
            background: color, color: 'white', border: 'none',
            cursor: 'pointer', borderRadius: '4px'
        });
        btn.onclick = () => console.log(onClickId);
        return btn;
    };

    // Row 1: Flow Control
    const row1 = document.createElement('div');
    row1.style.display = 'flex'; row1.style.gap = '10px';
    row1.appendChild(createBtn('PAUSE / STOP', '#ff4444', 'STOP_PRESSED'));
    row1.appendChild(createBtn('AUTO SNAP & FINISH', '#44ff44', 'CONTINUE_PRESSED'));
    
    // Row 2: Manual Actions
    const row2 = document.createElement('div');
    row2.style.display = 'flex'; row2.style.gap = '10px';

    // 1. Save to Disk Button
    const btnSave = createBtn('Save to Disk (Triggers Download)', '#2196F3', 'SAVE_MANUAL_PRESSED');
    
    // 2. Upload File items
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.id = 'puppy-file-upload';
    fileInput.accept = 'image/*';
    fileInput.style.display = 'none';

    // Handle file selection in browser
    fileInput.onchange = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        console.log('UPLOAD_TRIGGERED'); // Notify Node loop
        
        const reader = new FileReader();
        reader.onload = function(event) {
            // Call exposed Node function
            window.nodeReceiveUpload(event.target.result, file.name);
            // Provide visual feedback
            const uploadBtn = document.getElementById('btn-upload-visual');
            if(uploadBtn) {
                uploadBtn.innerText = 'Processing...';
                uploadBtn.style.background = '#888';
            }
        };
        reader.readAsDataURL(file);
    };

    const btnUpload = createBtn('Upload File & Finish', '#ff9800', 'UPLOAD_CLICKED_LOG');
    btnUpload.id = 'btn-upload-visual';
    // Override onclick to trigger file input
    btnUpload.onclick = () => { document.getElementById('puppy-file-upload').click(); };

    row2.appendChild(btnSave);
    row2.appendChild(btnUpload);

    menu.appendChild(row1);
    menu.appendChild(row2);
    menu.appendChild(fileInput);
    document.body.appendChild(menu);
  });
}

// Generate filename from URL (kept mostly original)
function generateScreenshotName(url) {
  try {
    const parsedUrl = new URL(url);
    const host = parsedUrl.hostname.replace(/www\./, '').split('.')[0];
    let pathName = parsedUrl.pathname.replace(/\/$/, '').replace(/^\//, '').replace(/\//g, '-');
    
    if (pathName.endsWith('index.html') || pathName.endsWith('index.php')) {
        pathName = pathName.replace(/index\.(html|php)/, '');
    }
    
    let name = host;
    if (pathName && pathName.length > 1) {
        name += '-' + pathName;
    }
    // Sanitize
    return name.replace(/[^a-zA-Z0-9-_]/g, '');
  } catch (e) {
    return 'screenshot-' + Date.now();
  }
}