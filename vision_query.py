#vision_query.py

import google.generativeai as genai
import PIL.Image
import sys
import os
import datetime
import logging
from dotenv import load_dotenv

# Create a directory for the logs if there isn't one
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Setup logging with absolute path and flush
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_dir, 'vision_query.log')
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Forced flush after each message
logger = logging.getLogger()
for handler in logger.handlers:
    handler.flush()

def log_with_flush(level, message):
    logger.log(level, message)
    for handler in logger.handlers:
        handler.flush()

# Load environment variables
load_dotenv()
log_with_flush(logging.DEBUG, "Environment variables loaded")

# Configure API key
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    log_with_flush(logging.ERROR, "GEMINI_API_KEY not found in .env file")
    sys.exit(1)
    
log_with_flush(logging.DEBUG, "API key found, configuring Gemini")
genai.configure(api_key=gemini_api_key)

def analyze_visual_style(image_path):
    log_with_flush(logging.INFO, f"Starting analysis of image: {image_path}")
    
    # Check if file exists
    if not os.path.exists(image_path):
        log_with_flush(logging.ERROR, f"File not found: {image_path}")
        return ""
    
    # Check file size
    file_size = os.path.getsize(image_path)
    log_with_flush(logging.DEBUG, f"File size: {file_size} bytes")
    
    if file_size < 5120:  # 5KB
        error_msg = f"Error: Blank screenshot detected - {image_path}"
        log_with_flush(logging.WARNING, error_msg)
        with open("log.txt", "a") as log_file:
            log_file.write(f"[{datetime.datetime.now()}] {error_msg}\n")
        return ""

    # Load and validate image
    try:
        image = PIL.Image.open(image_path)
        log_with_flush(logging.DEBUG, 
            f"Image loaded successfully: format={image.format}, size={image.size}, mode={image.mode}")
    except Exception as e:
        log_with_flush(logging.ERROR, f"Error loading image: {str(e)}")
        return ""

    # Initialize model
    try:
        log_with_flush(logging.DEBUG, "Initializing Gemini model")
        model = genai.GenerativeModel("gemini-1.5-flash-8b")
        log_with_flush(logging.DEBUG, "Model initialized successfully")
    except Exception as e:
        log_with_flush(logging.ERROR, f"Error initializing model: {str(e)}")
        return f"Model initialization error: {str(e)}"

    # Define prompt
    prompt = """
    You are an expert in visual analysis. Analyze the provided screenshot of a CYOA game and describe it in detail. Focus on the following:
    - Visual style (e.g., cartoonish, realistic, pixel art, etc.)
    - Color palette (dominant colors, background colors, text colors)
    - Objects, characters, or symbols present (describe their appearance, clothing, poses, etc.)
    - Layout and composition (e.g., text placement, image positioning)
    - Any notable details (e.g., specific themes like demons, fantasy, sci-fi, etc.)
    Provide a comprehensive description as if you’re explaining it to someone who cannot see the image. Avoid summarizing; include all relevant visual elements.
    """
    log_with_flush(logging.DEBUG, "Prompt prepared")

    # Generate response with error handling
    try:
        log_with_flush(logging.DEBUG, "Attempting to generate content with model")
        response = model.generate_content([prompt, image])
        log_with_flush(logging.DEBUG, "Response received from model")
        
        if not response.text:
            log_with_flush(logging.WARNING, "Empty response received from model")
            return "Empty response from model"
            
        log_with_flush(logging.INFO, f"Successfully generated description: {response.text[:100]}...")
        return response.text
        
    except Exception as e:
        error_msg = str(e)
        log_with_flush(logging.ERROR, f"Visual analysis error: {error_msg}")
        return error_msg

if __name__ == "__main__":
    log_with_flush(logging.INFO, "Script started")
    
    # Validate command line arguments
    if len(sys.argv) != 2:
        log_with_flush(logging.ERROR, "Invalid number of arguments")
        print("Usage: python vision_query.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    log_with_flush(logging.INFO, f"Processing image path: {image_path}")
    
    description = analyze_visual_style(image_path)
    
    if not description:
        log_with_flush(logging.WARNING, "No description generated")
    else:
        log_with_flush(logging.INFO, "Description generated successfully")
        
    print(description)
    log_with_flush(logging.INFO, "Script completed")