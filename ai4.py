import asyncio
import datetime
import logging
import time
import json
import os
import sys
from typing import Dict, List, Optional, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError, Forbidden, BadRequest, NetworkError, TimedOut
import threading
from contextlib import asynccontextmanager
import aiohttp
import base64

# 🔧 تنظیمات
BOT_TOKEN = "7871342383:AAEnHXtvc6txRoyGegRL_IeErLISmS4j_DQ"  # توکن ربات تلگرام
CHANNEL_IDS = ["infinityIeveI", "golden_market7"]  # آیدی چنل‌های مورد نظر
ADMIN_IDS = [2065070882, 6508600903]  # آیدی عددی ادمین‌ها

# 🤖 کلاینت AI - استفاده از g4f
AI_AVAILABLE = False
ai_client = None

try:
    from g4f.client import Client
    ai_client = Client()
    AI_AVAILABLE = True
    print("✅ g4f library loaded successfully")
except ImportError:
    print("❌ g4f library not installed. Install with: pip install g4f")
    AI_AVAILABLE = False
except Exception as e:
    print(f"❌ Error loading g4f: {e}")
    AI_AVAILABLE = False

# 📊 ذخیره داده‌های کاربران
USER_DATA_FILE = "user_data.json"
user_messages: Dict[int, List[float]] = {}
user_chat_history: Dict[int, List[Dict[str, str]]] = {}
user_channel_status: Dict[int, bool] = {}  # کش برای وضعیت عضویت
user_mode: Dict[int, str] = {}  # حالت کاربر: home, text_ai, image_gen
data_lock = threading.Lock()

# 📝 تنظیمات لاگ
def setup_logging():
    """تنظیم سیستم لاگ"""
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        handlers=[
            logging.FileHandler('bot.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# 🔒 مدیریت امن فایل
def safe_file_operation(operation_func, *args, **kwargs):
    """عملیات امن روی فایل با قفل"""
    with data_lock:
        try:
            return operation_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"خطا در عملیات فایل: {e}")
            return None

def load_user_data():
    """بارگذاری امن داده‌های کاربران از فایل"""
    global user_messages, user_chat_history, user_channel_status, user_mode
    
    def _load():
        if os.path.exists(USER_DATA_FILE):
            try:
                with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # اعتبارسنجی داده‌ها
                if not isinstance(data, dict):
                    raise ValueError("فرمت داده نامعتبر")
                
                user_messages = {int(k): v for k, v in data.get('messages', {}).items() if isinstance(v, list)}
                user_chat_history = {int(k): v for k, v in data.get('history', {}).items() if isinstance(v, list)}
                user_channel_status = {int(k): v for k, v in data.get('channel_status', {}).items() if isinstance(v, bool)}
                user_mode = {int(k): v for k, v in data.get('user_mode', {}).items() if isinstance(v, str)}
                
                logger.info(f"داده‌های {len(user_messages)} کاربر بارگذاری شد")
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"خطا در خواندن فایل داده: {e}")
                # ایجاد بک‌آپ از فایل خراب
                if os.path.exists(USER_DATA_FILE):
                    backup_name = f"{USER_DATA_FILE}.backup.{int(time.time())}"
                    os.rename(USER_DATA_FILE, backup_name)
                    logger.info(f"بک‌آپ ایجاد شد: {backup_name}")
                # مقداردهی اولیه
                user_messages = {}
                user_chat_history = {}
                user_channel_status = {}
                user_mode = {}
        else:
            user_messages = {}
            user_chat_history = {}
            user_channel_status = {}
            user_mode = {}
    
    safe_file_operation(_load)

def save_user_data():
    """ذخیره امن داده‌های کاربران در فایل"""
    def _save():
        try:
            data = {
                'messages': {str(k): v for k, v in user_messages.items()},
                'history': {str(k): v for k, v in user_chat_history.items()},
                'channel_status': {str(k): v for k, v in user_channel_status.items()},
                'user_mode': {str(k): v for k, v in user_mode.items()}
            }
            
            # ذخیره در فایل موقت ابتدا
            temp_file = f"{USER_DATA_FILE}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # جایگزینی فایل اصلی
            if os.path.exists(USER_DATA_FILE):
                os.replace(temp_file, USER_DATA_FILE)
            else:
                os.rename(temp_file, USER_DATA_FILE)
                
        except Exception as e:
            logger.error(f"خطا در ذخیره داده‌ها: {e}")
            # پاک کردن فایل موقت در صورت خطا
            temp_file = f"{USER_DATA_FILE}.tmp"
            if os.path.exists(temp_file):
                os.remove(temp_file)
    
    safe_file_operation(_save)

