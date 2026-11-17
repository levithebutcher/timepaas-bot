import re
import logging
from pathlib import Path
try:
    from pyrogram import Client, filters
    from pyrogram.types import Message
except ImportError:
    class _MockFilter:
        def __and__(self, other): return self
        def __invert__(self): return self
    class _MockClient:
        @staticmethod
        def on_message(*args, **kwargs):
            return lambda f: f
    Client = _MockClient
    filters = type("filters", (), {
        "text": _MockFilter(),
        "private": _MockFilter(),
        "command": lambda *args: _MockFilter()
    })
    Message = object
from bot.config import ADMIN_IDS, DOWNLOAD_DIR
from bot.database import (
    set_user_thumb,
    clear_user_thumb,
    set_user_caption,
    get_user_settings,
    get_dump_channel,
    set_dump_channel
)
from bot.core.queue_manager import queue_manager

logger = logging.getLogger(__name__)


def is_authorized(user_id: int) -> bool:
    """Checks if user is in ADMIN_IDS. If ADMIN_IDS is empty, grants access."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        await message.reply_text("⛔ <b>Access Denied.</b> You are not authorized to use this bot.")
        return

    text = (
        "<blockquote>"
        "⚡ <b>TIMEPASS LEECH & DOWNLOADER</b>\n\n"
        "Send any video link to download and upload directly to Telegram!\n\n"
        "• <b>Single link:</b> Direct video player upload\n"
        "• <b>Multiple links:</b> Auto-grouped into video albums (up to 10 per album)\n"
        "• <b>Fast Multi-Stream:</b> 32-split Aria2 turbo engine\n"
        "• <b>Auto-Split:</b> Automatically splits videos &gt; 1.95 GB\n\n"
        "📖 <i>Send /help for full command guide</i>"
        "</blockquote>"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    text = (
        "<blockquote>"
        "📖 <b>COMMAND GUIDE</b>\n\n"
        "• <code>&lt;link&gt;</code> — Download & upload single video\n"
        "• <code>&lt;link1&gt; &lt;link2&gt;...</code> — Auto-grouped video album\n"
        "• <code>/album &lt;links&gt;</code> — Force album mode\n"
        "• <code>/status</code> — View active tasks\n"
        "• <code>/cancelall</code> — Cancel all active tasks\n"
        "• <code>/setthumb</code> — Reply to image to set thumbnail\n"
        "• <code>/clearthumb</code> — Reset thumbnail\n"
        "• <code>/setcaption &lt;text&gt;</code> — Set custom caption\n"
        "• <code>/setdump &lt;id&gt;</code> — Configure Dump Channel (Option B Relay)\n"
        "• <code>/cleardump</code> — Clear Dump Channel\n"
        "• <code>/dump</code> — View Dump Channel status"
        "</blockquote>"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    active_tasks = [t for t in queue_manager.tasks.values() if t.status not in ("Done", "Failed", "Cancelled")]

    sys_info = ""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage(".").percent
        sys_info = f"\n\n⚙️ <b>Server:</b> CPU <code>{cpu}%</code> | RAM <code>{mem}%</code> | Disk <code>{disk}%</code>"
    except Exception:
        pass

    if not active_tasks:
        await message.reply_text(
            "<blockquote>"
            "📭 <b>NO ACTIVE TASKS</b>\n"
            "All queues are clear. Send links to start downloading!"
            f"{sys_info}"
            "</blockquote>"
        )
        return

    items = []
    for idx, t in enumerate(active_tasks[:10], 1):
        items.append(f"• <b>[{idx:02d}]</b> <code>{t.id[:8]}</code> — <i>{t.status}</i>\n  <code>{t.url[:40]}...</code>")

    text = (
        f"<blockquote>"
        f"📊 <b>ACTIVE QUEUE ({len(active_tasks)} Tasks)</b>\n\n"
        + "\n\n".join(items)
        + f"{sys_info}"
        f"</blockquote>"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("cancelall") & filters.private)
async def cancelall_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    cancelled = queue_manager.cancel_all_for_user(message.from_user.id)
    if cancelled > 0:
        await message.reply_text(f"🛑 Cancelled {cancelled} task(s).")
    else:
        await message.reply_text("ℹ️ You have no active or pending tasks to cancel.")


@Client.on_message(filters.command("setthumb") & filters.private)
async def setthumb_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    replied = message.reply_to_message
    if not replied or not (replied.photo or (replied.document and replied.document.mime_type.startswith("image/"))):
        await message.reply_text("⚠️ Please **reply to an image** with `/setthumb`.")
        return

    thumb_dir = DOWNLOAD_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"thumb_{message.from_user.id}.jpg"

    msg = await message.reply_text("⏳ Saving custom thumbnail...")
    try:
        await client.download_media(replied, file_name=str(thumb_path))
        await set_user_thumb(message.from_user.id, str(thumb_path))
        await msg.edit_text("✅ **Custom thumbnail saved successfully!**")
    except Exception as e:
        logger.error(f"Failed to save thumbnail: {e}")
        await msg.edit_text(f"❌ Failed to save thumbnail: `{e}`")


@Client.on_message(filters.command("clearthumb") & filters.private)
async def clearthumb_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    await clear_user_thumb(message.from_user.id)
    await message.reply_text("🗑️ Custom thumbnail cleared. Default video thumbnails will be used.")


@Client.on_message(filters.command("setcaption") & filters.private)
async def setcaption_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("⚠️ Usage: `/setcaption Your Custom Caption Here`")
        return

    caption = parts[1].strip()
    await set_user_caption(message.from_user.id, caption)
    await message.reply_text(f"✅ **Custom caption template saved:**\n`{caption}`")


async def resolve_dump_chat(client: Client, raw_input: str = "", reply_to: Message = None):
    """
    Automatically resolves and fetches any channel target:
    - Forwarded message from the channel (reply_to.forward_from_chat)
    - Private channel message link (https://t.me/c/1234567890/45 -> -1001234567890)
    - Private invite link (https://t.me/+AbcDef or https://t.me/joinchat/AbcDef)
    - Public channel username or link (https://t.me/mychannel/45 or @mychannel)
    - Numeric channel ID (-1001234567890 or 1234567890)
    """
    # 1. Forwarded message check
    if reply_to:
        if getattr(reply_to, "forward_from_chat", None):
            f_chat = reply_to.forward_from_chat
            try:
                return await client.get_chat(f_chat.id)
            except Exception:
                return f_chat
        if not raw_input:
            if getattr(reply_to, "text", None):
                raw_input = reply_to.text.strip()
            elif getattr(reply_to, "caption", None):
                raw_input = reply_to.caption.strip()

    if not raw_input:
        return None

    target = raw_input.strip().strip("'\"")

    # 2. Private channel message link: https://t.me/c/1234567890/123 or t.me/c/1234567890
    c_match = re.search(r"(?:https?://)?(?:www\.)?t(?:elegram)?\.me/c/(\d+)(?:/\d+)?", target)
    if c_match:
        raw_num = c_match.group(1)
        full_id = int(f"-100{raw_num}")
        logger.info(f"Resolved private channel message link to ID: {full_id}")
        return await client.get_chat(full_id)

    # 3. Private invite link: https://t.me/+AbcDef or https://t.me/joinchat/AbcDef or +AbcDef
    invite_match = re.search(r"(?:https?://)?(?:www\.)?t(?:elegram)?\.me/(?:\+|joinchat/)([a-zA-Z0-9_\-]+)", target)
    if not invite_match and target.startswith("+") and len(target) > 5:
        invite_match = re.search(r"\+([a-zA-Z0-9_\-]+)", target)

    if invite_match:
        invite_hash = invite_match.group(1)
        full_invite = f"https://t.me/+{invite_hash}"
        logger.info(f"Attempting to resolve private invite link: {full_invite}")

        # Check if client is a bot or user account
        is_bot = True
        try:
            me = await client.get_me()
            is_bot = getattr(me, "is_bot", True)
        except Exception:
            pass

        if not is_bot:
            # Userbot / user account can join directly via invite link
            try:
                chat = await client.join_chat(full_invite)
                if chat:
                    return chat
            except Exception as join_err:
                logger.debug(f"User join_chat failed on invite {full_invite}: {join_err}")

        # For Telegram Bots: Bots cannot use join_chat (ImportChatInvite).
        # We query CheckChatInvite to resolve peer or identify membership.
        try:
            from pyrogram.raw.functions.messages import CheckChatInvite
            from pyrogram.raw.types import ChatInvite, ChatInviteAlready
            from pyrogram.utils import get_channel_id

            res = await client.invoke(CheckChatInvite(hash=invite_hash))
            if isinstance(res, ChatInviteAlready):
                # Bot is already added to this channel!
                target_id = get_channel_id(res.chat.id)
                logger.info(f"Resolved invite link to already joined channel ID: {target_id}")
                return await client.get_chat(target_id)
            elif isinstance(res, ChatInvite):
                # Bot is not added to the channel yet
                ch_title = getattr(res, "title", None) or "Private Channel"
                raise RuntimeError(
                    f"Bot channel '<b>{ch_title}</b>' me added nahi hai!\n\n"
                    f"⚠️ Telegram security policy ke mutabiq Bot private invite link se khud join nahi ho sakta.\n\n"
                    f"<b>Bas ye 1 step karein:</b>\n"
                    f"1. Apne channel me jayein ➔ <b>Channel Settings</b> ➔ <b>Administrators</b> ➔ <b>Add Admin</b>.\n"
                    f"2. Is Bot ko search karke Administrator banayein (with <i>'Post Messages'</i> permission).\n"
                    f"3. Bot add hote hi ya to link dobara bhej dein, ya channel me direct <code>/setdump</code> likh dein!"
                )
        except Exception as check_err:
            if "Bot channel" in str(check_err):
                raise
            logger.debug(f"CheckChatInvite failed for {invite_hash}: {check_err}")
            raise RuntimeError(
                f"Invite link resolve nahi ho paya ({check_err}).\n\n"
                f"💡 <b>Sabse asaan tareeqa:</b>\n"
                f"1. Bot ko apne channel me <b>Admin</b> banayein.\n"
                f"2. Channel me jakar seedha <code>/setdump</code> likhein (bot khud connect ho jayega)!\n"
                f"<b>YA</b> channel ka koi post yahan forward karke <code>/setdump</code> reply karein."
            )

    # 4. Public channel link or message link: https://t.me/channel_name/123 or https://t.me/channel_name
    pub_match = re.search(r"(?:https?://)?(?:www\.)?t(?:elegram)?\.me/([a-zA-Z0-9_]{4,})(?:/\d+)?", target)
    if pub_match:
        uname = pub_match.group(1)
        if uname.lower() not in ("c", "joinchat", "share", "addstickers", "setlanguage"):
            logger.info(f"Resolved public link to username: @{uname}")
            return await client.get_chat(f"@{uname}")

    # 5. Username format: @mychannel
    if target.startswith("@"):
        return await client.get_chat(target)

    # 6. Integer channel ID: -100..., -..., or raw digits
    clean_num = target.replace(" ", "")
    if clean_num.startswith("-100") and clean_num[4:].isdigit():
        return await client.get_chat(int(clean_num))
    elif clean_num.startswith("-") and clean_num[1:].isdigit():
        try:
            return await client.get_chat(int(clean_num))
        except Exception:
            return await client.get_chat(int(f"-100{clean_num[1:]}"))
    elif clean_num.isdigit():
        try:
            return await client.get_chat(int(f"-100{clean_num}"))
        except Exception:
            return await client.get_chat(int(clean_num))

    # 7. Fallback direct resolution
    return await client.get_chat(target)


@Client.on_message(filters.command(["setdump", "setchannel"]))
async def setdump_handler(client: Client, message: Message):
    # 1. If executed DIRECTLY inside a Channel, Supergroup, or Group:
    chat_type_str = str(getattr(getattr(message, "chat", None), "type", "")).lower()
    is_channel_or_group = any(t in chat_type_str for t in ("channel", "supergroup", "group"))

    if is_channel_or_group:
        user_id = message.from_user.id if getattr(message, "from_user", None) else 0
        if user_id and not is_authorized(user_id):
            return

        try:
            await set_dump_channel(message.chat.id)
            title = message.chat.title or "Dump Channel"
            uname = f"@{message.chat.username}" if getattr(message.chat, "username", None) else "Private Channel"

            await message.reply_text(
                f"<blockquote>"
                f"✅ <b>THIS CHANNEL IS NOW CONFIGURED AS DUMP!</b>\n\n"
                f"• <b>Title:</b> {title}\n"
                f"• <b>ID:</b> <code>{message.chat.id}</code>\n"
                f"• <b>Type:</b> {uname}\n"
                f"• <b>Mode:</b> Server-to-Server High Speed Relay (Option B)\n\n"
                f"<i>All video albums will now be uploaded to this channel and copied to users instantly with zero local disk bloat!</i>"
                f"</blockquote>"
            )
            return
        except Exception as e:
            logger.error(f"Failed to set dump channel directly from chat {message.chat.id}: {e}")
            await message.reply_text(f"❌ Failed to configure dump: <code>{e}</code>")
            return

    # 2. If executed in PRIVATE chat:
    if not is_authorized(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    raw_input = parts[1].strip() if len(parts) > 1 else ""
    reply_to = message.reply_to_message

    if not raw_input and not reply_to:
        await message.reply_text(
            "<blockquote>"
            "⚠️ <b>Usage:</b> <code>/setdump &lt;link / username / ID&gt;</code>\n\n"
            "<b>Auto-Fetch supports all formats:</b>\n"
            "• <b>Run in Channel:</b> Simply type <code>/setdump</code> directly inside the Dump Channel!\n"
            "• <b>Private Message Link:</b> <code>https://t.me/c/1234567890/45</code>\n"
            "• <b>Private Invite Link:</b> <code>https://t.me/+AbCdEfGh...</code>\n"
            "• <b>Public Channel:</b> <code>@mychannel</code> or <code>https://t.me/mychannel</code>\n"
            "• <b>Channel ID:</b> <code>-1001234567890</code> or <code>1234567890</code>\n"
            "• <b>Or Simply:</b> Forward any post from the channel here and reply <code>/setdump</code>!\n\n"
            "<i>Note: Make sure the bot is an Administrator in that channel with 'Post Messages' permission!</i>"
            "</blockquote>"
        )
        return

    status_msg = await message.reply_text("🔍 <i>Fetching channel details & verifying permissions...</i>")

    try:
        chat = await resolve_dump_chat(client, raw_input=raw_input, reply_to=reply_to)
        if not chat:
            raise ValueError("No valid channel target could be identified from your input.")

        # Verify bot permissions in the channel
        perm_info = "Connected ✅"
        try:
            me = await client.get_me()
            member = await client.get_chat_member(chat.id, me.id)
            st = str(getattr(member, "status", "")).lower()
            if "admin" in st or "owner" in st or "creator" in st:
                perm_info = "Administrator (Post Messages allowed) ✅"
            else:
                perm_info = f"Member ({st}) ⚠️ (Ensure Bot has Post permission!)"
        except Exception as p_err:
            logger.debug(f"Could not verify chat member permissions: {p_err}")

        await set_dump_channel(chat.id)

        title = getattr(chat, "title", None) or "Dump Channel"
        uname = f"@{chat.username}" if getattr(chat, "username", None) else "Private Channel"

        await status_msg.edit_text(
            f"<blockquote>"
            f"✅ <b>DUMP CHANNEL CONFIGURED!</b>\n\n"
            f"• <b>Title:</b> {title}\n"
            f"• <b>ID:</b> <code>{chat.id}</code>\n"
            f"• <b>Type:</b> {uname}\n"
            f"• <b>Bot Permission:</b> {perm_info}\n"
            f"• <b>Active Mode:</b> Server-to-Server High Speed Relay (Option B)\n\n"
            f"<i>Video albums will now be uploaded to this channel and copied to your chat instantly with zero local disk usage!</i>"
            f"</blockquote>"
        )
    except Exception as e:
        logger.error(f"Failed to configure dump channel from '{raw_input}': {e}")
        await status_msg.edit_text(
            f"<blockquote>"
            f"❌ <b>Could Not Connect to Channel</b>\n\n"
            f"<b>Reason:</b> <code>{e}</code>\n\n"
            f"<b>Troubleshooting:</b>\n"
            f"1. Make sure you added the Bot to the channel/group as an <b>Administrator</b>.\n"
            f"2. Ensure the Bot has <b>'Post Messages'</b> permission enabled.\n"
            f"3. For private channels, you can also forward any message from the channel here and reply <code>/setdump</code>."
            f"</blockquote>"
        )


@Client.on_message(filters.command(["dump", "getdump"]) & filters.private)
async def getdump_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    dump_id = await get_dump_channel()
    if not dump_id:
        await message.reply_text(
            "<blockquote>"
            "📢 <b>DUMP CHANNEL STATUS</b>\n\n"
            "• <b>Status:</b> Not configured\n"
            "• <b>Active Mode:</b> Direct Local Pipeline (Option A)\n\n"
            "💡 <i>Tip: Send <code>/setdump -100xxxxxxxxxx</code> to enable instant zero-disk server relay!</i>"
            "</blockquote>"
        )
        return

    try:
        chat = await client.get_chat(dump_id)
        title = chat.title
    except Exception:
        title = "Connected"

    await message.reply_text(
        f"<blockquote>"
        f"📢 <b>DUMP CHANNEL STATUS</b>\n\n"
        f"• <b>Title:</b> {title}\n"
        f"• <b>ID:</b> <code>{dump_id}</code>\n"
        f"• <b>Active Mode:</b> Server-to-Server Instant Relay (Option B)\n\n"
        f"<i>Send <code>/cleardump</code> anytime to switch back to direct local pipeline.</i>"
        f"</blockquote>"
    )


@Client.on_message(filters.command("cleardump") & filters.private)
async def cleardump_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    await set_dump_channel(None)
    await message.reply_text(
        "<blockquote>"
        "🗑️ <b>DUMP CHANNEL CLEARED</b>\n\n"
        "Bot has reverted to <b>Direct Local Pipeline (Option A)</b>."
        "</blockquote>"
    )
