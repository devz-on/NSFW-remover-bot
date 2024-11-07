import logging
import os
import time
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from nudenet import NudeDetector
from PIL import Image, ImageSequence

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize NudeDetector
detector = NudeDetector()

# Basic Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm here to keep the chat safe.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Available commands: /start, /help, /mute, /ban, /info, /tmute, /tban, /broadcast")

# Function to handle photos and static stickers
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat_id
    photo = update.message.photo[-1]  # Get the highest resolution image

    # Download the image
    file = await photo.get_file()
    file_path = f"{photo.file_id}.jpg"
    await file.download_to_drive(file_path)

    # Check if image is NSFW
    detections = detector.detect(file_path)
    nsfw_classes = {"BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "ANUS_EXPOSED", "MALE_GENITALIA_EXPOSED"}
    is_nsfw = any(detection['class'] in nsfw_classes and detection['score'] > 0.7 for detection in detections)

    logger.info(f"Detection results for {file_path}: {detections}")

    if is_nsfw:
        await update.message.delete()
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {user.first_name}, NSFW content is not allowed!")
        await mute_user(context, chat_id, user.id)  # Mute for 2 hours
    else:
        await context.bot.send_message(chat_id=chat_id, text="This image was deemed safe.")
    
    # Clean up the downloaded image file
    if os.path.exists(file_path):
        os.remove(file_path)

async def mute_user(context, chat_id, user_id):
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=int(time.time() + 2 * 60 * 60)  # Mute for 2 hours
        )
    except Exception as e:
        logger.error(f"Failed to mute user {user_id}: {e}")

# Function to handle GIFs
async def handle_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document and update.message.document.mime_type == 'image/gif':
        user = update.message.from_user
        chat_id = update.message.chat_id

        # Notify that animated GIFs are not allowed
        await update.message.delete()
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Animated GIFs are not allowed in this chat.")

# Function to handle stickers, including detection of animated WebP
# Function to handle stickers, including detection of animated WebP
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.sticker:
        user = update.message.from_user
        chat_id = update.message.chat_id
        sticker = update.message.sticker

        # Download the sticker file
        file = await sticker.get_file()
        file_path_webp = f"{sticker.file_id}.webp"

        try:
            await file.download_to_drive(file_path_webp)
            if not os.path.exists(file_path_webp):
                logger.error(f"Download failed, file not found: {file_path_webp}")
                return  # Exit if download fails
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return  # Exit if there's an error during download

        is_nsfw = False
        frame_paths = []  # Track frame file paths for cleanup

        # Attempt to process the WebP image
        try:
            with Image.open(file_path_webp) as img:
                if img.is_animated:
                    # Notify that animated stickers are not allowed
                    await update.message.delete()
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ Animated stickers are not allowed in this chat.")
                    return  # Exit after notifying

                # Process static WebP stickers frame by frame
                for i, frame in enumerate(ImageSequence.Iterator(img)):
                    frame = frame.convert("RGB")
                    temp_frame_path = f"{sticker.file_id}_frame_{i}.jpg"
                    frame.save(temp_frame_path)
                    frame_paths.append(temp_frame_path)

                    # Run NSFW detection on each frame
                    detections = detector.detect(temp_frame_path)
                    nsfw_classes = {"FEMALE_BREAST_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_GENITALIA_EXPOSED"}
                    if any(detection['class'] in nsfw_classes and detection['score'] > 0.7 for detection in detections):
                        is_nsfw = True
                        break  # Stop checking further frames if NSFW content is detected

        except (EOFError, OSError) as e:
            # Handle errors related to image processing (e.g., unsupported format)
            logger.error(f"Failed to process WebP: {e}")
            await update.message.delete()
            await context.bot.send_message(chat_id=chat_id, text="⚠️ The sticker could not be processed. Please send a valid static sticker.")
            return
        finally:
            # Clean up all frame files
            for path in frame_paths:
                if os.path.exists(path):
                    os.remove(path)
            # Check and delete the original WebP file
            if os.path.exists(file_path_webp):
                os.remove(file_path_webp)

        # Respond based on NSFW detection results
        if is_nsfw:
            await update.message.delete()
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {user.first_name}, NSFW content is not allowed!")
            await mute_user(context, chat_id, user.id)  # Mute for 2 hours
        else:
            await context.bot.send_message(chat_id=chat_id, text="This sticker was deemed safe.")

# Admin-only command handler (mute)
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.reply_to_message.from_user
    chat_id = update.message.chat_id
    chat_member = await context.bot.get_chat_member(chat_id, update.message.from_user.id)

    # Check if the command issuer is an admin
    if chat_member.status in ["administrator", "creator"]:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text(f"Muted {user.first_name}.")
    else:
        await update.message.reply_text("You must be an admin to use this command.")

# Broadcast command for bot owner only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_owner_id = 1875300132  # Replace with your Telegram user ID
    if update.message.from_user.id == bot_owner_id:
        message = update.message.text.partition(" ")[2]
        for chat in context.bot_data.get("chats", []):
            try:
                await context.bot.send_message(chat_id=chat, text=message)
            except Exception as e:
                logger.error(f"Could not send message to chat {chat}: {e}")
    else:
        await update.message.reply_text("Only the bot owner can use this command.")

# Main function to initialize the bot
def main():
    app = Application.builder().token("7012069955:AAEhPYDdCLZxsw7IKfvRUxjCvXye1kZkSiE").build()  # Replace with your actual bot token
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Add handlers for photos, GIFs, and stickers
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.Document.MimeType("image/gif"), handle_gif))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))  # Use filters.Sticker.ALL for stickers

    # Start polling for updates
    app.run_polling()

if __name__ == "__main__":
    main()