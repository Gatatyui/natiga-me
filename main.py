import os
import re
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
from thefuzz import process, fuzz

# البيانات الأساسية (تم وضع التوكين مباشرة)
TELEGRAM_TOKEN = "8773479891:AAEdB5WaInEhiRxeff4Lgwj3MzEWIkPifKY"
SUPABASE_URL = "https://ztcubxsgkspmjnuvamve.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_G-F2ZIST3iOCXYIi77N5Og_TBFdWWeu"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
TOTAL_MARKS = 320

user_sessions = {}

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[أإآءئؤ]', 'ا', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'[\u064B-\u0652]', '', text)
    return text.strip().lower()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [["🔍 بحث جديد", "❓ مساعدة"]],
        resize_keyboard=True
    )

def get_matches_keyboard(matches):
    buttons = [[f"👤 {item['name']}"] for item in matches]
    buttons.append(["❌ إلغاء البحث"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_sessions.pop(chat_id, None)
    await update.message.reply_text(
        "أهلاً بك! اكتب **رقم الجلوس** أو **اسم الطالب** لبدء البحث:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "يمكنك إرسال رقم الجلوس مباشرة، أو كتابة اسم الطالب (مع التسامح مع الأخطاء الإملائية).",
        reply_markup=get_main_keyboard()
    )

async def send_student_result(update: Update, student: dict):
    total_score = student.get('total_score', 0) or 0
    percentage = student.get('percentage')
    
    if not percentage:
        percentage = round((total_score / TOTAL_MARKS) * 100, 2)

    response_text = (
        f"🎓 **نتيجة الطالب**\n\n"
        f"👤 **الاسم:** {student.get('name')}\n"
        f"🔢 **رقم الجلوس:** {student.get('seat_no')}\n"
        f"📊 **المجموع الكلي:** {total_score} من {TOTAL_MARKS}\n"
        f"📈 **النسبة المئوية:** {percentage}%\n"
        f"📌 **الحالة:** {student.get('status', 'ناجح')}"
    )

    await update.message.reply_text(
        response_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip() if update.message.text else ""

    if not text:
        return

    if text in ["/start", "🔍 بحث جديد", "❌ إلغاء البحث"]:
        await start(update, context)
        return

    if text == "❓ مساعدة":
        await help_command(update, context)
        return

    if chat_id in user_sessions:
        selected_name = text.replace("👤 ", "")
        session_matches = user_sessions.get(chat_id, [])
        matched_student = next((s for s in session_matches if s['name'] == selected_name), None)

        if matched_student:
            user_sessions.pop(chat_id, None)
            await send_student_result(update, matched_student)
            return

    loading_msg = await update.message.reply_text("جاري البحث عن النتيجة...")

    try:
        if text.isdigit():
            response = supabase.table('students').select('*').eq('seat_no', text).execute()
            data = response.data

            await loading_msg.delete()

            if not data:
                await update.message.reply_text("لم يتم العثور على نتيجة برقم الجلوس هذا.", reply_markup=get_main_keyboard())
                return

            await send_student_result(update, data[0])

        else:
            clean_input = normalize_text(text)
            first_word = clean_input.split()[0] if clean_input else ""

            response = supabase.table('students').select('*').or_(f"name.ilike.%{first_word}%,name.ilike.%{text}%").limit(300).execute()
            students = response.data

            await loading_msg.delete()

            if not students:
                await update.message.reply_text("لم يتم العثور على اسم مطابق في قاعدة البيانات.", reply_markup=get_main_keyboard())
                return

            names_map = {s['name']: normalize_text(s['name']) for s in students}
            normalized_names = list(names_map.values())

            best_matches = process.extract(clean_input, normalized_names, scorer=fuzz.WRatio, limit=5)
            filtered_matches = [m for m in best_matches if m[1] >= 50]

            if not filtered_matches:
                await update.message.reply_text("لم يتم العثور على اسم قريب من المدخلات.", reply_markup=get_main_keyboard())
                return

            matched_students = []
            for norm_name, score in filtered_matches:
                for student in students:
                    if normalize_text(student['name']) == norm_name and student not in matched_students:
                        matched_students.append(student)

            if len(matched_students) > 1:
                user_sessions[chat_id] = matched_students
                await update.message.reply_text(
                    f"وجدت أكثر من اسم قريب من \"{text}\". اختر الاسم الصحيح:",
                    reply_markup=get_matches_keyboard(matched_students)
                )
            else:
                user_sessions.pop(chat_id, None)
                await send_student_result(update, matched_students[0])

    except Exception as e:
        print(f"Error: {e}")
        try:
            await loading_msg.delete()
        except:
            pass
        await update.message.reply_text("حدث خطأ غير متوقع، حاول لاحقاً.", reply_markup=get_main_keyboard())

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("البوت يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()
