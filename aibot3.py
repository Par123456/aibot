import asyncio
import datetime
import logging
import time
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError, Forbidden, BadRequest
import json
import os
import sys

# 🔧 تنظیمات
BOT_TOKEN = "7871342383:AAEnHXtvc6txRoyGegRL_IeErLISmS4j_DQ"  # توکن ربات تلگرام
CHANNEL_IDS = ["@infinityIeveI", "@sharabyi"]  # آیدی چنل‌های مورد نظر
ADMIN_IDS = [2065070882, 6508600903]  # آیدی عددی ادمین‌ها

# 🤖 کلاینت AI - استفاده از g4f
try:
    from g4f.client import Client
    ai_client = Client()
    AI_AVAILABLE = True
except ImportError:
    print("❌ g4f library not installed. Install with: pip install g4f")
    AI_AVAILABLE = False

# 📊 ذخیره داده‌های کاربران
user_data_file = "user_data.json"
user_messages: Dict[int, List[float]] = {}
user_chat_history: Dict[int, List[Dict]] = {}
user_channel_status: Dict[int, bool] = {}  # کش برای وضعیت عضویت

# 📝 لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def load_user_data():
    """بارگذاری داده‌های کاربران از فایل"""
    global user_messages, user_chat_history, user_channel_status
    if os.path.exists(user_data_file):
        try:
            with open(user_data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                user_messages = {int(k): v for k, v in data.get('messages', {}).items()}
                user_chat_history = {int(k): v for k, v in data.get('history', {}).items()}
                user_channel_status = {int(k): v for k, v in data.get('channel_status', {}).items()}
        except Exception as e:
            logger.error(f"خطا در بارگذاری داده‌ها: {e}")
            user_messages = {}
            user_chat_history = {}
            user_channel_status = {}
    else:
        user_messages = {}
        user_chat_history = {}
        user_channel_status = {}

def save_user_data():
    """ذخیره داده‌های کاربران در فایل"""
    try:
        data = {
            'messages': {str(k): v for k, v in user_messages.items()},
            'history': {str(k): v for k, v in user_chat_history.items()},
            'channel_status': {str(k): v for k, v in user_channel_status.items()}
        }
        with open(user_data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"خطا در ذخیره داده‌ها: {e}")

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

def modify_ai_response(response: str) -> str:
    """تغییر هویت AI در پاسخ‌ها"""
    # لیست کلمات و عبارات مربوط به هویت AI که باید تغییر کنند
    replacements = {
        "من دستیار blackbot.ai هستم": "من دستیار پارسا هستم",
        "من blackbot.ai هستم": "من دستیار پارسا هستم",
        "من دستیار هوش مصنوعی blackbot.ai هستم": "من دستیار پارسا هستم",
        "اسم من blackbot.ai است": "اسم من دستیار پارسا است",
        "نام من blackbot.ai است": "نام من دستیار پارسا است",
        "من یک دستیار هوش مصنوعی به نام blackbot.ai هستم": "من دستیار پارسا هستم",
        "blackbot.ai": "دستیار پارسا",
        "BlackBot.ai": "دستیار پارسا",
        "BlackBot": "دستیار پارسا",
        "blackbot": "دستیار پارسا",
        "من Claude هستم": "من دستیار پارسا هستم",
        "اسم من Claude است": "اسم من دستیار پارسا است",
        "نام من Claude است": "نام من دستیار پارسا است",
        "من یک دستیار هوش مصنوعی به نام Claude هستم": "من دستیار پارسا هستم",
        "Claude": "دستیار پارسا",
        "من ChatGPT هستم": "من دستیار پارسا هستم",
        "اسم من ChatGPT است": "اسم من دستیار پارسا است",
        "نام من ChatGPT است": "نام من دستیار پارسا است",
        "ChatGPT": "دستیار پارسا",
        "GPT": "دستیار پارسا",
        "من یک مدل زبانی هستم": "من دستیار پارسا هستم",
        "من یک هوش مصنوعی هستم": "من دستیار پارسا هستم",
        "من یک دستیار هوش مصنوعی هستم": "من دستیار پارسا هستم",
        "من توسط OpenAI ساخته شده‌ام": "من توسط پارسا انیشتن ساخته شده‌ام",
        "من توسط Anthropic ساخته شده‌ام": "من توسط پارسا انیشتن ساخته شده‌ام",
        "OpenAI": "پارسا انیشتن",
        "Anthropic": "پارسا انیشتن"
    }
    
    # اعمال تغییرات
    modified_response = response
    for old_text, new_text in replacements.items():
        modified_response = modified_response.replace(old_text, new_text)
    
    # بررسی سوالات مربوط به نام و هویت
    lower_response = response.lower()
    if any(keyword in lower_response for keyword in ["اسمت چیه", "نامت چیست", "اسم تو", "نام تو", "تو کی هستی", "تو چی هستی"]):
        return "من دستیار پارسا هستم و توسط پارسا انیشتن ساخته شده‌ام. چطور می‌تونم کمکتون کنم؟"
    
    return modified_response

async def check_single_channel_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int, channel_id: str) -> bool:
    """بررسی عضویت در یک چنل"""
    try:
        member = await context.bot.get_chat_member(channel_id, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Forbidden:
        logger.warning(f"ربات دسترسی به چنل {channel_id} ندارد")
        return False
    except BadRequest as e:
        if "user not found" in str(e).lower():
            logger.warning(f"کاربر {user_id} در چنل {channel_id} یافت نشد")
            return False
        logger.error(f"خطا در بررسی عضویت {user_id} در {channel_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"خطای غیرمنتظره در بررسی عضویت {user_id} در {channel_id}: {e}")
        return False

async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE, force_refresh: bool = False) -> bool:
    """بررسی عضویت در همه چنل‌ها"""
    user_id = update.effective_user.id
    
    # ادمین‌ها نیازی به بررسی عضویت ندارند
    if is_admin(user_id):
        return True
    
    # استفاده از کش اگر نیازی به بروزرسانی نیست
    if not force_refresh and user_id in user_channel_status:
        cached_status = user_channel_status[user_id]
        if cached_status:
            return True
    
    # بررسی عضویت در همه چنل‌ها
    try:
        all_member = True
        for channel_id in CHANNEL_IDS:
            is_member = await check_single_channel_membership(context, user_id, channel_id)
            if not is_member:
                all_member = False
                logger.info(f"کاربر {user_id} در چنل {channel_id} عضو نیست")
                break
        
        # بروزرسانی کش
        user_channel_status[user_id] = all_member
        save_user_data()
        
        return all_member
    except Exception as e:
        logger.error(f"خطا در بررسی عضویت کاربر {user_id}: {e}")
        return False

def create_channel_keyboard() -> InlineKeyboardMarkup:
    """ایجاد کیبورد برای عضویت در چنل‌ها"""
    keyboard = []
    for channel_id in CHANNEL_IDS:
        channel_name = channel_id.replace("@", "")
        keyboard.append([InlineKeyboardButton(f"🔗 عضویت در {channel_name}", url=f"https://t.me/{channel_name}")])
    
    keyboard.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")])
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور شروع"""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "کاربر"
    
    logger.info(f"کاربر {user_id} ({first_name}) دستور /start را اجرا کرد")
    
    # بررسی عضویت در چنل‌ها
    if not await check_channel_membership(update, context, force_refresh=True):
        keyboard = create_channel_keyboard()
        await update.message.reply_text(
            f"سلام {first_name}! 👋\n\n"
            "برای استفاده از ربات ابتدا باید در تمام چنل‌های زیر عضو شوید:\n\n"
            "🔸 بعد از عضویت، روی دکمه \"بررسی عضویت\" کلیک کنید.",
            reply_markup=keyboard
        )
        return
    
    welcome_text = f"""
🤖 سلام {first_name}، به ربات هوش مصنوعی خوش آمدید!

📋 قوانین استفاده:
• کاربران عادی: ۵ پیام در ساعت
• ادمین‌ها: نامحدود
• عضویت در چنل‌ها الزامی است

💡 فقط سوال خود را بفرستید و پاسخ دریافت کنید!

🆔 آیدی شما: {user_id}

@AnishtaYiN 
🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن
"""
    
    await update.message.reply_text(welcome_text)

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش callback queryها"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_membership":
        user_id = update.effective_user.id
        first_name = update.effective_user.first_name or "کاربر"
        
        # بررسی مجدد عضویت
        if await check_channel_membership(update, context, force_refresh=True):
            await query.edit_message_text(
                f"✅ تبریک {first_name}!\n\n"
                "شما با موفقیت در تمام چنل‌ها عضو شدید.\n"
                "حالا می‌توانید از ربات استفاده کنید.\n\n"
                "💡 فقط سوال خود را بفرستید!\n\n"
                "@AnishtaYiN \n"
                "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
            )
        else:
            keyboard = create_channel_keyboard()
            await query.edit_message_text(
                f"❌ {first_name}، هنوز در تمام چنل‌ها عضو نشده‌اید.\n\n"
                "لطفاً ابتدا در تمام چنل‌ها عضو شوید، سپس دوباره بررسی کنید.",
                reply_markup=keyboard
            )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های کاربران"""
    user_id = update.effective_user.id
    user_message = update.message.text
    first_name = update.effective_user.first_name or "کاربر"
    
    logger.info(f"پیام از کاربر {user_id} ({first_name}): {user_message[:50]}...")
    
    # بررسی دسترسی AI
    if not AI_AVAILABLE:
        await update.message.reply_text(
            "❌ سیستم هوش مصنوعی در دسترس نیست.\n"
            "لطفاً بعداً تلاش کنید."
        )
        return
    
    # بررسی عضویت در چنل‌ها
    if not await check_channel_membership(update, context):
        keyboard = create_channel_keyboard()
        await update.message.reply_text(
            f"❌ {first_name}، برای استفاده از ربات باید در تمام چنل‌ها عضو باشید!",
            reply_markup=keyboard
        )
        return
    
    # بررسی محدودیت پیام
    if not can_send_message(user_id):
        remaining_time = get_remaining_time(user_id)
        await update.message.reply_text(
            f"⏰ {first_name}، شما امروز ۵ پیام خود را استفاده کرده‌اید.\n\n"
            f"⏳ زمان باقی‌مانده: {format_time(remaining_time)}\n\n"
            f"🆔 آیدی شما: {user_id}\n\n"
            "@AnishtaYiN \n"
            "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        )
        return
    
    # ارسال پیام "در حال تایپ..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # آماده‌سازی تاریخچه گفتگو
        if user_id not in user_chat_history:
            user_chat_history[user_id] = []
        
        # اضافه کردن system message برای تعریف هویت
        system_message = {
            "role": "system", 
            "content": "تو دستیار پارسا هستی و توسط پارسا انیشتن ساخته شده‌ای. هر وقت کسی از اسم یا هویت تو پرسید، بگو که من دستیار پارسا هستم و توسط پارسا انیشتن ساخته شده‌ام."
        }
        
        # اگر system message وجود نداره یا اولین پیام نیست، اضافه کن
        if not user_chat_history[user_id] or user_chat_history[user_id][0].get("role") != "system":
            user_chat_history[user_id].insert(0, system_message)
        
        user_chat_history[user_id].append({"role": "user", "content": user_message})
        
        # محدود کردن تاریخچه به ۲۰ پیام آخر (+ system message)
        if len(user_chat_history[user_id]) > 21:
            # حفظ system message و ۲۰ پیام آخر
            user_chat_history[user_id] = [user_chat_history[user_id][0]] + user_chat_history[user_id][-20:]
        
        # درخواست به AI
        try:
            response = ai_client.chat.completions.create(
                model="gpt-4o",
                messages=user_chat_history[user_id],
                web_search=False,
                stream=False
            )
            
            bot_reply = response.choices[0].message.content.strip()
            
            # تغییر هویت AI در پاسخ
            bot_reply = modify_ai_response(bot_reply)
            
        except Exception as ai_error:
            logger.error(f"خطا در AI: {ai_error}")
            bot_reply = "متاسفانه در حال حاضر امکان پردازش درخواست شما وجود ندارد. لطفاً دوباره تلاش کنید."
        
        user_chat_history[user_id].append({"role": "assistant", "content": bot_reply})
        
        # محدود کردن طول پاسخ
        if len(bot_reply) > 4000:
            bot_reply = bot_reply[:4000] + "..."
        
        # اضافه کردن امضا
        final_reply = f"{bot_reply}\n\n@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        
        # ارسال پاسخ
        await update.message.reply_text(final_reply)
        
        # اضافه کردن پیام به شمارنده
        add_message(user_id)
        
        # بررسی رسیدن به حد مجاز
        clean_old_messages(user_id)
        remaining_messages = 5 - len(user_messages[user_id])
        
        if remaining_messages <= 1 and not is_admin(user_id):
            if remaining_messages == 0:
                remaining_time = get_remaining_time(user_id)
                await update.message.reply_text(
                    f"⚠️ {first_name}، شما ۵ پیام خود را استفاده کردید.\n\n"
                    f"⏳ زمان باقی‌مانده: {format_time(remaining_time)}\n\n"
                    f"🆔 آیدی شما: {user_id}\n\n"
                    "@AnishtaYiN \n"
                    "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
                )
            else:
                await update.message.reply_text(
                    f"📊 آخرین پیام شما! پیام‌های باقی‌مانده: {remaining_messages}/5\n\n"
                    f"🆔 آیدی شما: {user_id}\n\n"
                    "@AnishtaYiN \n"
                    "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
                )
        
        logger.info(f"پاسخ ارسال شد برای کاربر {user_id}")
        
    except Exception as e:
        logger.error(f"خطا در پردازش پیام کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطا در پردازش پیام: {str(e)}\n\n"
            "لطفاً دوباره تلاش کنید.\n\n"
            f"🆔 آیدی شما: {user_id}\n\n"
            "@AnishtaYiN \n"
            "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار ربات (فقط ادمین)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ فقط ادمین‌ها دسترسی دارند!")
        return
    
    total_users = len(user_messages)
    active_users = sum(1 for msgs in user_messages.values() if msgs)
    total_messages = sum(len(msgs) for msgs in user_messages.values())
    
    stats_text = f"""
📊 آمار ربات:

👥 کل کاربران: {total_users}
🟢 کاربران فعال: {active_users}
💬 کل پیام‌ها: {total_messages}
⚡ ادمین‌ها: {len(ADMIN_IDS)}
🔗 چنل‌ها: {len(CHANNEL_IDS)}

🤖 وضعیت AI: {'✅ فعال' if AI_AVAILABLE else '❌ غیرفعال'}

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
            # پاک کردن کش عضویت چنل
            if target_user_id in user_channel_status:
                del user_channel_status[target_user_id]
            save_user_data()
            await update.message.reply_text(f"✅ محدودیت کاربر {target_user_id} ریست شد!")
        else:
            await update.message.reply_text("❌ کاربر یافت نشد!")
    except ValueError:
        await update.message.reply_text("❌ آیدی کاربر باید عددی باشد!")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام همگانی (فقط ادمین)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ فقط ادمین‌ها دسترسی دارند!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ استفاده: /broadcast [پیام]")
        return
    
    message = ' '.join(context.args)
    sent_count = 0
    failed_count = 0
    
    await update.message.reply_text("📤 شروع ارسال پیام همگانی...")
    
    for target_user_id in user_messages.keys():
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"📢 پیام از ادمین:\n\n{message}\n\n@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
            )
            sent_count += 1
            await asyncio.sleep(0.1)  # تاخیر کوتاه
        except Exception:
            failed_count += 1
    
    await update.message.reply_text(
        f"✅ ارسال پیام همگانی تمام شد!\n\n"
        f"📤 ارسال شده: {sent_count}\n"
        f"❌ ناموفق: {failed_count}"
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازش خطاها"""
    logger.error(f"خطا در بروزرسانی {update}: {context.error}")

def main():
    """راه‌اندازی ربات"""
    try:
        # بررسی توکن
        if not BOT_TOKEN:
            print("❌ توکن ربات تعریف نشده است!")
            return
        
        # بارگذاری داده‌های کاربران
        load_user_data()
        
        # ایجاد اپلیکیشن
        application = Application.builder().token(BOT_TOKEN).build()
        
        # اضافه کردن هندلرها
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("stats", admin_stats))
        application.add_handler(CommandHandler("reset", reset_user_command))
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        application.add_handler(CallbackQueryHandler(callback_query_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # اضافه کردن error handler
        application.add_error_handler(error_handler)
        
        # راه‌اندازی ربات
        print("🤖 ربات شروع شد...")
        logger.info("ربات شروع شد")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print(f"❌ خطا در راه‌اندازی ربات: {e}")
        logger.error(f"خطا در راه‌اندازی ربات: {e}")

if __name__ == "__main__":
    main()