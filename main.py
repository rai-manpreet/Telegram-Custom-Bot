import logging
import base64
import requests
import json
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token
ALLOWED_CHAT_ID = 12345678  # Only this chat ID can use the bot
BEARER_TOKEN = "YOUR_BEARER_TOKEN_HERE"  # Replace with your bearer token for upscale API
BOT_USERNAME = "BOT_USERNAME"  # Replace with your bot's username (without @)

# API endpoints
CAPTION_ENDPOINT = "https://example.com/generate-captions"
UPSCALE_ENDPOINT = "https://example.com/upscale"
THUMBNAIL_ENDPOINT = "https://example.com/generate-thumbnail"

def check_chat_permission(chat_id: int) -> bool:
    """Check if the chat ID is allowed to use the bot"""
    return chat_id == ALLOWED_CHAT_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    if not check_chat_permission(update.effective_chat.id):
        await update.message.reply_text("You are not authorized to use this bot.")
        return
    
    await update.message.reply_text(
        "Welcome! Send me:\n"
        "📷 An image - I'll give you upscale or thumbnail options\n"
        "📝 Text - I'll generate captions for you\n"
        "📤 Use /share to get the group link\n"
        "🏷️ Use /rename to rename image files"
    )

async def share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Share command handler - returns HTML formatted message with bot link"""
    if not check_chat_permission(update.effective_chat.id):
        await update.message.reply_text("You are not authorized to use this bot.")
        return
    
    # HTML formatted message
    share_message = f"""Telegram ⤵
