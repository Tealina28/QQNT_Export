"""
HTML 格式导出器

单文件 HTML 导出，Apple 极简风格，支持亮/暗主题。
"""

import html
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from parser.models import ParsedMessage, ParsedMember, ElementType
from .base import BaseExporter


class HTMLExporter(BaseExporter):
    """HTML 格式导出器（单文件，所有资源内联或相对路径）"""

    def export(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages: list[ParsedMessage]
    ):
        """导出为 HTML 格式"""
        self.ensure_output_dir()

        # 如果需要复制资源，先创建资源目录并复制图片
        copy_resources = self.config.get('copy_resources', True)
        if copy_resources:
            self._prepare_resources(messages)

        # 构建成员映射
        member_map = {m.platform_id: m for m in members}

        # 补充消息中出现的其他 UID（如被引用消息的发送者）
        from db import DatabaseManager
        db_path = self.config.get('db_path')
        if db_path:
            try:
                from pathlib import Path
                dbman = DatabaseManager(Path(db_path))
                from parser.message import MessageParser
                parser = MessageParser(dbman)

                # 收集所有出现的 UID
                all_uids = set(m.platform_id for m in members)
                for msg in messages:
                    all_uids.add(msg.sender_uid)

                # 查询缺失的成员信息
                for uid in all_uids:
                    if uid not in member_map:
                        # 尝试查询这个 UID 的信息
                        try:
                            member = parser.get_c2c_member(uid)
                            member_map[uid] = member
                        except:
                            pass  # 查询失败，保持 UID
            except:
                pass  # 静默失败

        # 获取所有者 ID（判断"我"）
        owner_id = meta.get('ownerId', '')

        # 构建头像映射（从数据库查询）
        avatar_map = self._build_avatar_map(list(member_map.values()))

        # 按日期分组消息
        messages_by_date = self._group_messages_by_date(messages)

        # 渲染 HTML
        html_content = self._render_html(
            meta=meta,
            members=members,
            messages_by_date=messages_by_date,
            member_map=member_map,
            owner_id=owner_id,
            avatar_map=avatar_map
        )

        # 写入文件
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def get_file_extension(self) -> str:
        return '.html'

    def _prepare_resources(self, messages: list[ParsedMessage]):
        """准备资源文件（复制图片到 resources 目录）"""
        import shutil
        from parser.elements import compute_image_cache_path

        # 创建资源目录
        resources_dir = self.output_path.parent / 'resources'
        resources_dir.mkdir(exist_ok=True)
        images_dir = resources_dir / 'images'
        images_dir.mkdir(exist_ok=True)

        # 获取 pic_path
        pic_path = self.config.get('pic_path')
        if not pic_path:
            return

        pic_path_obj = Path(pic_path)
        if not pic_path_obj.exists():
            return

        # 遍历所有消息，复制图片
        for msg in messages:
            for elem in msg.elements:
                if elem.type == ElementType.IMAGE:
                    md5 = elem.content.get('md5')
                    original = elem.content.get('original', 0)
                    if md5:
                        src_path = compute_image_cache_path(md5, original, pic_path_obj)
                        if src_path and src_path.exists():
                            ext = src_path.suffix or '.jpg'
                            dst_filename = f"{md5}{ext}"
                            dst_path = images_dir / dst_filename

                            # 复制文件（去重：已存在则跳过）
                            if not dst_path.exists():
                                try:
                                    shutil.copy2(src_path, dst_path)
                                except Exception:
                                    pass  # 静默失败

    def _build_avatar_map(self, members: list[ParsedMember]) -> dict[str, str]:
        """构建头像映射（uid -> avatar_url）

        从数据库查询头像 URL（列 20004），添加参数 s=100
        """
        from db import DatabaseManager

        avatar_map = {}

        # 获取 DatabaseManager 实例（从 config 的 db_path）
        db_path = self.config.get('db_path')
        if not db_path:
            return avatar_map

        try:
            from pathlib import Path
            dbman = DatabaseManager(Path(db_path))

            for member in members:
                profile = dbman.profile_info(member.platform_id)
                if profile and profile.avatar_url:
                    # 头像 URL 需要带参数 s=100（缩略图）
                    avatar_url = profile.avatar_url
                    if '?' in avatar_url:
                        avatar_url += '&s=100'
                    else:
                        avatar_url += '?s=100'
                    avatar_map[member.platform_id] = avatar_url
        except Exception:
            # 静默失败，不影响导出
            pass

        return avatar_map

    def _group_messages_by_date(self, messages: list[ParsedMessage]) -> list[tuple[str, list[ParsedMessage]]]:
        """按日期分组消息

        Returns:
            [(date_str, messages), ...]，date_str 格式为 "YYYY-MM-DD"
        """
        from collections import defaultdict
        groups = defaultdict(list)

        for msg in messages:
            date_str = datetime.fromtimestamp(msg.timestamp).strftime('%Y-%m-%d')
            groups[date_str].append(msg)

        # 按日期排序
        return sorted(groups.items(), key=lambda x: x[0])

    def _render_html(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages_by_date: list[tuple[str, list[ParsedMessage]]],
        member_map: dict[str, ParsedMember],
        owner_id: str,
        avatar_map: dict[str, str]
    ) -> str:
        """渲染完整 HTML"""
        chat_name = html.escape(meta.get('name', '聊天记录'))
        chat_type = '群聊' if meta.get('type') == 'group' else '私聊'
        export_time = datetime.fromtimestamp(int(time.time())).strftime('%Y-%m-%d %H:%M')

        # 同时按雪花 ID 和 seq 建立映射；新数据优先使用雪花 ID。
        all_messages = [msg for _, msgs in messages_by_date for msg in msgs]
        message_map = {}
        for message in all_messages:
            message_map[message.msg_id] = message
            message_map.setdefault(str(message.seq), message)

        # 生成时间轴项
        timeline_items_html = []
        for date_str, msgs in messages_by_date:
            # 生成锚点 ID（使用日期字符串）
            date_id = date_str.replace(' ', '-').replace('/', '-')
            timeline_items_html.append(f'''
<div class="timeline-item" onclick="scrollToDate('{date_id}')">
    <div class="date">{date_str}</div>
    <div class="count">{len(msgs)} 条消息</div>
</div>
            ''')

        # 渲染日期块
        date_blocks_html = []
        for date_str, msgs in messages_by_date:
            date_id = date_str.replace(' ', '-').replace('/', '-')
            msgs_html = []
            for msg in msgs:
                msgs_html.append(self._render_message(msg, member_map, owner_id, avatar_map, message_map))

            date_blocks_html.append(f'''
<details class="date-block" open id="date-{date_id}">
    <summary>{date_str} ({len(msgs)} 条)</summary>
    <div class="messages">
        {''.join(msgs_html)}
    </div>
</details>
            ''')

        return HTML_TEMPLATE.format(
            chat_name=chat_name,
            chat_type=chat_type,
            export_time=export_time,
            date_blocks=''.join(date_blocks_html),
            timeline_items=''.join(timeline_items_html)
        )

    def _render_message(
        self,
        msg: ParsedMessage,
        member_map: dict[str, ParsedMember],
        owner_id: str,
        avatar_map: dict[str, str],
        message_map: dict[str, ParsedMessage]
    ) -> str:
        """渲染单条消息"""
        is_self = (msg.sender_uid == owner_id)

        # 获取发送者信息
        sender_member = member_map.get(msg.sender_uid)
        sender_name = sender_member.get_display_name() if sender_member else msg.sender_uid

        # 检查是否为系统消息
        if msg.elements and msg.elements[0].type == ElementType.NOTICE:
            notice_text = self._format_notice_text(msg.elements[0].content, member_map)
            return f'<div class="system-message" id="msg-{html.escape(msg.msg_id)}"><span class="system-text">{html.escape(notice_text)}</span></div>'

        # 格式化时间
        time_str = datetime.fromtimestamp(msg.timestamp).strftime('%H:%M')

        # 头像（优先使用图片 URL，回退到首字母）
        avatar_url = avatar_map.get(msg.sender_uid)
        if avatar_url:
            avatar_html = f'<img src="{html.escape(avatar_url)}" alt="{html.escape(sender_name)}" class="avatar-img">'
        else:
            avatar_char = sender_name[0] if sender_name else '?'
            avatar_html = html.escape(avatar_char)

        # 构建消息内容
        content_html = self._render_message_content(msg.elements, member_map)
        reactions_html = self._render_reactions(msg.reactions)

        # 引用消息（查找被引用的消息内容）
        quoted_html = ''
        quote_key = msg.quoted_msg_id or (
            str(msg.quoted_msg_seq) if msg.quoted_msg_seq else None
        )
        if quote_key:
            quoted_msg = message_map.get(quote_key)
            if quoted_msg:
                # 获取被引用消息的发送者
                quoted_sender = member_map.get(quoted_msg.sender_uid)
                quoted_sender_name = quoted_sender.get_display_name() if quoted_sender else quoted_msg.sender_uid

                # 获取被引用消息的内容（简化版，只取文本）
                quoted_content = self._extract_text_content(quoted_msg.elements)
                if len(quoted_content) > 50:
                    quoted_content = quoted_content[:50] + '...'

                quoted_html = f'''
<div class="quote" onclick="scrollToMessage('{html.escape(quoted_msg.msg_id)}')">
    <div class="quote-sender">{html.escape(quoted_sender_name)}</div>
    <div class="quote-content">{html.escape(quoted_content)}</div>
</div>
            '''
            else:
                quote_element = next(
                    (element for element in msg.elements
                     if element.type == ElementType.QUOTE),
                    None,
                )
                quote_content = quote_element.content if quote_element else {}
                embedded = quote_content.get('quoted_elements', [])
                preview = self._extract_text_content(embedded) if embedded else ''
                preview = preview[:50] + ('...' if len(preview) > 50 else '')
                preview = preview or '引用了一条消息'
                quoted_html = f'''
<div class="quote">
    <div class="quote-content">{html.escape(preview)}</div>
</div>
            '''

        return f'''
<div class="message-group {'is-self' if is_self else 'is-other'}" id="msg-{html.escape(msg.msg_id)}">
    <div class="avatar">{avatar_html}</div>
    <div class="message-wrapper">
        <div class="meta">
            <span class="sender">{html.escape(sender_name)}</span>
            <span class="time">{time_str}</span>
        </div>
        <div class="bubble">
            {quoted_html}
            {content_html}
        </div>
        {reactions_html}
    </div>
</div>
        '''

    def _render_message_content(
        self,
        elements: list,
        member_map: dict[str, ParsedMember]
    ) -> str:
        """渲染消息内容（文本、图片、转发等）"""
        parts = []

        for elem in elements:
            # 跳过 QUOTE 类型（引用消息已在外层处理）
            if elem.type == ElementType.QUOTE:
                continue

            if elem.type == ElementType.TEXT:
                text = html.escape(elem.content.get('text', ''))
                # 简单换行处理
                text = text.replace('\n', '<br>')
                parts.append(f'<div class="text">{text}</div>')

            elif elem.type == ElementType.IMAGE:
                img_html = self._render_image(elem.content)
                if img_html:
                    parts.append(img_html)

            elif elem.type in (ElementType.FILE, ElementType.ONLINE_FILE):
                filename = html.escape(elem.content.get('filename', ''))
                parts.append(f'<div class="text">[文件: {filename}]</div>')

            elif elem.type == ElementType.ONLINE_FOLDER:
                filename = html.escape(elem.content.get('filename', ''))
                parts.append(f'<div class="text">[文件夹: {filename}]</div>')

            elif elem.type == ElementType.VOICE:
                text = elem.content.get('text')
                label = f'[语音: {text}]' if text else '[语音]'
                parts.append(f'<div class="text">{html.escape(label)}</div>')

            elif elem.type == ElementType.VIDEO:
                filename = html.escape(elem.content.get('filename', ''))
                parts.append(f'<div class="text">[视频: {filename}]</div>')

            elif elem.type in (ElementType.APPLICATION, ElementType.MULTI_MSG):
                # 检查是否为转发消息
                fwd_msgs = elem.content.get('forward_messages', [])
                if fwd_msgs:
                    fwd_html = self._render_forward_messages(fwd_msgs, member_map)
                    parts.append(fwd_html)
                else:
                    parts.append('<div class="text">[应用消息]</div>')

            elif elem.type in (ElementType.EMOJI, ElementType.MARKET_FACE, ElementType.BUBBLE_FACE):
                text = elem.content.get('text') or elem.content.get('summary') or '[表情]'
                parts.append(f'<div class="text">{html.escape(text)}</div>')

            elif elem.type == ElementType.RED_PACKET:
                prompt = html.escape(elem.content.get('prompt', ''))
                label = '转账' if elem.content.get('wallet_type') == 'transfer' else '红包'
                parts.append(f'<div class="text">[{label}: {prompt}]</div>')

            elif elem.type == ElementType.CALL:
                text = elem.content.get('text') or '[通话]'
                duration_ms = elem.content.get('duration_ms') or 0
                if duration_ms:
                    text = f'{text} ({duration_ms // 1000}秒)'
                parts.append(f'<div class="text">{html.escape(text)}</div>')

            elif elem.type in (ElementType.MARKDOWN, ElementType.BOT):
                flash = elem.content.get('flash_transfer')
                if flash:
                    name = flash.get('thumbnail_name') or flash.get('file_set_id') or ''
                    parts.append(f'<div class="text">[闪传: {html.escape(name)}]</div>')
                else:
                    text = elem.content.get('summary') or elem.content.get('text') or '[消息]'
                    parts.append(f'<div class="text">{html.escape(text)}</div>')

            elif elem.type == ElementType.MARKDOWN_BUTTON:
                rows = []
                for row in elem.content.get('rows', []):
                    buttons = ''.join(
                        f'<span class="bot-button">{html.escape(button.get("label") or "按钮")}</span>'
                        for button in row
                    )
                    if buttons:
                        rows.append(f'<div class="bot-button-row">{buttons}</div>')
                if rows:
                    parts.append(f'<div class="bot-buttons">{"".join(rows)}</div>')

            elif elem.type == ElementType.LOCATION:
                text = elem.content.get('text') or '位置共享'
                parts.append(f'<div class="text">[位置: {html.escape(text)}]</div>')

            elif elem.type == ElementType.FEED:
                title = elem.content.get('title')
                subtitle = elem.content.get('subtitle')
                content = elem.content.get('content')

                feed_parts = []
                if title:
                    feed_parts.append(f'<strong>{html.escape(title)}</strong>')
                if content:
                    feed_parts.append(html.escape(content))
                if subtitle:
                    feed_parts.append(html.escape(subtitle))

                if feed_parts:
                    parts.append(f'<div class="text">📰 {" | ".join(feed_parts)}</div>')
                else:
                    parts.append('<div class="text">[动态]</div>')

            else:
                # 其他类型暂时用占位符
                parts.append(f'<div class="text">[{elem.type.name}]</div>')

        return ''.join(parts) if parts else '<div class="text">[空消息]</div>'

    def _render_reactions(self, reactions: list) -> str:
        if not reactions:
            return ''
        from emojis import emojis

        items = []
        for reaction in reactions:
            try:
                emoji_key = int(reaction.emoji_id)
            except (TypeError, ValueError):
                emoji_key = reaction.emoji_id
            label = emojis.get(emoji_key, reaction.emoji_id or '表情')
            self_class = ' is-self' if reaction.is_self else ''
            items.append(
                f'<span class="reaction{self_class}">'
                f'{html.escape(str(label))} {reaction.count}</span>'
            )
        return f'<div class="reactions">{"".join(items)}</div>'

    def _render_image(self, content: dict) -> str:
        """渲染图片"""
        from parser.elements import compute_image_cache_path

        md5 = content.get('md5')
        if not md5:
            return '<div class="text">[图片]</div>'

        # 检查是否复制资源
        copy_resources = self.config.get('copy_resources', True)

        if copy_resources:
            # 模式 1：使用已复制到 resources/images/ 的图片
            resources_dir = self.output_path.parent / 'resources' / 'images'
            if resources_dir.exists():
                # 尝试找到对应的图片文件
                for img_file in resources_dir.iterdir():
                    if img_file.stem == md5:
                        # 相对路径（相对于 HTML 文件）
                        rel_path = f"resources/images/{img_file.name}"
                        return f'<img src="{rel_path}" class="message-image" onclick="showImage(\'{rel_path}\')" alt="图片">'
        else:
            # 模式 2：直接指向原始 pic_path 目录（使用相对路径）
            pic_path = self.config.get('pic_path')
            if pic_path:
                pic_path_obj = Path(pic_path)
                original = content.get('original', 0)
                src_path = compute_image_cache_path(md5, original, pic_path_obj)

                if src_path and src_path.exists():
                    # 计算从 HTML 文件到图片的相对路径
                    try:
                        # 使用 os.path.relpath 计算相对路径
                        # output/c2c/张三.html -> ../../../mnt/d/chatpic/chatimg/xxx/Cache_xxx
                        import os
                        html_file = self.output_path.absolute()
                        img_file = src_path.absolute()
                        rel_path = os.path.relpath(img_file, html_file.parent)
                        rel_path_str = rel_path.replace('\\', '/')
                        return f'<img src="{rel_path_str}" class="message-image" onclick="showImage(\'{rel_path_str}\')" alt="图片">'
                    except Exception:
                        # 失败时显示占位符
                        return '<div class="text">[图片]</div>'

        return '<div class="text">[图片]</div>'

    def _render_forward_messages(
        self,
        forward_messages: list[ParsedMessage],
        member_map: dict[str, ParsedMember]
    ) -> str:
        """渲染转发消息"""
        items = []
        for fwd_msg in forward_messages[:10]:  # 最多显示前 10 条
            sender = member_map.get(fwd_msg.sender_uid)
            sender_name = sender.get_display_name() if sender else fwd_msg.sender_uid

            # 简化内容（只取文本）
            content_parts = []
            for elem in fwd_msg.elements:
                if elem.type == ElementType.TEXT:
                    content_parts.append(elem.content.get('text', ''))
                elif elem.type == ElementType.IMAGE:
                    content_parts.append('[图片]')

            content = ''.join(content_parts) or '[消息]'
            # 截断过长内容
            if len(content) > 50:
                content = content[:50] + '...'

            items.append(f'''
<div class="forward-item">
    <span class="forward-sender">{html.escape(sender_name)}</span>: {html.escape(content)}
</div>
            ''')

        more_html = ''
        if len(forward_messages) > 10:
            more_html = f'<div class="forward-more">还有 {len(forward_messages) - 10} 条...</div>'

        return f'''
<div class="forward-container">
    <div class="forward-header">聊天记录 ({len(forward_messages)} 条)</div>
    {''.join(items)}
    {more_html}
</div>
        '''

    def _extract_text_content(self, elements: list) -> str:
        """提取消息的纯文本内容（用于引用预览）"""
        parts = []
        for elem in elements:
            # 跳过 QUOTE 类型（避免递归引用）
            if elem.type == ElementType.QUOTE:
                continue

            if elem.type == ElementType.TEXT:
                parts.append(elem.content.get('text', ''))
            elif elem.type == ElementType.IMAGE:
                parts.append('[图片]')
            elif elem.type in (ElementType.FILE, ElementType.ONLINE_FILE):
                parts.append('[文件]')
            elif elem.type == ElementType.ONLINE_FOLDER:
                parts.append('[文件夹]')
            elif elem.type == ElementType.VOICE:
                parts.append('[语音]')
            elif elem.type == ElementType.VIDEO:
                parts.append('[视频]')
            elif elem.type in (ElementType.EMOJI, ElementType.MARKET_FACE, ElementType.BUBBLE_FACE):
                text = elem.content.get('text') or elem.content.get('summary') or '[表情]'
                parts.append(text)
            elif elem.type in (ElementType.MARKDOWN, ElementType.BOT):
                parts.append(elem.content.get('summary') or elem.content.get('text') or '[消息]')
            elif elem.type == ElementType.MARKDOWN_BUTTON:
                labels = [
                    button.get('label', '')
                    for row in elem.content.get('rows', [])
                    for button in row
                    if button.get('label')
                ]
                if labels:
                    parts.append(f"[按钮: {' | '.join(labels)}]")
        return ''.join(parts) or '[消息]'

    def _format_notice_text(self, content: dict, member_map: dict[str, ParsedMember]) -> str:
        """格式化系统提示文本"""
        notice_type = content.get('notice_type', 'generic')

        if notice_type == 'withdraw':
            recaller_uid = content.get('recaller_uid', '')
            recaller = member_map.get(recaller_uid)
            recaller_name = (recaller.get_display_name() if recaller else None) \
                or content.get('recaller_name') or recaller_uid or '某人'
            return content.get('display_text') or f"{recaller_name} 撤回了一条消息"

        if notice_type in ('interactive', 'invite'):
            actor = member_map.get(content.get('actor_uid', ''))
            target = member_map.get(content.get('target_uid', ''))
            actor_name = (actor.get_display_name() if actor else None) \
                or content.get('actor_name') or '某人'
            target_name = (target.get_display_name() if target else None) \
                or content.get('target_name') or '某人'
            verb = '邀请了' if notice_type == 'invite' else '戳了戳'
            return content.get('text') or f'{actor_name} {verb} {target_name}'

        if notice_type == 'group' and content.get('mute_info'):
            mute = content['mute_info']
            target = member_map.get(mute.get('target_uid', ''))
            target_name = (target.get_display_name() if target else None) \
                or mute.get('target_name') or '某人'
            return content.get('text') or f"{target_name} 被禁言 {mute.get('duration', 0)} 秒"

        # 其他类型直接返回原始文本
        return content.get('text', '[系统消息]')


