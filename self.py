import asyncio
import os
import re
import json
import inspect

from bale import BaleClient, auth, events

SESSION_FILE = "bale_session.json"
AUTO_TASKS = {}
AUTO_COUNTER = 0
ACTIVE_CLIENT = None


def normalize_phone(phone):
    phone = str(phone).strip()
    for ch in [" ", "-", "(", ")", "_"]:
        phone = phone.replace(ch, "")

    if phone.startswith("+"):
        phone = phone[1:]

    if phone.startswith("00"):
        phone = phone[2:]

    if phone.startswith("09"):
        phone = "98" + phone[1:]
    elif phone.startswith("9") and len(phone) == 10:
        phone = "98" + phone
    elif phone.startswith("98"):
        pass
    else:
        return None

    if not phone.isdigit():
        return None

    if len(phone) != 12 or not phone.startswith("98"):
        return None

    return int(phone)


def parse_duration(value):
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(s|m|h)", value)

    if not match:
        return None

    number = float(match.group(1))
    unit = match.group(2)

    if number <= 0:
        return None

    if unit == "s":
        return number
    if unit == "m":
        return number * 60
    if unit == "h":
        return number * 3600

    return None


def format_duration(seconds):
    seconds = float(seconds)

    if seconds < 60:
        if seconds.is_integer():
            return f"{int(seconds)} ثانیه"
        return f"{seconds:.1f} ثانیه"

    if seconds < 3600:
        minutes = seconds / 60
        if minutes.is_integer():
            return f"{int(minutes)} دقیقه"
        return f"{minutes:.1f} دقیقه"

    hours = seconds / 3600
    if hours.is_integer():
        return f"{int(hours)} ساعت"
    return f"{hours:.1f} ساعت"


def load_session():
    if not os.path.exists(SESSION_FILE):
        return None

    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ خطا در خواندن سشن: {e}")
        return None


def save_session(access_token):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"access_token": access_token},
                f,
                ensure_ascii=False,
                indent=2,
            )
        try:
            os.chmod(SESSION_FILE, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"❌ خطا در ذخیره سشن: {e}")
        return False


def delete_session():
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass


async def login_with_phone():
    print()
    print("=" * 60)
    print("📱 ورود به حساب بله")
    print("=" * 60)

    while True:
        raw_phone = input("📞 شماره تلفن را وارد کن: ").strip()
        phone = normalize_phone(raw_phone)

        if phone is None:
            print()
            print("❌ شماره نامعتبر است.")
            print("مثال صحیح:")
            print("09123456789")
            print("+989123456789")
            print("989123456789")
            print()
            continue

        print()
        print(f"📞 شماره بین‌المللی: {phone}")
        break

    try:
        print()
        print("📨 در حال ارسال کد تأیید...")

        session = auth.start_phone_auth(phone)

        print()
        print("✅ درخواست کد ارسال شد.")

        transaction_hash = getattr(session, "transaction_hash", None)

        if not transaction_hash:
            print("❌ transaction_hash دریافت نشد.")
            print("پاسخ:")
            print(session)
            return None

        print()
        print("🔐 کد ارسال‌شده را وارد کن.")

        code = input("کد تأیید: ").strip()

        if not code:
            print("❌ کد خالی است.")
            return None

        print()
        print("🔄 در حال بررسی کد...")

        result = auth.validate_code(transaction_hash, code)

        if inspect.isawaitable(result):
            result = await result

        access_token = getattr(result, "access_token", None)

        if not access_token:
            access_token = getattr(result, "jwt", None)

        if not access_token:
            jwt_obj = getattr(result, "jwt", None)
            if jwt_obj:
                access_token = getattr(jwt_obj, "value", None)

        if not access_token:
            print()
            print("❌ ورود تأیید شد اما access_token پیدا نشد.")
            print("LoginResult:")
            print(result)
            return None

        save_session(access_token)

        print()
        print("✅ ورود موفق بود.")
        print("💾 سشن ذخیره شد.")

        return access_token

    except Exception as e:
        print()
        print(f"❌ خطا در ورود: {e}")
        return None


async def create_client():
    saved = load_session()
    client = None

    if saved:
        token = saved.get("access_token")
        if token:
            print()
            print("🔐 سشن قبلی پیدا شد.")
            try:
                client = BaleClient(token)
                await client.connect()
                me = await client.get_me()

                print("✅ ورود خودکار موفق بود.")
                print(f"👤 حساب: {getattr(me, 'title', me)}")
                return client

            except Exception as e:
                print(f"⚠️ سشن قبلی معتبر نیست: {e}")
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                delete_session()
                print("🗑 سشن قبلی حذف شد.")

    while True:
        token = await login_with_phone()

        if not token:
            retry = input("\n🔁 دوباره تلاش کنم؟ (y/n): ").strip().lower()
            if retry != "y":
                return None
            continue

        try:
            client = BaleClient(token)
            await client.connect()
            me = await client.get_me()

            print()
            print("✅ ورود موفق بود.")
            print(f"👤 حساب: {getattr(me, 'title', me)}")
            return client

        except Exception as e:
            print(f"❌ اتصال ناموفق بود: {e}")
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            delete_session()