<a href="https://t.me/{BOT_USERNAME}">t.me/{BOT_USERNAME}</a>"""
    
    await update.message.reply_text(
        share_message,
        parse_mode='HTML',
        disable_web_page_preview=True
    )

async def rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rename command handler - initiates the rename process"""
    if not check_chat_permission(update.effective_chat.id):
        await update.message.reply_text("You are not authorized to use this bot.")
        return
    
    await update.message.reply_text(
        "📸 Please send me a photo or image document that you want to rename."
    )
    
    # Set user state to waiting for image
    context.user_data['waiting_for_rename_image'] = True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages"""
    if not check_chat_permission(update.effective_chat.id):
        return
    
    text = update.message.text
    
    # Check if user is in rename process and waiting for new filename
    if context.user_data.get('waiting_for_rename_filename'):
        await process_rename_with_filename(update, context, text)
        return
    
    # Send typing indicator
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # Call caption generation endpoint
        params = {"cap": text}
        response = requests.get(CAPTION_ENDPOINT, params=params, timeout=30)
        response.raise_for_status()
        
        # Parse JSON response and extract only the "result" field
        result = response.json()
        if "result" in result:
            await update.message.reply_text(result["result"])
        else:
            await update.message.reply_text("Error: No result found in response.")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling caption endpoint: {e}")
        await update.message.reply_text("Sorry, there was an error processing your text. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in handle_text: {e}")
        await update.message.reply_text("An unexpected error occurred. Please try again later.")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle image messages (both photos and documents)"""
    if not check_chat_permission(update.effective_chat.id):
        return
    
    # Check if user is in rename process
    if context.user_data.get('waiting_for_rename_image'):
        await process_rename_image(update, context)
        return
    
    # Handle both photo and document types
    if update.message.photo:
        # Get the largest photo size
        photo = update.message.photo[-1]
        context.user_data['photo_file_id'] = photo.file_id
    elif update.message.document and update.message.document.mime_type.startswith('image/'):
        # Handle document images
        document = update.message.document
        context.user_data['photo_file_id'] = document.file_id
    else:
        return
    
    # Create inline keyboard with options
    keyboard = [
        [
            InlineKeyboardButton("🔍 Upscale", callback_data="upscale_menu"),
            InlineKeyboardButton("🖼️ Thumbnail", callback_data="thumbnail")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "What would you like to do with this image?",
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries from inline keyboards"""
    query = update.callback_query
    await query.answer()
    
    if not check_chat_permission(update.effective_chat.id):
        return
    
    if query.data == "upscale_menu":
        # Show upscale options
        keyboard = [
            [
                InlineKeyboardButton("2x", callback_data="upscale_2x"),
                InlineKeyboardButton("4x (Default)", callback_data="upscale_4x"),
                InlineKeyboardButton("8x", callback_data="upscale_8x")
            ],
            [InlineKeyboardButton("← Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Choose upscale factor:",
            reply_markup=reply_markup
        )
    
    elif query.data == "back_to_main":
        # Go back to main options
        keyboard = [
            [
                InlineKeyboardButton("🔍 Upscale", callback_data="upscale_menu"),
                InlineKeyboardButton("🖼️ Thumbnail", callback_data="thumbnail")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "What would you like to do with this image?",
            reply_markup=reply_markup
        )
    
    elif query.data.startswith("upscale_"):
        scale_factor = query.data.split("_")[1]
        await process_upscale(update, context, scale_factor)
    
    elif query.data == "thumbnail":
        await process_thumbnail(update, context)

async def get_image_base64(context: ContextTypes.DEFAULT_TYPE, file_id: str, include_data_url: bool = False) -> str:
    """Convert image to base64"""
    file = await context.bot.get_file(file_id)
    file_bytes = BytesIO()
    await file.download_to_memory(file_bytes)
    file_bytes.seek(0)
    
    # Convert to base64
    base64_data = base64.b64encode(file_bytes.read()).decode('utf-8')
    
    if include_data_url:
        # Include data URL prefix for upscale endpoint
        return f"data:image/jpeg;base64,{base64_data}"
    else:
        # Return plain base64 for thumbnail endpoint
        return base64_data

async def process_upscale(update: Update, context: ContextTypes.DEFAULT_TYPE, scale_factor: str) -> None:
    """Process image upscaling"""
    query = update.callback_query
    
    # Edit message to show processing
    await query.edit_message_text("🔄 Processing upscale... Please wait.")
    
    try:
        # Get image base64
        photo_file_id = context.user_data.get('photo_file_id')
        if not photo_file_id:
            await query.edit_message_text("❌ Error: Image not found. Please send the image again.")
            return
        
        # Get base64 with data URL prefix for upscale endpoint
        base64_image = await get_image_base64(context, photo_file_id, include_data_url=True)
        
        # Prepare request data according to the expected format
        headers = {
            "Authorization": f"Bearer {BEARER_TOKEN}",
            "Content-Type": "application/json"
        }
        
        data = {
            "base64_data": base64_image,  # Changed from "image" to "base64_data"
            "size": scale_factor  # Changed from "scale" to "size"
        }
        
        # Send request to upscale endpoint with longer timeout for 4x and 8x
        timeout = 120 if scale_factor in ['4x', '8x'] else 60  # 2 minutes for 4x/8x, 1 minute for 2x
        response = requests.post(
            UPSCALE_ENDPOINT,
            headers=headers,
            json=data,
            timeout=timeout
        )
        response.raise_for_status()
        
        # Parse response
        result = response.json()
        
        # Check if response contains upscaled_base64 field
        if 'upscaled_base64' in result:
            # Extract base64 data (remove data URL prefix if present)
            base64_str = result['upscaled_base64']
            if base64_str.startswith('data:image'):
                base64_str = base64_str.split(',')[1]
            
            # Decode base64 image
            image_data = base64.b64decode(base64_str)
            image_file = BytesIO(image_data)
            image_file.name = f"upscaled_{scale_factor}.png"  # Set filename for document
            
            # Send upscaled image back as document to preserve quality
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=image_file,
                caption=f"✅ Image upscaled {scale_factor}",
                filename=f"upscaled_{scale_factor}.png"
            )
            
            # Delete the processing message
            await query.delete_message()
        else:
            await query.edit_message_text("❌ Error: Invalid response from upscale service.")
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error in upscale request: {e}")
        await query.edit_message_text("❌ Error processing upscale. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in process_upscale: {e}")
        await query.edit_message_text("❌ An unexpected error occurred during upscaling.")

async def process_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process thumbnail generation"""
    query = update.callback_query
    
    # Edit message to show processing
    await query.edit_message_text("🔄 Generating thumbnail... Please wait.")
    
    try:
        # Get image base64
        photo_file_id = context.user_data.get('photo_file_id')
        if not photo_file_id:
            await query.edit_message_text("❌ Error: Image not found. Please send the image again.")
            return
        
        # Get plain base64 for thumbnail endpoint (no data URL prefix)
        base64_image = await get_image_base64(context, photo_file_id, include_data_url=False)
        
        # Prepare request data
        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "image": base64_image  # Plain base64 as specified
        }
        
        # Send request to thumbnail endpoint
        response = requests.post(
            THUMBNAIL_ENDPOINT,
            headers=headers,
            json=data,
            timeout=45  # Increased timeout for thumbnail generation
        )
        response.raise_for_status()
        
        # Parse response
        result = response.json()
        
        # Check if response contains thumbnail field
        if 'thumbnail' in result:
            # Decode base64 image
            image_data = base64.b64decode(result['thumbnail'])
            image_file = BytesIO(image_data)
            image_file.name = "thumbnail.png"  # Set filename for document
            
            # Send thumbnail back as document to preserve quality
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=image_file,
                caption="✅ Thumbnail generated",
                filename="thumbnail.png"
            )
            
            # Delete the processing message
            await query.delete_message()
        else:
            await query.edit_message_text("❌ Error: Invalid response from thumbnail service.")
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error in thumbnail request: {e}")
        await query.edit_message_text("❌ Error generating thumbnail. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in process_thumbnail: {e}")
        await query.edit_message_text("❌ An unexpected error occurred during thumbnail generation.")

