import asyncio
import logging
import re
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from supabase import create_client, Client
import google.generativeai as genai

# --- البيانات الخاصة بك ---
SUPABASE_URL = "https://ztcubxsgkspmjnuvamve.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_G-F2ZIST3iOCXYIi77N5Og_TBFdWWeu"
TELEGRAM_BOT_TOKEN = "8773479891:AAGvzLbWfGm4NCRWqhFxUJ6AsAsRxnQOqEY"
GEMINI_API_KEY = "AQ.Ab8RN6JBUgcI9EuBvFzqeGfJGzas9zxnWXT_nZ75HVVJmwaSpQ"

# رابط موقعك لزر Open المباشر بجانب خانة الكتابة
WEB_APP_URL = "https://google.com"

TOTAL_MAX_DEGREE = 320  # المجموع الكلي

# قائمة بحفظ الجروبات الموقوفة مؤقتاً
DISABLED_GROUPS = set()

# إعداد Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# إعداد Gemini AI
try:
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel("gemini-1.5-flash")
except Exception as e:
    logging.error(f"Gemini Init Error: {e}")
    ai_model = None

# إعداد التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# الكيبورد الرئيسي الثابت
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🌟 الأوائل"), KeyboardButton("📜 سجل البحث")],
        [KeyboardButton("🤖 الذكاء الاصطناعي"), KeyboardButton("🛑 تعطيل البوت في الجروب")],
    ],
    resize_keyboard=True,
    is_persistent=True
)

def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ؤ", "ء", text)
    text = re.sub(r"ئ", "ء", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"[\u064B-\u0652]", "", text)  # إزالة التشكيل
    return text.strip().lower()

def get_student_rank(total_degree: float) -> int:
    try:
        res = supabase.table("students").select("seating_no", count="exact").gt("total_degree", total_degree).execute()
        higher_students_count = res.count if res.count is not None else 0
        return higher_students_count + 1
    except Exception as e:
        logging.error(f"Error calculating rank: {e}")
        return 0

