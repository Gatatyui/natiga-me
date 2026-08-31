import re
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from supabase import create_client, Client

# 1. إعدادات الاتصال (Supabase) المأخوذة من الموقع المرفق
SUPABASE_URL = "https://ztcubxsgkspmjnuvamve.supabase.co"
SUPABASE_KEY = "sb_publishable_G-F2ZIST3iOCXYIi77N5Og_TBFdWWeu"
TELEGRAM_BOT_TOKEN = "8773479891:AAEdB5WaInEhiRxeff4Lgwj3MzEWIkPifKY"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------------------------------------------
# دالّات المساعدة وتوحيد النصوص العربية
# ----------------------------------------------------


def normalize_arabic(text: str) -> str:
    """تطهير وتوحيد الحروف العربية لمطابقة آلية الموقع"""
    if not text:
        return ""
    text = str(text).strip()
    text = re.sub(r"[أإآ]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"[\u064B-\u0652]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def build_sql_like_pattern(token: str) -> str:
    """بناء نمط البحث المخصص المطابق للواجهة"""
    if not token:
        return ""
    t = token.strip()
    if t.startswith("ال") and len(t) > 3:
        t = t[2:]
    t = re.sub(r"[أإآا]", "_", t)
    t = re.sub(r"[ىي]$", "_", t)
    t = re.sub(r"[ةه]$", "_", t)
    return f"%{t}%"


def calculate_percentage(total_degree) -> str:
    """حساب النسبة المئوية بناءً على مجموع 320"""
    try:
        total = float(total_degree)
        pct = (total / 320) * 100
        return f"{pct:.1f}%"
    except (ValueError, TypeError):
        return "0.0%"


def format_student_card(student: dict) -> str:
    """تنسيق نتيجة الطالب لرسائل التليجرام"""
    name = student.get("arabic_name", "غير محدد")
    seat = student.get("seating_no", "---")
    total = student.get("total_degree", 0)
    status = student.get("student_case_desc", "ناجح")
    pct = calculate_percentage(total)

    return (
        f"🎓 *نتيجة الثانوية العامة 2026*\n\n"
        f"👤 *اسم الطالب:* {name}\n"
        f"🔢 *رقم الجلوس:* `{seat}`\n"
        f"📊 *المجموع الكلي:* {total} / 320\n"
        f"📈 *النسبة المئوية:* {pct}\n"
        f"📌 *الحالة:* {status}\n"
    )


# ----------------------------------------------------
# الاستعلام من قاعدة البيانات Supabase
# ----------------------------------------------------


def search_student_data(query_str: str):
    """البحث سواء برقم الجلوس أو بالاسم"""
    clean_query = query_str.strip()

    # 1. إذا كان المدخل رقم جلوس (أرقام فقط)
    if clean_query.isdigit():
        try:
            res = (
                supabase.table("students")
                .select("*")
                .or_(f"seating_no.eq.{int(clean_query)},seating_no.eq.{clean_query}")
                .execute()
            )
            return res.data if res.data else []
        except Exception as e:
            print(f"Error seating query: {e}")
            return []

    # 2. إذا كان المدخل اسماً
    norm_query = normalize_arabic(clean_query)
    tokens = [t for t in norm_query.split(" ") if t]
    if not tokens:
        return []

    try:
        db_query = supabase.table("students").select("*")
        for token in tokens:
            pattern = build_sql_like_pattern(token)
            if pattern:
                db_query = db_query.ilike("arabic_name", pattern)

        res = db_query.limit(10).execute()
        matches = res.data if res.data else []

        # محاولة بحث مرنة في حال عدم وجود نتائج مطابقة تماماً
        if not matches:
            or_conditions = [
                f"arabic_name.ilike.{build_sql_like_pattern(t)}"
                for t in tokens
                if build_sql_like_pattern(t)
            ]
            if or_conditions:
                res_or = (
                    supabase.table("students")
                    .select("*")
                    .or_(",".join(or_conditions))
                    .limit(10)
                    .execute()
                )
                matches = res_or.data if res_or.data else []

        return matches
    except Exception as e:
        print(f"Error name query: {e}")
        return []


# ----------------------------------------------------
# معالجات أوامر ورسائل البوت
# ----------------------------------------------------


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "مرحباً بك في *بوابة النتائج الرسمية للثانوية العامة 2026* 🎓\n\n"
        "يمكنك البحث بالأساليب التالية:\n"
        "1️⃣ أرسل *رقم الجلوس* مباشرة.\n"
        "2️⃣ أرسل *اسم الطالب* (سواء ثنائي، ثلاثي، أو رباعي).\n\n"
        "أو استخدم الأمر /top لعرض قائمة الأوائل."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جلب قائمة الأوائل (أعلى 10 درجات)"""
    try:
        res = (
            supabase.table("students")
            .select("*")
            .order("total_degree", desc=True)
            .limit(10)
            .execute()
        )
        top_list = res.data if res.data else []

        if not top_list:
            await update.message.reply_text("لا توجد بيانات متاحة حالياً.")
            return

        msg = "🏆 *أوائل الثانوية العامة 2026*\n\n"
        for idx, student in enumerate(top_list, 1):
            name = student.get("arabic_name", "")
            total = student.get("total_degree", 0)
            pct = calculate_percentage(total)
            msg += f"{idx}. *{name}* — {total}/320 ({pct})\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء جلب قائمة الأوائل.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    await update.message.reply_text("🔎 جاري البحث في قاعدة البيانات...")

    results = search_student_data(text)

    if not results:
        await update.message.reply_text(
            "❌ لم نتمكن من العثور على أي نتائج مطابقة.\nتأكد من كتابة الاسم أو رقم الجلوس بشكل صحيح."
        )
        return

    # إذا كانت النتيجة طالب واحد فقط
    if len(results) == 1:
        card = format_student_card(results[0])
        await update.message.reply_text(card, parse_mode="Markdown")
    else:
        # إذا وجدت عدة نتائج بالاسم (أكثر من طالب)
        response_text = (
            f"🔍 تم العثور على *{len(results)}* نتائج مطابقة:\n\n"
        )
        for idx, student in enumerate(results[:10], 1):
            name = student.get("arabic_name")
            seat = student.get("seating_no")
            total = student.get("total_degree")
            pct = calculate_percentage(total)
            response_text += (
                f"{idx}. *{name}*\n   رقم الجلوس: `{seat}` | المجموع: {pct}\n\n"
            )

        response_text += "💡 *ملاحظة:* للحصول على تفاصيل أعمق، ابحث برقم الجلوس المباشر للطالب."
        await update.message.reply_text(response_text, parse_mode="Markdown")


# ----------------------------------------------------
# التشغيل الرئيسي
# ----------------------------------------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    print("🤖 البوت يعمل الآن ويستقبل الرسائل...")
    app.run_polling()
