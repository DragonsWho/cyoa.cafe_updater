// get_screenshoot_puppy.js

// to run use  "   node get_screenshoot_puppy.js https://example.neocities.org/game/ --pause   " 

const puppeteer = require('puppeteer');
const sharp = require('sharp');
const fs = require('fs');

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

  // Launch the browser with the specified window size
  const browser = await puppeteer.launch({
    args: [
      '--no-sandbox',
      `--window-size=${windowWidth},${windowHeight}`
    ],
    headless: false,
    protocolTimeout: 300000
  });
  const page = await browser.newPage();

  const viewportWidth = 1920;
  const screenshotHeight = 2560;
  await page.setViewport({ 
    width: viewportWidth,
    height: 1080, // Initial height for interaction 
  });

  console.log('Navigating to:', url);
  await page.goto(url, {
    waitUntil: 'networkidle0',
    timeout: 300000
  });

  await page.waitForSelector('body', { timeout: 300000 });
  console.log('Page URL after navigation:', page.url());

  // Force enable scrolling
  await page.evaluate(() => {
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
    document.body.style.height = 'auto';
  });

  // Add virtual floating menu
  await addControlMenu(page);

  // Scroll down a couple of screens (2 * viewport height) and wait 5 seconds
  await page.evaluate(async () => {
    const scrollAmount = window.innerHeight * 2; // Scroll down 2 screens
    window.scrollTo(0, scrollAmount);
  });
  console.log('Scrolled down 2 screens, waiting 5 seconds for content to load...');
  await new Promise(resolve => setTimeout(resolve, 5000)); // Pause for 5 seconds

  // Wait for "STOP" and "CONTINUE" presses
  let isPaused = startPaused;
  if (startPaused) {
    console.log('Started in paused mode. Adjust the page manually, then press "CONTINUE".');
  }

  page.on('console', msg => {
    if (msg.text() === 'STOP_PRESSED') {
      isPaused = true;
      console.log('Paused. Adjust the page manually, then press "CONTINUE".');
    } else if (msg.text() === 'CONTINUE_PRESSED') {
      isPaused = false;
      console.log('Continuing screenshot process...');
    }
  });

  // Wait until the user presses "STOP" and "CONTINUE"
  let attempts = 0;
  const maxAttempts = 300;
  while (attempts < maxAttempts) {
    if (isPaused) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      continue;
    }

    if (!isPaused && (attempts > 0 || startPaused)) {
      break;
    }

    await new Promise(resolve => setTimeout(resolve, 1000));
    attempts++;
  }

  if (attempts >= maxAttempts) {
    throw new Error('Timeout waiting for user interaction');
  }

  // Remove the menu before taking the screenshot
  await page.evaluate(() => {
    const menu = document.getElementById('control-menu');
    if (menu) menu.remove();
  });

  // Set full size for the screenshot
  await page.setViewport({
    width: viewportWidth,
    height: screenshotHeight, 
  });

  // Take the screenshot
  const screenshotName = generateScreenshotName(page.url());
  const screenshotPath = `screenshots/${screenshotName}.png`;
  const webpPath = `screenshots/${screenshotName}.webp`;

  await page.screenshot({ 
    path: screenshotPath,
    clip: { x: 0, y: 0, width: viewportWidth, height: screenshotHeight }
  });

  // Convert to WebP
  await sharp(screenshotPath)
    .resize({
      width: Math.round(viewportWidth * 0.5),
      height: Math.round(screenshotHeight * 0.5),
      fit: 'inside',
      withoutEnlargement: true
    })
    .webp({ quality: 80 })
    .toFile(webpPath);

  console.log(`Screenshot saved: ${webpPath}`);

  // Clean up temporary file
  fs.unlinkSync(screenshotPath);
  await browser.close();
})();

// Function to add virtual floating menu
async function addControlMenu(page) {
  await page.evaluate(() => {
    const menu = document.createElement('div');
    menu.id = 'control-menu';
    menu.style.position = 'fixed'; // Changed to fixed to stay in place during scroll
    menu.style.top = '10px';
    menu.style.left = '10px';
    menu.style.zIndex = '9999';
    menu.style.background = 'rgba(0, 0, 0, 0.8)';
    menu.style.padding = '20px';
    menu.style.borderRadius = '10px';
    menu.style.display = 'flex';
    menu.style.gap = '20px';

    const stopButton = document.createElement('button');
    stopButton.innerText = 'STOP';
    stopButton.style.padding = '15px 30px';
    stopButton.style.fontSize = '24px';
    stopButton.style.background = '#ff4444';
    stopButton.style.color = 'white';
    stopButton.style.border = 'none';
    stopButton.style.cursor = 'pointer';
    stopButton.style.borderRadius = '8px';
    stopButton.onclick = () => console.log('STOP_PRESSED');

    const continueButton = document.createElement('button');
    continueButton.innerText = 'CONTINUE';
    continueButton.style.padding = '15px 30px';
    continueButton.style.fontSize = '24px';
    continueButton.style.background = '#44ff44';
    continueButton.style.color = 'white';
    continueButton.style.border = 'none';
    continueButton.style.cursor = 'pointer';
    continueButton.style.borderRadius = '8px';
    continueButton.onclick = () => console.log('CONTINUE_PRESSED');

    menu.appendChild(stopButton);
    menu.appendChild(continueButton);
    document.body.appendChild(menu);
  });
}

// Generate filename from URL
function generateScreenshotName(url) {
  const parsedUrl = new URL(url);
  const pathParts = parsedUrl.pathname.split('/').filter(Boolean);
  let screenshotName;

  if (pathParts.length > 0) {
    if (pathParts[pathParts.length - 1] === 'index.html') {
      screenshotName = pathParts[pathParts.length - 2] || parsedUrl.hostname.split('.')[0];
    } else {
      screenshotName = pathParts[pathParts.length - 1];
    }
  } else {
    screenshotName = parsedUrl.hostname;
  }
  return screenshotName;
}