def build_student_card(student: dict, index: int, total_count: int) -> tuple[str, str, InlineKeyboardMarkup]:
    name = student.get("arabic_name", "غير محدد")
    seating_no = student.get("seating_no", "غير محدد")
    total_degree = student.get("total_degree", 0)
    case_desc = student.get("student_case_desc", "غير محدد")

    percentage = (total_degree / TOTAL_MAX_DEGREE) * 100 if TOTAL_MAX_DEGREE else 0
    rank = get_student_rank(total_degree)
    rank_str = f"#{rank}" if rank > 0 else "غير متاح"

    text = (
        f"🔍 **عدد النتائج المطابقة:** `{total_count}`\n"
        f"📄 **نتيجة ({index + 1} من {total_count})**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 **الاسم:** {name}\n"
        f"🔢 **رقم الجلوس:** `{seating_no}`\n"
        f"📊 **المجموع:** {total_degree} من {TOTAL_MAX_DEGREE}\n"
        f"📈 **النسبة المئوية:** {percentage:.2f}%\n"
        f"🏆 **الترتيب:** {rank_str}\n"
        f"📌 **الحالة:** {case_desc}\n"
        f"━━━━━━━━━━━━━━━"
    )

    copy_text = (
        f"الاسم: {name}\n"
        f"رقم الجلوس: {seating_no}\n"
        f"المجموع: {total_degree} من {TOTAL_MAX_DEGREE}\n"
        f"النسبة المئوية: {percentage:.2f}%\n"
        f"الترتيب: {rank_str}\n"
        f"الحالة: {case_desc}"
    )

    keyboard = []
    nav_buttons = []

    if index > 0:
        nav_buttons.append(InlineKeyboardButton("➡️ السابق", callback_data=f"nav_{index - 1}"))
    if index < total_count - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ⬅️", callback_data=f"nav_{index + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # زر نسخ النتيجة فقط
    keyboard.append([InlineKeyboardButton("📋 نسخ النتيجة", callback_data=f"copy_{index}")])

    return text, copy_text, InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "أهلاً بك 👋\n\n"
        "🔍 **يمكنك البحث فوراً بـ:**\n"
        "1️⃣ **رقم الجلوس** (مثل: `2001970`)\n"
        "2️⃣ **الاسم** أو جزء منه (مثل: `احمد محمود`)\n\n"
        "أو استخدم الأزرار بالأسفل للتصفح والخدمات الأخرى!"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def resume_bot_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type in ["group", "supergroup"]:
        DISABLED_GROUPS.discard(chat_id)
        await update.message.reply_text("✅ تم إعادة تفعيل عمل البوت في الجروب بنجاح!", reply_markup=MAIN_KEYBOARD)

async def handle_top_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري جلب قائمة الأوائل...", reply_markup=MAIN_KEYBOARD)
    try:
        res = supabase.table("students").select("*").order("total_degree", desc=True).limit(10).execute()
        top_list = res.data or []

        if not top_list:
            await update.message.reply_text("لا توجد بيانات متاحة حالياً.", reply_markup=MAIN_KEYBOARD)
            return

        msg = "🏆 **قائمة أوائل الطلاب:**\n━━━━━━━━━━━━━━━\n"
        for idx, student in enumerate(top_list, 1):
            name = student.get("arabic_name", "غير محدد")
            degree = student.get("total_degree", 0)
            seating = student.get("seating_no", "")
            perc = (degree / TOTAL_MAX_DEGREE) * 100
            msg += f"{idx}. **{name}**\n   🔢 جلوس: `{seating}` | 📊 المجموع: {degree} ({perc:.2f}%)\n\n"

        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        logging.error(f"Top students error: {e}")
        await update.message.reply_text("حدث خطأ أثناء جلب قائمة الأوائل.", reply_markup=MAIN_KEYBOARD)

async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = context.user_data.get("search_history", [])
    if not history:
        await update.message.reply_text("📜 لا يوجد لديك سجل بحث سابق حتى الآن.", reply_markup=MAIN_KEYBOARD)
        return

    msg = "📜 **سجل عمليات البحث الأخيرة:**\n━━━━━━━━━━━━━━━\n"
    for idx, q in enumerate(reversed(history[-10:]), 1):
        msg += f"{idx}. `{q}`\n"

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def handle_ai_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai_active = context.user_data.get("ai_mode", False)
    if not ai_active:
        context.user_data["ai_mode"] = True
        await update.message.reply_text(
            "🤖 **تم تفعيل وضع الذكاء الاصطناعي!**\n"
            "يمكنك الآن التحدث معي وسؤال أي شيء.\n"
            "(للخروج والعودة للبحث، أرسل كلمة **خروج**).",
            reply_markup=MAIN_KEYBOARD
        )
    else:
        context.user_data["ai_mode"] = False
        await update.message.reply_text("✅ تم إيقاف وضع الذكاء الاصطناعي. يمكنك البحث عن النتائج مجدداً.", reply_markup=MAIN_KEYBOARD)

async def save_history(context: ContextTypes.DEFAULT_TYPE, query_str: str):
    if "search_history" not in context.user_data:
        context.user_data["search_history"] = []
    if query_str not in context.user_data["search_history"]:
        context.user_data["search_history"].append(query_str)

def fetch_gemini_response(prompt_text: str) -> str:
    try:
        if not ai_model:
            return "نموذج الذكاء الاصطناعي غير متوفر حالياً."
        response = ai_model.generate_content(
            f"أنت مساعد ذكاء اصطناعي لبوت نتائج امتحانات. أجب على رسالة المستخدم التالية باللغة العربية بشكل ودي ومختصر: {prompt_text}"
        )
        if response and hasattr(response, 'text') and response.text:
            return response.text
        return "لم أستطع الحصول على إجابة."
    except Exception as e:
        return f"خطأ من جوجل: {e}"

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type in ["group", "supergroup"] and chat_id in DISABLED_GROUPS:
        return

    text_input = update.message.text.strip() if update.message.text else ""

    if not text_input:
        return

    if text_input == "🛑 تعطيل البوت في الجروب":
        if update.effective_chat.type in ["group", "supergroup"]:
            DISABLED_GROUPS.add(chat_id)
            await update.message.reply_text(
                "🛑 **تم تعطيل البوت في هذا الجروب.**\n"
                "إلإعادة تفعيله مجدداً أرسل: /resume"
            )
        else:
            await update.message.reply_text("ℹ️ هذا الخيار مخصص لإيقاف البوت داخل المجموعات (الجروبات) فقط.")
        return

    if text_input == "🌟 الأوائل":
        await handle_top_students(update, context)
        return
    elif text_input == "📜 سجل البحث":
        await handle_history(update, context)
        return
    elif text_input == "🤖 الذكاء الاصطناعي":
        await handle_ai_mode(update, context)
        return

    # --- معالجة الذكاء الاصطناعي ---
    if context.user_data.get("ai_mode", False):
        if text_input.lower() in ["خروج", "exit"]:
            context.user_data["ai_mode"] = False
            await update.message.reply_text("✅ خرجت من وضع الذكاء الاصطناعي.", reply_markup=MAIN_KEYBOARD)
            return

        wait_msg = await update.message.reply_text("🤖 جاري التفكير والرد...", reply_markup=MAIN_KEYBOARD)
        reply_text = await asyncio.to_thread(fetch_gemini_response, text_input)
        await wait_msg.edit_text(f"🤖 **الذكاء الاصطناعي:**\n\n{reply_text}")
        return

    # --- وضع البحث عن النتائج ---
    await save_history(context, text_input)

    if text_input.isdigit():
        seating_no = int(text_input)
        res = supabase.table("students").select("*").eq("seating_no", seating_no).execute()
        results = res.data or []
    else:
        raw_query = text_input.strip()
        
        # 1. بحث مباشر عبر Supabase
        res = supabase.table("students").select("*").ilike("arabic_name", f"%{raw_query}%").execute()
        results = res.data or []

        # 2. بحث مرن وشامل (عند كتابة الاسم مركب أو بدون تشكيل)
        if not results:
            words = raw_query.split()
            first_word_raw = words[0] if words else raw_query
            
            # البحث بالكلمة الأولى لجلب قاعدة البيانات المحتملة
            res = supabase.table("students").select("*").ilike("arabic_name", f"%{first_word_raw}%").execute()
            raw_results = res.data or []

            # تقييس كافة كلمات المدخل
            normalized_search_words = [normalize_arabic(w) for w in words if normalize_arabic(w)]
            
            seen_ids = set()
            for student in raw_results:
                st_name = student.get("arabic_name", "")
                st_name_normalized = normalize_arabic(st_name)
                
                # التحقق من أن جميع الكلمات المكتوبة موجودة بداخل الاسم الموحد
                if all(nw in st_name_normalized for nw in normalized_search_words):
                    st_id = student.get("seating_no")
                    if st_id not in seen_ids:
                        results.append(student)
                        seen_ids.add(st_id)

    if not results:
        await update.message.reply_text(
            "❌ لم يتم العثور على نتائج مطابقة. تأكد من إدخال الاسم أو رقم الجلوس بشكل صحيح.",
            reply_markup=MAIN_KEYBOARD
        )
        return

    context.user_data["search_results"] = results

    card_text, _, markup = build_student_card(results[0], 0, len(results))
    await update.message.reply_text(card_text, parse_mode="Markdown", reply_markup=markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    results = context.user_data.get("search_results", [])
    if not results:
        await query.edit_message_text("⚠️ انتهت جلسة البحث. يرجى إجراء بحث جديد.")
        return

    data = query.data

    if data.startswith("nav_"):
        index = int(data.split("_")[1])
        if 0 <= index < len(results):
            text, _, markup = build_student_card(results[index], index, len(results))
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("copy_"):
        index = int(data.split("_")[1])
        if 0 <= index < len(results):
            _, copy_text, _ = build_student_card(results[index], index, len(results))
            formatted_copy = f"📋 **اضغط على النص أدناه لنسخه:**\n\n```\n{copy_text}\n```"
            await query.message.reply_text(formatted_copy, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def post_init(application):
    # إعداد زر الـ Open الأزرق الثابت بجانب خانة الرسائل
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Open",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["resume", "start_bot"], resume_bot_in_group))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("تم تشغيل البوت بنجاح...")
    app.run_polling()

if __name__ == "__main__":
    main()