# ============================================================================
# HTML 模板（内联所有 CSS/JS）
# ============================================================================

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{chat_name} - 聊天记录</title>
    <style>
        /* CSS 变量与主题 */
        :root {{
            --bg-primary: #FFFFFF;
            --bg-secondary: #F5F5F7;
            --text-primary: #000000;
            --text-secondary: #86868B;
            --bubble-self: #007AFF;
            --bubble-other: #E5E5EA;
            --text-self: #FFFFFF;
            --text-other: #000000;
            --border: rgba(0, 0, 0, 0.1);
            --shadow: rgba(0, 0, 0, 0.05);
            --system-bg: #F5F5F7;
            --system-text: #86868B;
        }}

        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-primary: #000000;
                --bg-secondary: #1C1C1E;
                --text-primary: #FFFFFF;
                --text-secondary: #98989D;
                --bubble-self: #0A84FF;
                --bubble-other: #2C2C2E;
                --text-self: #FFFFFF;
                --text-other: #FFFFFF;
                --border: rgba(255, 255, 255, 0.1);
                --shadow: rgba(0, 0, 0, 0.3);
                --system-bg: #2C2C2E;
                --system-text: #98989D;
            }}
        }}

        [data-theme="dark"] {{
            --bg-primary: #000000;
            --bg-secondary: #1C1C1E;
            --text-primary: #FFFFFF;
            --text-secondary: #98989D;
            --bubble-self: #0A84FF;
            --bubble-other: #2C2C2E;
            --text-self: #FFFFFF;
            --text-other: #FFFFFF;
            --border: rgba(255, 255, 255, 0.1);
            --shadow: rgba(0, 0, 0, 0.3);
            --system-bg: #2C2C2E;
            --system-text: #98989D;
        }}

        [data-theme="light"] {{
            --bg-primary: #FFFFFF;
            --bg-secondary: #F5F5F7;
            --text-primary: #000000;
            --text-secondary: #86868B;
            --bubble-self: #007AFF;
            --bubble-other: #E5E5EA;
            --text-self: #FFFFFF;
            --text-other: #000000;
            --border: rgba(0, 0, 0, 0.1);
            --shadow: rgba(0, 0, 0, 0.05);
            --system-bg: #F5F5F7;
            --system-text: #86868B;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Hiragino Sans GB", sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.5;
            font-size: 16px;
            -webkit-font-smoothing: antialiased;
        }}

        /* Header */
        header {{
            background: rgba(255, 255, 255, 0.8);
            -webkit-backdrop-filter: saturate(180%) blur(20px);
            backdrop-filter: saturate(180%) blur(20px);
            position: sticky;
            top: 0;
            z-index: 100;
            border-bottom: 1px solid var(--border);
            padding: 20px;
            text-align: center;
        }}

        @media (prefers-color-scheme: dark) {{
            header {{
                background: rgba(0, 0, 0, 0.8);
            }}
        }}

        [data-theme="dark"] header {{
            background: rgba(0, 0, 0, 0.8);
        }}

        header h1 {{
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }}

        header .meta {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-bottom: 16px;
        }}

        .header-actions {{
            display: flex;
            gap: 12px;
            align-items: center;
            justify-content: center;
            max-width: 500px;
            margin: 0 auto;
        }}

        .search-input {{
            flex: 1;
            padding: 8px 16px;
            border: 1px solid var(--border);
            border-radius: 20px;
            background: var(--bg-secondary);
            color: var(--text-primary);
            font-size: 14px;
            outline: none;
            transition: all 0.2s;
        }}

        .search-input:focus {{
            border-color: var(--bubble-self);
            background: var(--bg-primary);
        }}

        #themeToggle {{
            background: var(--bg-secondary);
            border: none;
            border-radius: 50%;
            width: 36px;
            height: 36px;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}

        #timelineToggle {{
            background: var(--bg-secondary);
            border: none;
            border-radius: 50%;
            width: 36px;
            height: 36px;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}

        /* 时间轴侧边栏 */
        .timeline-sidebar {{
            position: fixed;
            left: -300px;
            top: 0;
            width: 300px;
            height: 100vh;
            background: var(--bg-primary);
            border-right: 1px solid var(--border);
            box-shadow: 2px 0 8px rgba(0,0,0,0.1);
            transition: left 0.3s ease;
            z-index: 1000;
            display: flex;
            flex-direction: column;
        }}

        .timeline-sidebar.active {{
            left: 0;
        }}

        .timeline-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px;
            border-bottom: 1px solid var(--border);
        }}

        .timeline-header h3 {{
            margin: 0;
            font-size: 16px;
            color: var(--text-primary);
        }}

        .timeline-close {{
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--text-secondary);
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .timeline-content {{
            flex: 1;
            overflow-y: auto;
            padding: 10px;
            /* 确保滚动条不被遮挡 */
            padding-right: 4px;
        }}

        /* 自定义滚动条样式（可选） */
        .timeline-content::-webkit-scrollbar {{
            width: 8px;
        }}

        .timeline-content::-webkit-scrollbar-track {{
            background: var(--bg-secondary);
            border-radius: 4px;
        }}

        .timeline-content::-webkit-scrollbar-thumb {{
            background: var(--border);
            border-radius: 4px;
        }}

        .timeline-content::-webkit-scrollbar-thumb:hover {{
            background: var(--text-secondary);
        }}

        .timeline-item {{
            padding: 12px 16px;
            margin: 4px 0;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.2s;
            font-size: 14px;
            color: var(--text-primary);
        }}

        .timeline-item:hover {{
            background: var(--bg-secondary);
        }}

        .timeline-item .date {{
            font-weight: 600;
            margin-bottom: 4px;
        }}

        .timeline-item .count {{
            font-size: 12px;
            color: var(--text-secondary);
        }}

        /* Main */
        main {{
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}

        /* 日期块 */
        .date-block {{
            margin-bottom: 30px;
            border: none;
        }}

        .date-block summary {{
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            padding: 10px 0;
            cursor: pointer;
            list-style: none;
            text-align: center;
        }}

        .date-block summary::-webkit-details-marker {{
            display: none;
        }}

        .messages {{
            padding-top: 10px;
        }}

        /* 消息组 */
        .message-group {{
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
        }}

        .message-group.is-self {{
            flex-direction: row-reverse;
        }}

        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--bg-secondary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            flex-shrink: 0;
            overflow: hidden;
        }}

        .avatar-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}

        .message-wrapper {{
            max-width: 70%;
        }}

        .meta {{
            display: flex;
            gap: 8px;
            align-items: baseline;
            margin-bottom: 4px;
            font-size: 12px;
        }}

        .is-self .meta {{
            flex-direction: row-reverse;
        }}

        .sender {{
            font-weight: 600;
            color: var(--text-primary);
        }}

        .time {{
            color: var(--text-secondary);
        }}

        .bubble {{
            background: var(--bubble-other);
            color: var(--text-other);
            padding: 10px 14px;
            border-radius: 18px;
            box-shadow: 0 1px 2px var(--shadow);
        }}

        .is-self .bubble {{
            background: var(--bubble-self);
            color: var(--text-self);
        }}

        .reactions {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 5px;
        }}

        .is-self .reactions {{
            justify-content: flex-end;
        }}

        .reaction {{
            padding: 2px 7px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--bg-secondary);
            color: var(--text-secondary);
            font-size: 12px;
        }}

        .reaction.is-self {{
            border-color: var(--bubble-self);
            color: var(--bubble-self);
        }}

        .bot-buttons {{
            display: grid;
            gap: 6px;
            margin-top: 6px;
        }}

        .bot-button-row {{
            display: flex;
            gap: 6px;
        }}

        .bot-button {{
            flex: 1;
            padding: 6px 8px;
            border: 1px solid var(--border);
            border-radius: 6px;
            text-align: center;
            font-size: 13px;
        }}

        .text {{
            word-break: break-word;
        }}

        /* 图片 */
        .message-image {{
            max-width: 100%;
            max-height: 300px;
            border-radius: 12px;
            cursor: pointer;
            display: block;
            margin-top: 6px;
        }}

        /* 引用 */
        .quote {{
            background: rgba(0, 0, 0, 0.1);
            padding: 8px 10px;
            border-radius: 8px;
            margin-bottom: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: background 0.2s;
            border-left: 3px solid var(--bubble-self);
        }}

        .quote:hover {{
            background: rgba(0, 0, 0, 0.15);
        }}

        .is-self .quote {{
            background: rgba(255, 255, 255, 0.2);
        }}

        .is-self .quote:hover {{
            background: rgba(255, 255, 255, 0.3);
        }}

        .quote-sender {{
            font-weight: 600;
            font-size: 12px;
            margin-bottom: 4px;
            color: var(--bubble-self);
        }}

        .quote-content {{
            opacity: 0.9;
        }}

        /* 消息高亮动画 */
        @keyframes highlightMessage {{
            0%, 100% {{
                background: transparent;
            }}
            50% {{
                background: rgba(255, 235, 59, 0.3);
            }}
        }}

        .message-highlight {{
            animation: highlightMessage 2s ease;
        }}

        /* 转发消息 */
        .forward-container {{
            background: rgba(0, 0, 0, 0.05);
            padding: 10px;
            border-radius: 12px;
            font-size: 14px;
        }}

        .is-self .forward-container {{
            background: rgba(255, 255, 255, 0.15);
        }}

        .forward-header {{
            font-weight: 600;
            margin-bottom: 8px;
        }}

        .forward-item {{
            padding: 4px 0;
            border-bottom: 1px solid rgba(0, 0, 0, 0.05);
        }}

        .forward-item:last-child {{
            border-bottom: none;
        }}

        .forward-sender {{
            font-weight: 600;
            margin-right: 4px;
        }}

        .forward-more {{
            margin-top: 8px;
            color: var(--text-secondary);
            font-style: italic;
        }}

        /* 系统消息 */
        .system-message {{
            text-align: center;
            margin: 16px 0;
        }}

        .system-text {{
            display: inline-block;
            background: var(--system-bg);
            color: var(--system-text);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 13px;
        }}

        /* 图片预览模态框 */
        #imageModal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        }}

        #modalImage {{
            max-width: 90%;
            max-height: 90%;
            border-radius: 8px;
        }}

        /* 搜索高亮 */
        .message-group.hidden {{
            display: none;
        }}

        .highlight {{
            background: #FFEB3B;
            color: #000;
            padding: 2px 4px;
            border-radius: 4px;
        }}

        [data-theme="dark"] .highlight {{
            background: #FBC02D;
            color: #000;
        }}

        /* 响应式 */
        @media (max-width: 600px) {{
            main {{
                padding: 10px;
            }}

            .message-wrapper {{
                max-width: 80%;
            }}

            header h1 {{
                font-size: 20px;
            }}

            header {{
                padding: 15px;
            }}

            .header-actions {{
                flex-direction: column;
                width: 100%;
            }}

            .search-input {{
                width: 100%;
            }}

            #themeToggle {{
                width: 32px;
                height: 32px;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>{chat_name}</h1>
        <div class="meta">{chat_type} | 导出时间: {export_time}</div>
        <div class="header-actions">
            <input type="text" id="searchInput" placeholder="搜索消息..." class="search-input">
            <button id="themeToggle">🌙</button>
            <button id="timelineToggle" title="时间轴">📅</button>
        </div>
    </header>

    <div class="timeline-sidebar" id="timelineSidebar">
        <div class="timeline-header">
            <h3>时间轴</h3>
            <button class="timeline-close" onclick="toggleTimeline()">×</button>
        </div>
        <div class="timeline-content">
            {timeline_items}
        </div>
    </div>

    <main>
        {date_blocks}
    </main>

    <div id="imageModal" onclick="closeModal()">
        <img id="modalImage" src="" alt="">
    </div>

    <script>
        // 主题切换
        const themeToggle = document.getElementById('themeToggle');
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme) {{
            document.documentElement.setAttribute('data-theme', savedTheme);
            themeToggle.textContent = savedTheme === 'dark' ? '☀️' : '🌙';
        }}

        themeToggle.onclick = () => {{
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
            themeToggle.textContent = next === 'dark' ? '☀️' : '🌙';
        }};

        // 时间轴切换
        const timelineToggle = document.getElementById('timelineToggle');
        const timelineSidebar = document.getElementById('timelineSidebar');

        function toggleTimeline() {{
            timelineSidebar.classList.toggle('active');
        }}

        timelineToggle.onclick = toggleTimeline;

        // 图片预览
        function showImage(src) {{
            const modal = document.getElementById('imageModal');
            const img = document.getElementById('modalImage');
            img.src = src;
            modal.style.display = 'flex';
        }}

        function closeModal() {{
            document.getElementById('imageModal').style.display = 'none';
        }}

        // 搜索功能
        const searchInput = document.getElementById('searchInput');
        let searchTimeout;

        searchInput.addEventListener('input', (e) => {{
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {{
                const query = e.target.value.toLowerCase().trim();
                const messages = document.querySelectorAll('.message-group');
                const dateBlocks = document.querySelectorAll('.date-block');

                if (!query) {{
                    // 清空搜索，显示所有消息
                    messages.forEach(msg => msg.classList.remove('hidden'));
                    dateBlocks.forEach(block => block.open = true);
                    // 移除所有高亮
                    document.querySelectorAll('.highlight').forEach(el => {{
                        const text = el.textContent;
                        el.outerHTML = text;
                    }});
                    return;
                }}

                let hasVisibleMessages = false;

                dateBlocks.forEach(block => {{
                    const blockMessages = block.querySelectorAll('.message-group');
                    let blockHasVisible = false;

                    blockMessages.forEach(msg => {{
                        // 移除旧高亮
                        msg.querySelectorAll('.highlight').forEach(el => {{
                            const text = el.textContent;
                            el.outerHTML = text;
                        }});

                        const text = msg.textContent.toLowerCase();
                        if (text.includes(query)) {{
                            msg.classList.remove('hidden');
                            blockHasVisible = true;
                            hasVisibleMessages = true;

                            // 高亮匹配文本
                            const bubble = msg.querySelector('.bubble');
                            if (bubble) {{
                                highlightText(bubble, query);
                            }}
                        }} else {{
                            msg.classList.add('hidden');
                        }}
                    }});

                    // 展开有匹配的日期块
                    block.open = blockHasVisible;
                }});
            }}, 300); // 防抖 300ms
        }});

        function highlightText(element, query) {{
            const walker = document.createTreeWalker(
                element,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );

            const nodesToReplace = [];
            let node;

            while (node = walker.nextNode()) {{
                const text = node.textContent.toLowerCase();
                if (text.includes(query)) {{
                    nodesToReplace.push(node);
                }}
            }}

            nodesToReplace.forEach(node => {{
                const text = node.textContent;
                const lowerText = text.toLowerCase();
                const index = lowerText.indexOf(query);

                if (index !== -1) {{
                    const before = text.substring(0, index);
                    const match = text.substring(index, index + query.length);
                    const after = text.substring(index + query.length);

                    const fragment = document.createDocumentFragment();
                    if (before) fragment.appendChild(document.createTextNode(before));

                    const mark = document.createElement('span');
                    mark.className = 'highlight';
                    mark.textContent = match;
                    fragment.appendChild(mark);

                    if (after) fragment.appendChild(document.createTextNode(after));

                    node.parentNode.replaceChild(fragment, node);
                }}
            }});
        }}

        // 跳转到引用的消息
        function scrollToMessage(msgId) {{
            const targetMsg = document.getElementById('msg-' + msgId);
            if (!targetMsg) {{
                return; // 消息不在当前导出范围内
            }}

            // 展开目标消息所在的日期块
            let parent = targetMsg.parentElement;
            while (parent) {{
                if (parent.tagName === 'DETAILS') {{
                    parent.open = true;
                    break;
                }}
                parent = parent.parentElement;
            }}

            // 滚动到目标消息
            targetMsg.scrollIntoView({{ behavior: 'smooth', block: 'center' }});

            // 添加高亮动画
            targetMsg.classList.add('message-highlight');
            setTimeout(() => {{
                targetMsg.classList.remove('message-highlight');
            }}, 2000);
        }}

        // 滚动到指定日期
        function scrollToDate(dateId) {{
            const targetDate = document.getElementById('date-' + dateId);
            if (!targetDate) {{
                return;
            }}

            // 展开日期块
            targetDate.open = true;

            // 滚动到日期块
            targetDate.scrollIntoView({{ behavior: 'smooth', block: 'start' }});

            // 关闭时间轴
            toggleTimeline();
        }}

        // 键盘快捷键
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                closeModal();
                searchInput.blur();
            }}
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {{
                e.preventDefault();
                searchInput.focus();
            }}
        }});
    </script>
</body>
</html>
'''