async def process_rename_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle image received for renaming"""
    # Store the image file_id for renaming
    if update.message.photo:
        # Get the largest photo size
        photo = update.message.photo[-1]
        context.user_data['rename_file_id'] = photo.file_id
        context.user_data['rename_file_type'] = 'photo'
    elif update.message.document and update.message.document.mime_type.startswith('image/'):
        # Handle document images
        document = update.message.document
        context.user_data['rename_file_id'] = document.file_id
        context.user_data['rename_file_type'] = 'document'
    else:
        await update.message.reply_text("❌ Please send a valid image file.")
        return
    
    # Clear the waiting flag and set new flag
    context.user_data['waiting_for_rename_image'] = False
    context.user_data['waiting_for_rename_filename'] = True
    
    await update.message.reply_text(
        "✅ Image received! Now please send me the new filename (without extension).\n"
        "Example: my_new_image\n"
        "The file will be saved as: your_name.png"
    )

async def process_rename_with_filename(update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str) -> None:
    """Process the rename with the provided filename"""
    try:
        # Get the stored file_id
        file_id = context.user_data.get('rename_file_id')
        if not file_id:
            await update.message.reply_text("❌ Error: No image found. Please start over with /rename")
            # Clear user data
            context.user_data.clear()
            return
        
        # Clean the filename (remove special characters, keep only alphanumeric, spaces, hyphens, underscores)
        import re
        clean_filename = re.sub(r'[^\w\s\-_]', '', filename.strip())
        clean_filename = clean_filename.replace(' ', '_')  # Replace spaces with underscores
        
        if not clean_filename:
            await update.message.reply_text("❌ Please provide a valid filename with letters, numbers, spaces, hyphens, or underscores only.")
            return
        
        # Add .png extension
        new_filename = f"{clean_filename}.png"
        
        # Send processing message
        processing_msg = await update.message.reply_text("🔄 Renaming your image... Please wait.")
        
        # Get the file and download it
        file = await context.bot.get_file(file_id)
        file_bytes = BytesIO()
        await file.download_to_memory(file_bytes)
        file_bytes.seek(0)
        
        # Set the filename for the BytesIO object
        file_bytes.name = new_filename
        
        # Send the renamed file back as document
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_bytes,
            filename=new_filename,
            caption=f"✅ Image renamed to: {new_filename}"
        )
        
        # Delete processing message
        await processing_msg.delete()
        
        # Clear user data
        context.user_data.clear()
        
    except Exception as e:
        logger.error(f"Error in process_rename_with_filename: {e}")
        await update.message.reply_text("❌ An error occurred while renaming the image. Please try again.")
        # Clear user data on error
        context.user_data.clear()

def main() -> None:
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("share", share))  # Add share command handler
    application.add_handler(CommandHandler("rename", rename))  # Add rename command handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_image))  # Handle document images
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Start the bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