# 🔐 مدیریت دسترسی
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
    # ذخیره به صورت async تا عملکرد بهتر باشد
    asyncio.create_task(async_save_data())

async def async_save_data():
    """ذخیره غیرهمزمان داده‌ها"""
    await asyncio.get_event_loop().run_in_executor(None, save_user_data)

def format_time(seconds: int) -> str:
    """فرمت کردن زمان به دقیقه و ثانیه"""
    if seconds <= 0:
        return "0:00"
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}:{seconds:02d}"

# 🎭 تغییر هویت AI
def modify_ai_response(response: str) -> str:
    """تغییر هویت AI در پاسخ‌ها"""
    if not response or not isinstance(response, str):
        return "متاسفانه نمی‌توانم در حال حاضر پاسخ دهم."
    
    # لیست کلمات و عبارات مربوط به هویت AI که باید تغییر کنند
    replacements = {
        "من یک مدل هوش مصنوعی هستم و نام خاصی ندارم، اما می‌توانید من را \"BLACKBOX.AI Assistant\" یا هر نام دیگری که دوست دارید صدا بزنید. هدف من کمک به شما و پاسخ به سوالاتتان است! اگر سوال دیگری دارید، خوشحال می‌شوم کمک کنم.": "من دستیار پارسا هستم",
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
        "Anthropic": "پارسا انیشتن",
        "GPT-4": "دستیار پارسا",
        "GPT-3": "دستیار پارسا"
    }
    
    # اعمال تغییرات
    modified_response = response
    for old_text, new_text in replacements.items():
        modified_response = modified_response.replace(old_text, new_text)
    
    # بررسی سوالات مربوط به نام و هویت
    lower_response = response.lower()
    identity_keywords = ["اسمت چیه", "نامت چیست", "اسم تو", "نام تو", "تو کی هستی", "تو چی هستی", "شما کی هستید"]
    
    if any(keyword in lower_response for keyword in identity_keywords):
        return "من دستیار پارسا هستم و توسط پارسا انیشتن ساخته شده‌ام. چطور می‌تونم کمکتون کنم؟"
    
    return modified_response

# 🔍 بررسی عضویت در چنل‌ها
async def check_single_channel_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int, channel_id: str) -> bool:
    """بررسی عضویت در یک چنل"""
    try:
        # اضافه کردن @ اگر وجود نداشته باشد
        if not channel_id.startswith('@'):
            channel_id = f"@{channel_id}"
        
        member = await context.bot.get_chat_member(channel_id, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Forbidden:
        logger.warning(f"ربات دسترسی به چنل {channel_id} ندارد")
        return False
    except BadRequest as e:
        if "user not found" in str(e).lower():
            logger.warning(f"کاربر {user_id} در چنل {channel_id} یافت نشد - احتمالاً عضو نیست")
            return False
        elif "chat not found" in str(e).lower():
            logger.error(f"چنل {channel_id} یافت نشد - آیدی چنل اشتباه است")
            return False
        logger.error(f"خطا در بررسی عضویت {user_id} در {channel_id}: {e}")
        return False
    except (NetworkError, TimedOut) as e:
        logger.warning(f"مشکل شبکه در بررسی عضویت {user_id} در {channel_id}: {e}")
        # در صورت مشکل شبکه، اجازه دسترسی بده تا کاربر مشکل نداشته باشد
        return True
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
        membership_checks = []
        for channel_id in CHANNEL_IDS:
            membership_checks.append(check_single_channel_membership(context, user_id, channel_id))
        
        # اجرای همزمان بررسی‌ها
        results = await asyncio.gather(*membership_checks, return_exceptions=True)
        
        all_member = True
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"خطا در بررسی عضویت در چنل {CHANNEL_IDS[i]}: {result}")
                all_member = False
                break
            elif not result:
                logger.info(f"کاربر {user_id} در چنل {CHANNEL_IDS[i]} عضو نیست")
                all_member = False
                break
        
        # بروزرسانی کش
        user_channel_status[user_id] = all_member
        await async_save_data()
        
        return all_member
        
    except Exception as e:
        logger.error(f"خطا در بررسی عضویت کاربر {user_id}: {e}")
        return False

