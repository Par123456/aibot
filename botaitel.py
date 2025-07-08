import asyncio
import datetime
import logging
import time
from typing import Dict, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from g4f.client import Client
import json
import os

# 🔧 تنظیمات
BOT_TOKEN = "7871342383:AAEnHXtvc6txRoyGegRL_IeErLISmS4j_DQ"  # توکن ربات تلگرام
CHANNEL_ID = ["@infinityIeveI", "@sharabyi"]  # آیدی چنل‌های مورد نظر

ADMIN_IDS = [2065070882, 6508600903]  # آیدی عددی ادمین‌ها (2 ادمین)

# 🤖 کلاینت AI
ai_client = Client()

# 📊 ذخیره داده‌های کاربران
user_data_file = "user_data.json"
user_messages: Dict[int, List[float]] = {}
user_chat_history: Dict[int, List[Dict]] = {}

# 📝 لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def load_user_data():
    """بارگذاری داده‌های کاربران از فایل"""
    global user_messages, user_chat_history
    if os.path.exists(user_data_file):
        try:
            with open(user_data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                user_messages = {int(k): v for k, v in data.get('messages', {}).items()}
                user_chat_history = {int(k): v for k, v in data.get('history', {}).items()}
        except:
            user_messages = {}
            user_chat_history = {}
    else:
        user_messages = {}
        user_chat_history = {}

def save_user_data():
    """ذخیره داده‌های کاربران در فایل"""
    data = {
        'messages': {str(k): v for k, v in user_messages.items()},
        'history': {str(k): v for k, v in user_chat_history.items()}
    }
    with open(user_data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_admin(user_id: int) -> bool:
    """بررسی ادمین بودن کاربر"""
    return user_id in ADMIN_IDS

def clean_old_messages(user_id: int):
    """پاک کردن پیام‌های قدیمی (بیش از 1 ساعت)"""
    if user_id not in user_messages:
        user_messages[user_id] = []
    
    current_time = time.time()
    user_messages[user_id] = [
        msg_time for msg_time in user_messages[user_id]
        if current_time - msg_time < 3600  # 1 ساعت
    ]

def can_send_message(user_id: int) -> bool:
    """بررسی امکان ارسال پیام"""
    if is_admin(user_id):
        return True
    
    clean_old_messages(user_id)
    return len(user_messages[user_id]) < 5

def get_remaining_time(user_id: int) -> int:
    """محاسبه زمان باقی‌مانده تا ریست محدودیت"""
    if is_admin(user_id):
        return 0
    
    clean_old_messages(user_id)
    if len(user_messages[user_id]) == 0:
        return 0
    
    oldest_message = min(user_messages[user_id])
    remaining = 3600 - (time.time() - oldest_message)
    return max(0, int(remaining))

def add_message(user_id: int):
    """اضافه کردن پیام به تاریخچه کاربر"""
    if user_id not in user_messages:
        user_messages[user_id] = []
    
    user_messages[user_id].append(time.time())
    save_user_data()

def format_time(seconds: int) -> str:
    """فرمت کردن زمان به دقیقه و ثانیه"""
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}:{seconds:02d}"

async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی عضویت در چنل"""
    user_id = update.effective_user.id
    
    if is_admin(user_id):
        return True
    
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور شروع"""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # بررسی عضویت در چنل
    if not await check_channel_membership(update, context):
        keyboard = [[InlineKeyboardButton("🔗 عضویت در چنل", url=f"https://t.me/{CHANNEL_ID[1:]}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"سلام {first_name}! 👋\n\n"
            "برای استفاده از ربات ابتدا باید در چنل عضو شوید:\n\n"
            "بعد از عضویت دوباره /start را بزنید.",
            reply_markup=reply_markup
        )
        return
    
    welcome_text = f"""
🤖 سلام {first_name}، به ربات هوش مصنوعی خوش آمدید!

📋 قوانین استفاده:
• کاربران عادی: ۵ پیام در ساعت
• ادمین‌ها: نامحدود
• عضویت در چنل الزامی است

💡 فقط سوال خود را بفرستید و پاسخ دریافت کنید!

@AnishtaYiN 
🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن
"""
    
    await update.message.reply_text(welcome_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های کاربران"""
    user_id = update.effective_user.id
    user_message = update.message.text
    first_name = update.effective_user.first_name
    
    # بررسی عضویت در چنل
    if not await check_channel_membership(update, context):
        keyboard = [[InlineKeyboardButton("🔗 عضویت در چنل", url=f"https://t.me/{CHANNEL_ID[1:]}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "❌ برای استفاده از ربات ابتدا باید در چنل عضو شوید!",
            reply_markup=reply_markup
        )
        return
    
    # بررسی محدودیت پیام
    if not can_send_message(user_id):
        remaining_time = get_remaining_time(user_id)
        await update.message.reply_text(
            f"⏰ {first_name}، شما امروز ۵ پیام خود را استفاده کرده‌اید.\n\n"
            f"⏳ زمان باقی‌مانده: {format_time(remaining_time)}\n\n"
            "@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        )
        return
    
    # ارسال پیام "در حال تایپ..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # آماده‌سازی تاریخچه گفتگو
        if user_id not in user_chat_history:
            user_chat_history[user_id] = []
        
        user_chat_history[user_id].append({"role": "user", "content": user_message})
        
        # محدود کردن تاریخچه به ۱۰ پیام آخر
        if len(user_chat_history[user_id]) > 20:
            user_chat_history[user_id] = user_chat_history[user_id][-20:]
        
        # درخواست به AI
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=user_chat_history[user_id],
            web_search=False,
            stream=False
        )
        
        bot_reply = response.choices[0].message.content.strip()
        user_chat_history[user_id].append({"role": "assistant", "content": bot_reply})
        
        # اضافه کردن امضا
        final_reply = f"{bot_reply}\n\n@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        
        # ارسال پاسخ
        await update.message.reply_text(final_reply)
        
        # اضافه کردن پیام به شمارنده
        add_message(user_id)
        
        # بررسی رسیدن به حد مجاز
        clean_old_messages(user_id)
        remaining_messages = 5 - len(user_messages[user_id])
        
        if remaining_messages == 0 and not is_admin(user_id):
            remaining_time = get_remaining_time(user_id)
            await update.message.reply_text(
                f"⚠️ {first_name}، شما ۵ پیام خود را استفاده کردید.\n\n"
                f"⏳ زمان باقی‌مانده: {format_time(remaining_time)}\n\n"
                "@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
            )
        elif remaining_messages > 0 and not is_admin(user_id):
            await update.message.reply_text(
                f"📊 پیام‌های باقی‌مانده: {remaining_messages}/5\n\n"
                "@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
            )
        
    except Exception as e:
        logger.error(f"خطا در پردازش پیام: {str(e)}")
        await update.message.reply_text(
            f"❌ خطا در پردازش پیام: {str(e)}\n\n"
            "لطفاً دوباره تلاش کنید.\n\n"
            "@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار ربات (فقط ادمین)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ فقط ادمین‌ها دسترسی دارند!")
        return
    
    total_users = len(user_messages)
    active_users = sum(1 for msgs in user_messages.values() if msgs)
    
    stats_text = f"""
📊 آمار ربات:

👥 کل کاربران: {total_users}
🟢 کاربران فعال: {active_users}
⚡ ادمین‌ها: {len(ADMIN_IDS)}

@AnishtaYiN 
🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن
"""
    
    await update.message.reply_text(stats_text)

async def reset_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ریست کردن محدودیت کاربر (فقط ادمین)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ فقط ادمین‌ها دسترسی دارند!")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❌ استفاده: /reset [user_id]")
        return
    
    try:
        target_user_id = int(context.args[0])
        if target_user_id in user_messages:
            user_messages[target_user_id] = []
            save_user_data()
            await update.message.reply_text(f"✅ محدودیت کاربر {target_user_id} ریست شد!")
        else:
            await update.message.reply_text("❌ کاربر یافت نشد!")
    except ValueError:
        await update.message.reply_text("❌ آیدی کاربر باید عددی باشد!")

def main():
    """راه‌اندازی ربات"""
    # بارگذاری داده‌های کاربران
    load_user_data()
    
    # ایجاد اپلیکیشن
    application = Application.builder().token(BOT_TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("reset", reset_user_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # راه‌اندازی ربات
    print("🤖 ربات شروع شد...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()