def next_auto_id():
    global AUTO_COUNTER
    AUTO_COUNTER += 1
    return AUTO_COUNTER


def get_autos(chat_id):
    return AUTO_TASKS.get(chat_id, [])


def find_auto(chat_id, auto_id):
    for auto in get_autos(chat_id):
        if auto["id"] == auto_id:
            return auto
    return None


def remove_auto(chat_id, auto_id):
    autos = get_autos(chat_id)
    remaining = [x for x in autos if x["id"] != auto_id]

    if remaining:
        AUTO_TASKS[chat_id] = remaining
    else:
        AUTO_TASKS.pop(chat_id, None)


async def normal_worker(client, chat_id, auto_id):
    try:
        while True:
            auto = find_auto(chat_id, auto_id)
            if not auto:
                break

            await asyncio.sleep(auto["intervals"][0])

            auto = find_auto(chat_id, auto_id)
            if not auto:
                break

            try:
                await client.send_message(chat_id, auto["text"])
                print(f"📨 اتو #{auto_id} ارسال شد.")
            except Exception as e:
                print(f"❌ خطای ارسال #{auto_id}: {e}")
                await asyncio.sleep(2)

    except asyncio.CancelledError:
        pass
    finally:
        remove_auto(chat_id, auto_id)


async def combined_worker(client, chat_id, auto_id):
    index = 0

    try:
        while True:
            auto = find_auto(chat_id, auto_id)
            if not auto:
                break

            intervals = auto["intervals"]
            if not intervals:
                break

            await asyncio.sleep(intervals[index])

            auto = find_auto(chat_id, auto_id)
            if not auto:
                break

            try:
                await client.send_message(chat_id, auto["text"])
                print(f"📨 اتوی ترکیبی #{auto_id} ارسال شد.")
            except Exception as e:
                print(f"❌ خطای ارسال #{auto_id}: {e}")
                await asyncio.sleep(2)

            index += 1
            if index >= len(intervals):
                index = 0

    except asyncio.CancelledError:
        pass
    finally:
        remove_auto(chat_id, auto_id)


def create_normal_auto(client, chat_id, text, interval):
    auto_id = next_auto_id()

    auto = {
        "id": auto_id,
        "text": text,
        "type": "normal",
        "intervals": [interval],
        "task": None,
    }

    AUTO_TASKS.setdefault(chat_id, []).append(auto)

    auto["task"] = asyncio.create_task(
        normal_worker(client, chat_id, auto_id)
    )

    return auto


def create_combined_auto(client, chat_id, text, intervals):
    auto_id = next_auto_id()

    auto = {
        "id": auto_id,
        "text": text,
        "type": "combined",
        "intervals": intervals,
        "task": None,
    }

    AUTO_TASKS.setdefault(chat_id, []).append(auto)

    auto["task"] = asyncio.create_task(
        combined_worker(client, chat_id, auto_id)
    )

    return auto


def event_text(event):
    value = getattr(event, "text", None)
    if value is None:
        return ""
    return str(value).strip()


def event_chat_id(event):
    value = getattr(event, "chat_id", None)
    if value is not None:
        return value

    chat = getattr(event, "chat", None)
    if chat:
        return getattr(chat, "id", None)

    return None