# 🎹 کیبورد و UI
def create_channel_keyboard() -> InlineKeyboardMarkup:
    """ایجاد کیبورد برای عضویت در چنل‌ها"""
    keyboard = []
    for channel_id in CHANNEL_IDS:
        channel_name = channel_id.replace("@", "")
        keyboard.append([InlineKeyboardButton(f"🔗 عضویت در {channel_name}", url=f"https://t.me/{channel_name}")])
    
    keyboard.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")])
    return InlineKeyboardMarkup(keyboard)

def create_main_menu_keyboard() -> InlineKeyboardMarkup:
    """ایجاد کیبورد منوی اصلی"""
    keyboard = [
        [InlineKeyboardButton("💬 هوش مصنوعی متنی", callback_data="text_ai")],
        [InlineKeyboardButton("🎨 هوش مصنوعی تولید عکس", callback_data="image_gen")],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_back_keyboard() -> InlineKeyboardMarkup:
    """ایجاد کیبورد بازگشت"""
    keyboard = [
        [InlineKeyboardButton("🏠 بازگشت به خانه", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

# 🖼️ تولید عکس
async def generate_image(prompt: str) -> Optional[str]:
    """تولید عکس با g4f"""
    if not AI_AVAILABLE or not ai_client:
        return None
    
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ai_client.images.generate(
                model="flux",
                prompt=prompt,
                response_format="url"
            )
        )
        
        if response and response.data and len(response.data) > 0:
            return response.data[0].url
        return None
        
    except Exception as e:
        logger.error(f"خطا در تولید عکس: {e}")
        return None

async def download_image(url: str) -> Optional[bytes]:
    """دانلود عکس از URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.read()
        return None
    except Exception as e:
        logger.error(f"خطا در دانلود عکس: {e}")
        return None

# 👁️ پردازش تصویر
async def process_image_with_ai(image_data: bytes, user_message: str) -> str:
    """پردازش تصویر با AI"""
    if not AI_AVAILABLE or not ai_client:
        return "❌ سیستم پردازش تصویر در دسترس نیست."
    
    try:
        # تبدیل تصویر به base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # ساخت پیام برای AI
        messages = [
            {
                "role": "user",
                "content": f"تصویر: data:image/jpeg;base64,{image_base64}\n\nپیام: {user_message}"
            }
        ]
        
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                stream=False
            )
        )
        
        if response and response.choices:
            bot_reply = response.choices[0].message.content.strip()
            return modify_ai_response(bot_reply)
        else:
            return "متاسفانه نمی‌توانم تصویر را تحلیل کنم."
            
    except Exception as e:
        logger.error(f"خطا در پردازش تصویر: {e}")
        return "متاسفانه در حال حاضر امکان تحلیل تصویر وجود ندارد."

# 🎯 دستورات ربات
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور شروع"""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "کاربر"
    
    logger.info(f"کاربر {user_id} ({first_name}) دستور /start را اجرا کرد")
    
    try:
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
        
        # تنظیم حالت کاربر به خانه
        user_mode[user_id] = "home"
        await async_save_data()
        
        welcome_text = f"""
🤖 سلام {first_name}، به ربات هوش مصنوعی خوش آمدید!

📋 قوانین استفاده:
• کاربران عادی: ۵ پیام در ساعت
• ادمین‌ها: نامحدود
• عضویت در چنل‌ها الزامی است

🔧 دستورات مفید:
• /resetchat - ریست کردن مکالمه

🆔 آیدی شما: {user_id}

لطفاً یکی از گزینه‌های زیر را انتخاب کنید:

@AnishtaYiN 
🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن
"""
        
        keyboard = create_main_menu_keyboard()
        await update.message.reply_text(welcome_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"خطا در دستور start برای کاربر {user_id}: {e}")
        await update.message.reply_text(
            "❌ خطا در راه‌اندازی ربات. لطفاً دوباره تلاش کنید."
        )

async def resetchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ریست کردن مکالمه کاربر"""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "کاربر"
    
    try:
        # پاک کردن تاریخچه مکالمه
        if user_id in user_chat_history:
            user_chat_history[user_id] = []
        
        # تنظیم حالت کاربر به خانه
        user_mode[user_id] = "home"
        await async_save_data()
        
        keyboard = create_main_menu_keyboard()
        await update.message.reply_text(
            f"✅ {first_name}، مکالمه شما ریست شد!\n\n"
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
            "@AnishtaYiN \n"
            "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"خطا در ریست چت کاربر {user_id}: {e}")
        await update.message.reply_text("❌ خطا در ریست کردن مکالمه!")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش callback queryها"""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    
    try:
        await query.answer()
        user_id = update.effective_user.id
        first_name = update.effective_user.first_name or "کاربر"
        
        if query.data == "check_membership":
            # بررسی مجدد عضویت
            if await check_channel_membership(update, context, force_refresh=True):
                user_mode[user_id] = "home"
                await async_save_data()
                
                keyboard = create_main_menu_keyboard()
                await query.edit_message_text(
                    f"✅ تبریک {first_name}!\n\n"
                    "شما با موفقیت در تمام چنل‌ها عضو شدید.\n"
                    "حالا می‌توانید از ربات استفاده کنید.\n\n"
                    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
                    "@AnishtaYiN \n"
                    "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن",
                    reply_markup=keyboard
                )
            else:
                keyboard = create_channel_keyboard()
                await query.edit_message_text(
                    f"❌ {first_name}، هنوز در تمام چنل‌ها عضو نشده‌اید.\n\n"
                    "لطفاً ابتدا در تمام چنل‌ها عضو شوید، سپس دوباره بررسی کنید.",
                    reply_markup=keyboard
                )
        
        elif query.data == "text_ai":
            user_mode[user_id] = "text_ai"
            await async_save_data()
            
            keyboard = create_back_keyboard()
            await query.edit_message_text(
                f"💬 {first_name}، شما در حالت هوش مصنوعی متنی هستید.\n\n"
                "🔸 متن یا سوال خود را بفرستید\n"
                "🔸 می‌توانید تصویر همراه با متن بفرستید\n"
                "🔸 برای ریست کردن مکالمه: /resetchat\n\n"
                "@AnishtaYiN \n"
                "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن",
                reply_markup=keyboard
            )
        
        elif query.data == "image_gen":
            user_mode[user_id] = "image_gen"
            await async_save_data()
            
            keyboard = create_back_keyboard()
            await query.edit_message_text(
                f"🎨 {first_name}، شما در حالت تولید عکس هستید.\n\n"
                "🔸 توضیحات عکسی که می‌خواهید را بفرستید\n"
                "🔸 مثال: \"یک گربه سفید در باغ\"\n"
                "🔸 بهتر است توضیحات را به انگلیسی بفرستید\n\n"
                "@AnishtaYiN \n"
                "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن",
                reply_markup=keyboard
            )
        
        elif query.data == "back_home":
            user_mode[user_id] = "home"
            await async_save_data()
            
            keyboard = create_main_menu_keyboard()
            await query.edit_message_text(
                f"🏠 {first_name}، به خانه برگشتید.\n\n"
                "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
                "@AnishtaYiN \n"
                "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن",
                reply_markup=keyboard
            )
                
    except Exception as e:
        logger.error(f"خطا در callback query handler: {e}")
        try:
            await query.answer("❌ خطا در پردازش درخواست", show_alert=True)
        except:
            pass

# 🤖 پردازش پیام‌های AI
async def get_ai_response(user_history: List[Dict[str, str]], user_message: str) -> str:
    """دریافت پاسخ از AI"""
    if not AI_AVAILABLE or not ai_client:
        return "❌ سیستم هوش مصنوعی در دسترس نیست."
    
    try:
        # آماده‌سازی پیام‌ها
        messages = user_history.copy()
        messages.append({"role": "user", "content": user_message})
        
        # درخواست به AI
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                web_search=False,
                stream=False
            )
        )
        
        if response and response.choices:
            bot_reply = response.choices[0].message.content.strip()
            return modify_ai_response(bot_reply)
        else:
            return "متاسفانه نمی‌توانم در حال حاضر پاسخ دهم."
            
    except Exception as e:
        logger.error(f"خطا در AI: {e}")
        return "متاسفانه در حال حاضر امکان پردازش درخواست شما وجود ندارد. لطفاً دوباره تلاش کنید."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های کاربران"""
    if not update.effective_user or not update.message:
        return
    
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "کاربر"
    
    # بررسی حالت کاربر
    current_mode = user_mode.get(user_id, "home")
    
    if current_mode == "home":
        keyboard = create_main_menu_keyboard()
        await update.message.reply_text(
            f"🏠 {first_name}، لطفاً ابتدا یکی از گزینه‌ها را انتخاب کنید:\n\n"
            "@AnishtaYiN \n"
            "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن",
            reply_markup=keyboard
        )
        return
    
    logger.info(f"پیام از کاربر {user_id} ({first_name}) در حالت {current_mode}")
    
    try:
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
        
        if current_mode == "text_ai":
            await handle_text_ai_message(update, context, user_id, first_name)
        elif current_mode == "image_gen":
            await handle_image_gen_message(update, context, user_id, first_name)
        
    except Exception as e:
        logger.error(f"خطا در پردازش پیام کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطا در پردازش پیام: {str(e)}\n\n"
            "لطفاً دوباره تلاش کنید.\n\n"
            f"🆔 آیدی شما: {user_id}\n\n"
            "@AnishtaYiN \n"
            "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        )

async def handle_text_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, first_name: str):
    """پردازش پیام در حالت هوش مصنوعی متنی"""
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
        
        # محدود کردن تاریخچه به ۲۰ پیام آخر (+ system message)
        if len(user_chat_history[user_id]) > 21:
            # حفظ system message و ۲۰ پیام آخر
            user_chat_history[user_id] = [user_chat_history[user_id][0]] + user_chat_history[user_id][-20:]
        
        # بررسی وجود تصویر
        if update.message.photo:
            # دانلود تصویر
            photo = update.message.photo[-1]  # بزرگترین سایز
            file = await context.bot.get_file(photo.file_id)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(file.file_path) as response:
                    image_data = await response.read()
            
            # متن همراه تصویر
            user_message = update.message.caption or "این تصویر را تحلیل کن"
            
            # پردازش تصویر با AI
            bot_reply = await process_image_with_ai(image_data, user_message)
        else:
            # پردازش پیام متنی
            user_message = update.message.text.strip()
            
            # بررسی طول پیام
            if len(user_message) > 1000:
                await update.message.reply_text(
                    "❌ پیام شما بیش از حد طولانی است. لطفاً پیام کوتاه‌تری ارسال کنید."
                )
                return
            
            # دریافت پاسخ AI
            bot_reply = await get_ai_response(user_chat_history[user_id], user_message)
            
            # اضافه کردن پیام‌ها به تاریخچه
            user_chat_history[user_id].append({"role": "user", "content": user_message})
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
        
        logger.info(f"پاسخ متنی ارسال شد برای کاربر {user_id}")
        
    except Exception as e:
        logger.error(f"خطا در پردازش پیام متنی: {e}")
        raise

async def handle_image_gen_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, first_name: str):
    """پردازش پیام در حالت تولید عکس"""
    try:
        if not update.message.text:
            await update.message.reply_text(
                "❌ لطفاً توضیحات عکسی که می‌خواهید را بفرستید.\n\n"
                "@AnishtaYiN \n"
                "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
            )
            return
        
        user_prompt = update.message.text.strip()
        
        # بررسی طول پرامپت
        if len(user_prompt) > 500:
            await update.message.reply_text(
                "❌ توضیحات شما بیش از حد طولانی است. لطفاً توضیحات کوتاه‌تری ارسال کنید."
            )
            return
        
        # ارسال پیام انتظار
        wait_message = await update.message.reply_text(
            "🎨 در حال تولید عکس...\nلطفاً صبر کنید، این ممکن است چند لحظه طول بکشد."
        )
        
        # تولید عکس
        image_url = await generate_image(user_prompt)
        
        if not image_url:
            await wait_message.edit_text(
                "❌ متاسفانه نتوانستم عکس را تولید کنم. لطفاً دوباره تلاش کنید.\n\n"
                "@AnishtaYiN \n"
                "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
            )
            return
        
        # دانلود عکس
        image_data = await download_image(image_url)
        
        if not image_data:
            await wait_message.edit_text(
                "❌ متاسفانه نتوانستم عکس را دانلود کنم. لطفاً دوباره تلاش کنید.\n\n"
                "@AnishtaYiN \n"
                "🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
            )
            return
        
        # ارسال عکس
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=image_data,
            caption=f"🎨 عکس تولید شده برای: {user_prompt}\n\n@AnishtaYiN \n🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن"
        )
        
        # حذف پیام انتظار
        try:
            await wait_message.delete()
        except:
            pass
        
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
        
        logger.info(f"عکس تولید و ارسال شد برای کاربر {user_id}")
        
    except Exception as e:
        logger.error(f"خطا در تولید عکس: {e}")
        raise

# 👨‍💼 دستورات ادمین
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار ربات (فقط ادمین)"""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ فقط ادمین‌ها دسترسی دارند!")
        return
    
    try:
        total_users = len(user_messages)
        active_users = sum(1 for msgs in user_messages.values() if msgs)
        total_messages = sum(len(msgs) for msgs in user_messages.values())
        
        # آمار حالت‌ها
        mode_stats = {}
        for mode in user_mode.values():
            mode_stats[mode] = mode_stats.get(mode, 0) + 1
        
        mode_text = "\n".join([f"  {mode}: {count}" for mode, count in mode_stats.items()])
        
        stats_text = f"""
📊 آمار ربات:

👥 کل کاربران: {total_users}
🟢 کاربران فعال: {active_users}
💬 کل پیام‌ها: {total_messages}
⚡ ادمین‌ها: {len(ADMIN_IDS)}
🔗 چنل‌ها: {len(CHANNEL_IDS)}

📱 حالت‌های کاربران:
{mode_text}

🤖 وضعیت AI: {'✅ فعال' if AI_AVAILABLE else '❌ غیرفعال'}

@AnishtaYiN 
🧠 هوش مصنوعی ساخته شده توسط پارسا انیشتن
"""
        
        await update.message.reply_text(stats_text)
        
    except Exception as e:
        logger.error(f"خطا در آمار ربات: {e}")
        await update.message.reply_text("❌ خطا در نمایش آمار!")

async def reset_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ریست کردن محدودیت کاربر (فقط ادمین)"""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ فقط ادمین‌ها دسترسی دارند!")
        return
    
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("❌ استفاده: /reset [user_id]")
        return
    
    try:
        target_user_id = int(context.args[0])
        if target_user_id in user_messages:
            user_messages[target_user_id] = []
            # پاک کردن کش عضویت چنل
            if target_user_id in user_channel_status:
                del user_channel_status[target_user_id]
            # پاک کردن تاریخچه مکالمه
            if target_user_id in user_chat_history:
                user_chat_history[target_user_id] = []
            # ریست حالت کاربر
            user_mode[target_user_id] = "home"
            await async_save_data()
            await update.message.reply_text(f"✅ محدودیت و داده‌های کاربر {target_user_id} ریست شد!")
        else:
            await update.message.reply_text("❌ کاربر یافت نشد!")
    except ValueError:
        await update.message.reply_text("❌ آیدی کاربر باید عددی باشد!")
    except Exception as e:
        logger.error(f"خطا در ریست کاربر: {e}")
        await update.message.reply_text("❌ خطا در ریست کاربر!")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام همگانی (فقط ادمین)"""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ فقط ادمین‌ها دسترسی دارند!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ استفاده: /broadcast [پیام]")
        return
    
    try:
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
            except Exception as e:
                failed_count += 1
                logger.warning(f"خطا در ارسال پیام همگانی به {target_user_id}: {e}")
        
        await update.message.reply_text(
            f"✅ ارسال پیام همگانی تمام شد!\n\n"
            f"📤 ارسال شده: {sent_count}\n"
            f"❌ ناموفق: {failed_count}"
        )
        
    except Exception as e:
        logger.error(f"خطا در broadcast: {e}")
        await update.message.reply_text("❌ خطا در ارسال پیام همگانی!")

# 🔧 مدیریت خطاها
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازش خطاها"""
    logger.error(f"خطا در بروزرسانی {update}: {context.error}")
    
    # اگر خطا مربوط به یک پیام خاص است، سعی کن پاسخ دهی
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ خطای سیستمی رخ داد. لطفاً دوباره تلاش کنید."
            )
        except Exception as e:
            logger.error(f"خطا در ارسال پیام خطا: {e}")

# 🚀 راه‌اندازی ربات
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
        application.add_handler(CommandHandler("resetchat", resetchat_command))
        application.add_handler(CommandHandler("stats", admin_stats))
        application.add_handler(CommandHandler("reset", reset_user_command))
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        application.add_handler(CallbackQueryHandler(callback_query_handler))
        application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_message))
        
        # اضافه کردن error handler
        application.add_error_handler(error_handler)
        
        # راه‌اندازی ربات
        print("🤖 ربات شروع شد...")
        logger.info("ربات شروع شد")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print(f"❌ خطا در راه‌اندازی ربات: {e}")
        logger.error(f"خطا در راه‌اندازی ربات: {e}")
    finally:
        # ذخیره داده‌ها در پایان
        save_user_data()

if __name__ == "__main__":
    main()