async def on_message(event):
    global ACTIVE_CLIENT

    client = ACTIVE_CLIENT
    if client is None:
        return

    try:
        text = event_text(event)
        if not text:
            return

        if not getattr(event, "is_group", False):
            return

        chat_id = event_chat_id(event)
        if chat_id is None:
            return

        if text == ".اتو":
            await event.reply(
                "❌ دستور درست:\n\n"
                ".اتو متن زمان\n\n"
                "مثال:\n"
                ".اتو سلام 1m\n\n"
                "s = ثانیه\n"
                "m = دقیقه\n"
                "h = ساعت"
            )
            return

        if text.startswith(".اتو "):
            parts = text.split()

            if len(parts) < 3:
                await event.reply(
                    "❌ دستور درست:\n"
                    ".اتو سلام 1m"
                )
                return

            interval = parse_duration(parts[-1])

            if interval is None:
                await event.reply("❌ زمان نامعتبر است.")
                return

            message_text = " ".join(parts[1:-1]).strip()

            auto = create_normal_auto(
                client, chat_id, message_text, interval
            )

            await event.reply(
                "✅ اتو اضافه شد.\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 #{auto['id']}\n"
                f"📝 {message_text}\n"
                f"⏱ {format_duration(interval)}\n"
                f"🔢 تعداد اتوها: {len(get_autos(chat_id))}\n"
                "🟢 فعال"
            )
            return

        if text == ".ترکیبی":
            await event.reply(
                "❌ دستور درست:\n\n"
                ".ترکیبی متن 1m 2m\n\n"
                "مثال:\n"
                ".ترکیبی تست 1m 2m\n\n"
                "🔄 1 دقیقه → ارسال\n"
                "🔄 2 دقیقه → ارسال\n"
                "🔄 دوباره 1 دقیقه → ارسال"
            )
            return

        if text.startswith(".ترکیبی "):
            parts = text.split()

            intervals = []
            text_parts = []

            for part in parts[1:]:
                value = parse_duration(part)
                if value is None:
                    text_parts.append(part)
                else:
                    intervals.append(value)

            if len(intervals) < 2:
                await event.reply(
                    "❌ حداقل دو زمان لازم است.\n\n"
                    ".ترکیبی تست 1m 2m"
                )
                return

            message_text = " ".join(text_parts).strip()

            if not message_text:
                await event.reply("❌ متن پیام مشخص نشده.")
                return

            auto = create_combined_auto(
                client, chat_id, message_text, intervals
            )

            times = " → ".join(
                format_duration(x) for x in intervals
            )

            await event.reply(
                "✅ اتوی ترکیبی اضافه شد.\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 #{auto['id']}\n"
                f"📝 {message_text}\n"
                f"⏱ {times}\n"
                f"🔢 تعداد اتوها: {len(get_autos(chat_id))}\n"
                "🔄 تکرار: فعال"
            )
            return

        if text == ".وضعیت اتو":
            autos = get_autos(chat_id)

            alive = []
            for auto in autos:
                task = auto.get("task")
                if task and not task.done():
                    alive.append(auto)

            if alive:
                AUTO_TASKS[chat_id] = alive
            else:
                AUTO_TASKS.pop(chat_id, None)

            autos = get_autos(chat_id)

            if not autos:
                await event.reply(
                    "🔴 هیچ اتویی در این گروه فعال نیست."
                )
                return

            lines = [
                "🟢 وضعیت اتوها",
                "━━━━━━━━━━━━━━━━━━━━",
                f"🔢 تعداد فعال: {len(autos)}",
                "",
            ]

            for auto in autos:
                lines.append(f"🆔 اتو #{auto['id']}")
                lines.append(f"📝 {auto['text']}")

                if auto["type"] == "combined":
                    times = " → ".join(
                        format_duration(x)
                        for x in auto["intervals"]
                    )
                    lines.append(f"🔀 ترکیبی: {times}")
                else:
                    lines.append(
                        f"⏱ هر {format_duration(auto['intervals'][0])}"
                    )

                lines.append("🟢 فعال")
                lines.append("────────────────────")

            await event.reply("\n".join(lines))
            return

        if text.startswith(".توقف ") and text not in (".توقف اتو",):
            value = text[6:].strip()

            try:
                auto_id = int(value.replace("#", ""))
            except ValueError:
                auto_id = None

            if auto_id is not None:
                auto = find_auto(chat_id, auto_id)

                if not auto:
                    await event.reply("❌ این اتو پیدا نشد.")
                    return

                remove_auto(chat_id, auto_id)

                task = auto.get("task")
                if task:
                    task.cancel()

                await event.reply(
                    f"🛑 اتو #{auto_id} متوقف شد."
                )
                return

        if text in (".توقف اتو", ".خاموش اتو"):
            autos = AUTO_TASKS.pop(chat_id, [])

            if not autos:
                await event.reply("ℹ️ هیچ اتویی فعال نیست.")
                return

            for auto in autos:
                task = auto.get("task")
                if task:
                    task.cancel()

            await event.reply(
                "🛑 همه اتوهای این گروه متوقف شدند.\n"
                f"🔢 تعداد متوقف‌شده: {len(autos)}"
            )
            return

    except Exception as e:
        print(f"❌ Message Handler Error: {e}")


async def main():
    global ACTIVE_CLIENT

    print("=" * 60)
    print("🤖 BALE SELF BOT")
    print("=" * 60)

    client = await create_client()

    if client is None:
        print("❌ ورود انجام نشد.")
        return

    ACTIVE_CLIENT = client

    try:
        client.on(events.NewMessage)(on_message)
        print("✅ سیستم دریافت پیام فعال شد.")
    except Exception as e:
        print(f"❌ خطا در ثبت Event: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        return

    print()
    print("=" * 60)
    print("📌 دستورات")
    print("=" * 60)
    print()
    print(".اتو سلام 1m")
    print(".اتو تست 2m")
    print()
    print(".ترکیبی تست 1m 2m")
    print()
    print(".وضعیت اتو")
    print(".توقف 1")
    print(".توقف اتو")
    print()
    print("➕ چند اتو همزمان در یک گروه")
    print("🔀 اتوی ترکیبی")
    print("💾 ذخیره سشن")
    print("🚀 فعال شد")
    print("=" * 60)

    try:
        await client.run_until_disconnected()
    except Exception as e:
        print()
        print(f"❌ اتصال قطع شد: {e}")
    finally:
        ACTIVE_CLIENT = None
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 برنامه متوقف شد.")