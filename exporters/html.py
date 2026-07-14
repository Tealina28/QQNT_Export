"""
HTML 格式导出器

单文件 HTML 导出，面向长聊天记录浏览，支持搜索、筛选和亮/暗主题。
"""

import html
import json
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from parser.models import ParsedMessage, ParsedMember, ElementType
from .base import BaseExporter


class HTMLExporter(BaseExporter):
    """HTML 格式导出器（单文件，所有资源内联或相对路径）"""

    streams_messages = True
    supports_incremental_messages = True

    def __init__(self, output_path: Path, config: dict[str, Any]):
        super().__init__(output_path, config)
        self._image_resource_map: dict[str, str] = {}
        self._stream_state: dict[str, Any] | None = None

    def export(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages: Iterable[ParsedMessage]
    ):
        """导出为 HTML 格式"""
        self.ensure_output_dir()

        if not isinstance(messages, list):
            self._export_streaming(meta, members, messages)
            return

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
                            if member:
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

    def _export_streaming(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages: Iterable[ParsedMessage],
    ) -> None:
        """逐条写出 HTML，避免大规模会话同时常驻内存。"""
        self.start_stream(meta, members)
        try:
            for message in messages:
                self.write_message(message)
        except Exception:
            self.abort_stream()
            raise
        else:
            self.finish_stream()

    def start_stream(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
    ) -> None:
        self.ensure_output_dir()
        member_map = {member.platform_id: member for member in members}
        owner_id = meta.get('ownerId', '')
        avatar_map = self._build_avatar_map(members)
        marker = '__QQNT_STREAMED_DATE_BLOCKS__'
        template = HTML_TEMPLATE.format(
            chat_name=html.escape(meta.get('name', '聊天记录')),
            chat_type='群聊' if meta.get('type') == 'group' else '私聊',
            export_time=datetime.fromtimestamp(int(time.time())).strftime('%Y-%m-%d %H:%M'),
            message_count=0,
            member_count=0,
            date_range='统计中',
            date_blocks=marker,
            timeline_items='',
            sender_options='',
        )
        prefix, suffix = template.split(marker, 1)
        output = open(self.output_path, 'w', encoding='utf-8')
        self._stream_state = {
            'output': output,
            'suffix': suffix,
            'member_map': member_map,
            'owner_id': owner_id,
            'avatar_map': avatar_map,
            'message_count': 0,
            'sender_uids': set(),
            'date_counts': {},
            'first_date': None,
            'last_date': None,
            'current_date': None,
        }
        output.write(prefix)

    def write_message(self, message: ParsedMessage) -> None:
        state = self._stream_state
        if state is None:
            raise RuntimeError('HTML stream is not open')
        output = state['output']
        self._prepare_message_resources(message)
        date_str = datetime.fromtimestamp(message.timestamp).strftime('%Y-%m-%d')
        date_id = date_str.replace(' ', '-').replace('/', '-')
        if date_str != state['current_date']:
            if state['current_date'] is not None:
                output.write('</div></section>')
            output.write(
                f'<section class="date-block" id="date-{date_id}" data-date="{date_id}">'
                f'<div class="date-divider"><span>{date_str}</span>'
                f'<small data-date-count="{date_id}">0 条</small></div>'
                '<div class="messages">'
            )
            state['current_date'] = date_str
        output.write(self._render_message(
            message,
            state['member_map'],
            state['owner_id'],
            state['avatar_map'],
            {},
        ))
        state['message_count'] += 1
        state['sender_uids'].add(message.sender_uid)
        state['date_counts'][date_str] = state['date_counts'].get(date_str, 0) + 1
        state['first_date'] = state['first_date'] or date_str
        state['last_date'] = date_str

    def finish_stream(self) -> None:
        state = self._stream_state
        if state is None:
            return
        output = state['output']
        try:
            if state['current_date'] is not None:
                output.write('</div></section>')
            sender_options = []
            for uid in sorted(
                state['sender_uids'],
                key=lambda item: (
                    str(state['member_map'][item].get_display_name() or item)
                    if state['member_map'].get(item) else str(item or '')
                ),
            ):
                member = state['member_map'].get(uid)
                sender_options.append({
                    'uid': str(uid),
                    'name': str(member.get_display_name() if member else uid),
                })
            first_date = state['first_date']
            last_date = state['last_date']
            date_range = '无消息'
            if first_date:
                date_range = (
                    first_date if first_date == last_date
                    else f'{first_date} 至 {last_date}'
                )
            metadata = json.dumps({
                'messageCount': state['message_count'],
                'memberCount': len(state['sender_uids']),
                'dateRange': date_range,
                'dateCounts': state['date_counts'],
                'senders': sender_options,
            }, ensure_ascii=False).replace('</', '<\\/')
            output.write(
                f'<script>window.__QQNT_EXPORT_META__={metadata};</script>'
            )
            output.write(state['suffix'])
        finally:
            output.close()
            self._stream_state = None

    def abort_stream(self) -> None:
        state = self._stream_state
        if state is not None:
            state['output'].close()
            self._stream_state = None

    def get_file_extension(self) -> str:
        return '.html'

    def _prepare_resources(self, messages: list[ParsedMessage]):
        """准备资源文件（复制图片到 resources 目录）"""
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
            for elem in self._iter_resource_elements(msg.elements):
                if elem.type == ElementType.IMAGE:
                    self._copy_image_resource(elem.content, pic_path_obj, images_dir)

    def _prepare_message_resources(self, message: ParsedMessage) -> None:
        if not self.config.get('copy_resources', True):
            return
        pic_path = self.config.get('pic_path')
        if not pic_path:
            return
        pic_path_obj = Path(pic_path)
        if not pic_path_obj.exists():
            return
        images_dir = self.output_path.parent / 'resources' / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        for element in self._iter_resource_elements(message.elements):
            if element.type == ElementType.IMAGE:
                self._copy_image_resource(
                    element.content, pic_path_obj, images_dir
                )

    def _copy_image_resource(
        self,
        content: dict,
        pic_path: Path,
        images_dir: Path,
    ) -> None:
        import shutil
        from parser.elements import compute_image_cache_path

        md5 = content.get('md5')
        if not md5 or md5 in self._image_resource_map:
            return
        source = compute_image_cache_path(
            md5, content.get('original', 0), pic_path
        )
        if not source:
            return
        destination = images_dir / f"{md5}{source.suffix or '.jpg'}"
        try:
            if not destination.exists():
                shutil.copy2(source, destination)
            self._image_resource_map[md5] = (
                f'resources/images/{destination.name}'
            )
        except OSError:
            return

    def _iter_resource_elements(self, elements: list):
        """递归遍历正文、引用缓存和合并转发中的资源元素。"""
        for element in elements:
            yield element
            if element.type == ElementType.QUOTE:
                yield from self._iter_resource_elements(
                    element.content.get('quoted_elements', [])
                )
            for message in element.content.get('forward_messages', []):
                yield from self._iter_resource_elements(message.elements)

    def _build_avatar_map(self, members: list[ParsedMember]) -> dict[str, str]:
        """构建头像映射，优先使用本地缓存并回退成员头像 URL。"""
        import os
        import shutil
        from parser.avatar import find_local_avatar, image_extension

        avatar_map = {}

        copy_resources = self.config.get('copy_resources', True)
        avatar_path = self.config.get('avatar_path')
        avatars_dir = self.output_path.parent / 'resources' / 'avatars'

        for member in members:
            local = find_local_avatar(
                avatar_path, member.platform_id, scope='user'
            )
            if local:
                try:
                    if copy_resources:
                        avatars_dir.mkdir(parents=True, exist_ok=True)
                        destination = avatars_dir / (
                            f'{member.platform_id}{image_extension(local)}'
                        )
                        if not destination.exists():
                            shutil.copy2(local, destination)
                        avatar_map[member.platform_id] = (
                            f'resources/avatars/{destination.name}'
                        )
                    else:
                        relative = os.path.relpath(
                            local.absolute(), self.output_path.parent.absolute()
                        )
                        avatar_map[member.platform_id] = relative.replace('\\', '/')
                    continue
                except OSError:
                    pass
            if member.avatar:
                avatar_map[member.platform_id] = member.avatar

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

        message_count = len(all_messages)
        if all_messages:
            first_date = datetime.fromtimestamp(
                all_messages[0].timestamp
            ).strftime('%Y-%m-%d')
            last_date = datetime.fromtimestamp(
                all_messages[-1].timestamp
            ).strftime('%Y-%m-%d')
            date_range = (
                first_date if first_date == last_date
                else f'{first_date} 至 {last_date}'
            )
        else:
            date_range = '无消息'

        sender_uids = {message.sender_uid for message in all_messages}
        sender_options = []
        for uid in sorted(
            sender_uids,
            key=lambda item: (
                str(member_map[item].get_display_name() or item)
                if member_map.get(item) else str(item or '')
            ),
        ):
            member = member_map.get(uid)
            name = str(member.get_display_name() if member else uid)
            sender_options.append(
                f'<option value="{html.escape(str(uid), quote=True)}">'
                f'{html.escape(name)}</option>'
            )

        # 生成时间轴项
        timeline_items_html = []
        for date_str, msgs in messages_by_date:
            # 生成锚点 ID（使用日期字符串）
            date_id = date_str.replace(' ', '-').replace('/', '-')
            timeline_items_html.append(f'''
<button class="timeline-item" data-date="{date_id}" onclick="scrollToDate('{date_id}')">
    <div class="date">{date_str}</div>
    <div class="count">{len(msgs)} 条消息</div>
</button>
            ''')

        # 渲染日期块
        date_blocks_html = []
        for date_str, msgs in messages_by_date:
            date_id = date_str.replace(' ', '-').replace('/', '-')
            msgs_html = []
            for msg in msgs:
                msgs_html.append(self._render_message(msg, member_map, owner_id, avatar_map, message_map))

            date_blocks_html.append(f'''
<section class="date-block" id="date-{date_id}" data-date="{date_id}">
    <div class="date-divider"><span>{date_str}</span><small>{len(msgs)} 条</small></div>
    <div class="messages">
        {''.join(msgs_html)}
    </div>
</section>
            ''')

        return HTML_TEMPLATE.format(
            chat_name=chat_name,
            chat_type=chat_type,
            export_time=export_time,
            message_count=message_count,
            member_count=len(sender_uids),
            date_range=html.escape(date_range),
            date_blocks=''.join(date_blocks_html),
            timeline_items=''.join(timeline_items_html),
            sender_options=''.join(sender_options),
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
            search_text = html.escape(notice_text.lower(), quote=True)
            full_time = datetime.fromtimestamp(msg.timestamp).strftime(
                '%Y-%m-%d %H:%M:%S'
            )
            return (
                f'<div class="message-entry system-message" '
                f'id="msg-{html.escape(msg.msg_id)}" '
                f'data-message-seq="{msg.seq}" '
                f'data-search="{search_text}" data-sender="">'
                f'<span class="system-text">{html.escape(notice_text)}</span>'
                f'<time title="{full_time}">'
                f'{datetime.fromtimestamp(msg.timestamp).strftime("%H:%M")}'
                f'</time></div>'
            )

        # 格式化时间
        time_str = datetime.fromtimestamp(msg.timestamp).strftime('%H:%M')
        full_time = datetime.fromtimestamp(msg.timestamp).strftime(
            '%Y-%m-%d %H:%M:%S'
        )

        # 头像（优先使用图片 URL，回退到首字母）
        avatar_url = avatar_map.get(msg.sender_uid)
        if avatar_url:
            avatar_html = (
                f'<img src="{html.escape(avatar_url, quote=True)}" '
                f'alt="{html.escape(sender_name, quote=True)}" '
                'class="avatar-img" '
                'onerror="this.style.display=\'none\'; '
                'this.parentElement.textContent=this.alt.slice(0,1)||\'?\'">'
            )
        else:
            avatar_char = sender_name[0] if sender_name else '?'
            avatar_html = html.escape(avatar_char)

        # 构建消息内容
        content_html = self._render_message_content(msg.elements, member_map)
        reactions_html = self._render_reactions(msg.reactions)

        # 引用消息（查找被引用的消息内容）
        quoted_html = ''
        quote_element = next(
            (element for element in msg.elements
             if element.type == ElementType.QUOTE),
            None,
        )
        quote_content = quote_element.content if quote_element else {}
        quote_keys = []
        for value in (
            quote_content.get('orig_msg_id_ref'),
            msg.quoted_msg_id,
            msg.quoted_msg_seq,
        ):
            if value:
                key = str(value)
                if key not in quote_keys:
                    quote_keys.append(key)

        if quote_keys:
            quoted_msg = next(
                (message_map[key] for key in quote_keys if key in message_map),
                None,
            )
            if quoted_msg:
                # 获取被引用消息的发送者
                quoted_sender = member_map.get(quoted_msg.sender_uid)
                quoted_sender_name = quoted_sender.get_display_name() if quoted_sender else quoted_msg.sender_uid

                # 获取被引用消息的内容（简化版，只取文本）
                quoted_content = self._render_quote_preview(quoted_msg.elements)

                quoted_html = f'''
<button type="button" class="quote quote-link" data-target-message-id="{html.escape(quoted_msg.msg_id, quote=True)}" title="跳转到被引用的消息">
    <div class="quote-sender">{html.escape(quoted_sender_name)}</div>
    <div class="quote-content">{quoted_content}</div>
    <span class="quote-jump" aria-hidden="true">↗</span>
</button>
            '''
            else:
                embedded = quote_content.get('quoted_elements', [])
                preview = self._render_quote_preview(embedded)
                quoted_sender = member_map.get(quote_content.get('sender_uid', ''))
                quoted_sender_name = (
                    quoted_sender.get_display_name() if quoted_sender else ''
                )
                sender_html = (
                    f'<div class="quote-sender">{html.escape(quoted_sender_name)}</div>'
                    if quoted_sender_name else ''
                )
                target_reference = (
                    quote_content.get('orig_msg_id_ref')
                    or msg.quoted_msg_id
                    or quote_content.get('orig_msg_id')
                    or msg.quoted_msg_seq
                    or quote_content.get('orig_msg_seq')
                )
                target_attr = ''
                target_class = 'quote'
                if target_reference:
                    target_attr = (
                        f' data-target-message-id="{html.escape(str(target_reference), quote=True)}"'
                        ' title="跳转到被引用的消息"'
                    )
                    target_class += ' quote-link'
                quoted_html = f'''
<button type="button" class="{target_class}"{target_attr}>
    {sender_html}
    <div class="quote-content">{preview}</div>
</button>
            '''

        search_text = ' '.join((
            sender_name,
            self._extract_text_content(msg.elements),
        )).lower()
        return f'''
<div class="message-entry message-group {'is-self' if is_self else 'is-other'}" id="msg-{html.escape(msg.msg_id)}" data-message-seq="{msg.seq}" data-search="{html.escape(search_text, quote=True)}" data-sender="{html.escape(msg.sender_uid, quote=True)}">
    <div class="avatar">{avatar_html}</div>
    <div class="message-wrapper">
        <div class="meta">
            <span class="sender">{html.escape(sender_name)}</span>
            <time class="time" title="{full_time}">{time_str}</time>
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
        member_map: dict[str, ParsedMember],
        forward_depth: int = 0,
    ) -> str:
        """渲染消息内容（文本、图片、转发等）"""
        parts = []

        for elem in elements:
            if elem.content.get('recovered_message_body'):
                continue
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
                parts.append(
                    '<div class="attachment-card">'
                    '<span class="attachment-icon">文</span>'
                    '<span><strong>文件</strong>'
                    f'<small>{filename or "未知文件"}</small></span></div>'
                )

            elif elem.type == ElementType.ONLINE_FOLDER:
                filename = html.escape(elem.content.get('filename', ''))
                parts.append(
                    '<div class="attachment-card">'
                    '<span class="attachment-icon">目</span>'
                    '<span><strong>文件夹</strong>'
                    f'<small>{filename or "未命名文件夹"}</small></span></div>'
                )

            elif elem.type == ElementType.VOICE:
                text = elem.content.get('text')
                duration = elem.content.get('duration') or 0
                voice_type = 'AI 语音' if elem.content.get('is_ai_voice') else '语音'
                label = text or '未转写语音'
                if duration:
                    label = f'{label} · {duration}秒'
                parts.append(
                    f'<div class="media-chip"><span>{voice_type}</span>'
                    f'{html.escape(label)}</div>'
                )

            elif elem.type == ElementType.VIDEO:
                filename = html.escape(elem.content.get('filename', ''))
                parts.append(
                    '<div class="attachment-card">'
                    '<span class="attachment-icon">影</span>'
                    '<span><strong>视频</strong>'
                    f'<small>{filename or "未知视频"}</small></span></div>'
                )

            elif elem.type in (ElementType.APPLICATION, ElementType.MULTI_MSG):
                # 检查是否为转发消息
                fwd_msgs = elem.content.get('forward_messages', [])
                if fwd_msgs:
                    fwd_html = self._render_forward_messages(
                        fwd_msgs,
                        member_map,
                        forward_depth,
                    )
                    parts.append(fwd_html)
                elif elem.type == ElementType.APPLICATION:
                    parts.append(self._render_application_card(elem.content))
                else:
                    parts.append('<div class="placeholder-card">应用消息</div>')

            elif elem.type in (ElementType.EMOJI, ElementType.MARKET_FACE, ElementType.BUBBLE_FACE):
                text = elem.content.get('text') or elem.content.get('summary') or '[表情]'
                parts.append(f'<div class="text">{html.escape(text)}</div>')

            elif elem.type == ElementType.RED_PACKET:
                prompt = html.escape(elem.content.get('prompt', ''))
                labels = {
                    'transfer': '转账',
                    'normal': '普通红包',
                    'lucky': '拼手气红包',
                    'password': '口令红包',
                    'designated': '专属红包',
                    'voice': '语音红包',
                }
                kind = elem.content.get('redbag_kind')
                label = labels.get(kind)
                if not label:
                    raw_type = elem.content.get('redbag_type')
                    label = f'红包（类型 {raw_type}）' if raw_type else '红包'
                designated = ''
                designated_num = elem.content.get('designated_num')
                if designated_num:
                    target = next(
                        (
                            member for member in member_map.values()
                            if member.qq_num == designated_num
                        ),
                        None,
                    )
                    target_name = (
                        target.get_display_name() if target else str(designated_num)
                    )
                    designated = (
                        f'<small>指定领取人：{html.escape(target_name)}</small>'
                    )
                parts.append(
                    f'<div class="wallet-card wallet-{html.escape(kind or "unknown")}">'
                    f'<strong>{label}</strong>'
                    f'<span>{prompt or "QQ 钱包消息"}</span>{designated}</div>'
                )

            elif elem.type == ElementType.CALL:
                text = elem.content.get('text') or '[通话]'
                duration_ms = elem.content.get('duration_ms') or 0
                if duration_ms:
                    text = f'{text} ({duration_ms // 1000}秒)'
                parts.append(
                    f'<div class="media-chip"><span>通话</span>'
                    f'{html.escape(text)}</div>'
                )

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
                parts.append(
                    '<div class="attachment-card">'
                    '<span class="attachment-icon">位</span>'
                    '<span><strong>位置</strong>'
                    f'<small>{html.escape(text)}</small></span></div>'
                )

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
                    parts.append(
                        f'<div class="feed-card">{"<br>".join(feed_parts)}</div>'
                    )
                else:
                    parts.append('<div class="placeholder-card">动态</div>')

            else:
                # 其他类型暂时用占位符
                parts.append(
                    f'<div class="placeholder-card">{elem.type.name}</div>'
                )

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

    @staticmethod
    def _render_application_card(content: dict) -> str:
        kind = content.get('card_kind') or 'share'
        title = html.escape(content.get('title') or content.get('prompt') or '应用消息')
        description = html.escape(content.get('description') or '')
        footer = html.escape(content.get('footer') or '')
        image_url = content.get('image_url') or ''
        target_url = content.get('target_url') or ''

        labels = {
            'announcement': '群公告',
            'location': '位置',
            'contact': '名片',
            'music': '音乐分享',
            'miniapp': 'QQ 小程序',
            'share': '分享卡片',
        }
        label = labels.get(kind, '应用消息')
        image = ''
        if image_url:
            safe_image = html.escape(image_url, quote=True)
            image = f'<img class="ark-image" src="{safe_image}" alt="" loading="lazy">'
        body = (
            f'<div class="ark-label">{html.escape(label)}</div>'
            f'<strong>{title}</strong>'
            f'{f"<span>{description}</span>" if description else ""}'
            f'{image}'
            f'{f"<small>{footer}</small>" if footer else ""}'
        )
        if target_url.startswith(('http://', 'https://')):
            safe_url = html.escape(target_url, quote=True)
            return f'<a class="ark-card ark-{kind}" href="{safe_url}" target="_blank" rel="noreferrer">{body}</a>'
        return f'<div class="ark-card ark-{kind}">{body}</div>'

    def _render_image(self, content: dict) -> str:
        """渲染图片"""
        image_source = self._resolve_image_source(content)
        if not image_source:
            return '<div class="text">[图片]</div>'
        path_attr = html.escape(image_source, quote=True)
        return (
            f'<button class="image-button" type="button" '
            f'data-src="{path_attr}" '
            f'onclick="showImage(this.dataset.src)">'
            f'<img src="{path_attr}" class="message-image" '
            f'alt="图片" loading="lazy"></button>'
        )

    def _resolve_image_source(self, content: dict) -> str | None:
        """返回图片相对路径，不生成可交互 HTML。"""
        from parser.elements import compute_image_cache_path

        md5 = content.get('md5')
        if not md5:
            return None

        # 检查是否复制资源
        copy_resources = self.config.get('copy_resources', True)

        if copy_resources:
            return self._image_resource_map.get(md5)
        else:
            # 模式 2：直接指向原始 pic_path 目录（使用相对路径）
            pic_path = self.config.get('pic_path')
            if pic_path:
                pic_path_obj = Path(pic_path)
                original = content.get('original', 0)
                src_path = compute_image_cache_path(md5, original, pic_path_obj)

                if src_path:
                    # 计算从 HTML 文件到图片的相对路径
                    try:
                        # 使用 os.path.relpath 计算相对路径
                        # output/c2c/张三.html -> ../../../mnt/d/chatpic/chatimg/xxx/Cache_xxx
                        import os
                        html_file = self.output_path.absolute()
                        img_file = src_path.absolute()
                        rel_path = os.path.relpath(img_file, html_file.parent)
                        return rel_path.replace('\\', '/')
                    except (OSError, ValueError):
                        return None

        return None

    def _render_forward_messages(
        self,
        forward_messages: list[ParsedMessage],
        member_map: dict[str, ParsedMember],
        depth: int = 0,
    ) -> str:
        """渲染可展开的合并转发消息，支持递归嵌套。"""
        if depth >= 4:
            return '<div class="forward-more">嵌套转发层级过深</div>'

        visible_messages = forward_messages[:100]
        items = []
        for fwd_msg in visible_messages:
            sender = member_map.get(fwd_msg.sender_uid)
            sender_name = (
                sender.get_display_name()
                if sender
                else fwd_msg.sender_nickname
                or str(fwd_msg.sender_num)
                or fwd_msg.sender_uid
            )
            content = self._render_message_content(
                fwd_msg.elements,
                member_map,
                depth + 1,
            )
            if not content:
                content = self._render_quote_preview(fwd_msg.elements)
            if not content:
                content = '<span class="placeholder-card">[消息]</span>'
            timestamp = datetime.fromtimestamp(fwd_msg.timestamp).strftime(
                '%Y-%m-%d %H:%M:%S'
            )

            items.append(f'''
<div class="forward-item">
    <div class="forward-meta">
        <span class="forward-sender">{html.escape(sender_name)}</span>
        <time title="{html.escape(timestamp, quote=True)}">{timestamp[11:16]}</time>
    </div>
    <div class="forward-content">{content}</div>
</div>
            ''')

        more_html = ''
        if len(forward_messages) > len(visible_messages):
            more_html = (
                f'<div class="forward-more">还有 '
                f'{len(forward_messages) - len(visible_messages)} 条...</div>'
            )

        return f'''
<div class="forward-container">
    <button type="button" class="forward-header" data-forward-toggle aria-expanded="false">
        <span>聊天记录 ({len(forward_messages)} 条)</span>
        <small>点击查看</small>
    </button>
    <div class="forward-body" hidden>
        {''.join(items)}
        {more_html}
    </div>
</div>
        '''

    def _extract_text_content(self, elements: list) -> str:
        """提取消息的纯文本内容（用于引用预览）"""
        parts = []
        for elem in elements:
            if elem.content.get('recovered_message_body'):
                continue
            # 跳过 QUOTE 类型（避免递归引用）
            if elem.type == ElementType.QUOTE:
                continue

            if elem.type == ElementType.TEXT:
                parts.append(elem.content.get('text', ''))
            elif elem.type == ElementType.IMAGE:
                parts.append('[图片]')
            elif elem.type in (ElementType.FILE, ElementType.ONLINE_FILE):
                filename = elem.content.get('filename') or ''
                parts.append(f'[文件] {filename}')
            elif elem.type == ElementType.ONLINE_FOLDER:
                filename = elem.content.get('filename') or ''
                parts.append(f'[文件夹] {filename}')
            elif elem.type == ElementType.VOICE:
                parts.append(elem.content.get('text') or '[语音]')
            elif elem.type == ElementType.VIDEO:
                filename = elem.content.get('filename') or ''
                parts.append(f'[视频] {filename}')
            elif elem.type in (ElementType.EMOJI, ElementType.MARKET_FACE, ElementType.BUBBLE_FACE):
                text = elem.content.get('text') or elem.content.get('summary') or '[表情]'
                parts.append(text)
            elif elem.type in (ElementType.MARKDOWN, ElementType.BOT):
                parts.append(elem.content.get('summary') or elem.content.get('text') or '[消息]')
            elif elem.type in (ElementType.APPLICATION, ElementType.MULTI_MSG):
                forward_messages = elem.content.get('forward_messages', [])
                if forward_messages:
                    previews = [
                        self._extract_text_content(message.elements)
                        for message in forward_messages[:10]
                    ]
                    parts.append('[转发消息] ' + ' '.join(previews))
                else:
                    parts.append('[应用消息]')
            elif elem.type == ElementType.RED_PACKET:
                parts.append(elem.content.get('prompt') or '[红包/转账]')
            elif elem.type == ElementType.CALL:
                parts.append(elem.content.get('text') or '[通话]')
            elif elem.type == ElementType.LOCATION:
                parts.append(elem.content.get('text') or '[位置]')
            elif elem.type == ElementType.FEED:
                parts.extend(filter(None, (
                    elem.content.get('title'),
                    elem.content.get('content'),
                    elem.content.get('subtitle'),
                )))
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

    def _render_quote_preview(self, elements: list) -> str:
        """渲染引用框预览，优先展示 40900 补全出的真实媒体。"""
        for element in elements:
            if element.type == ElementType.QUOTE:
                continue
            if element.type == ElementType.IMAGE:
                image_source = self._resolve_image_source(element.content)
                if image_source:
                    source = html.escape(image_source, quote=True)
                    return (
                        '<div class="quote-media">'
                        f'<img src="{source}" class="message-image" '
                        'alt="引用图片" loading="lazy"></div>'
                    )
                return '<span class="quote-media-label">[图片]</span>'
            if element.type == ElementType.VIDEO:
                return '<span class="quote-media-label">[视频]</span>'
            if element.type == ElementType.VOICE:
                return '<span class="quote-media-label">[语音]</span>'
            if element.type in (ElementType.FILE, ElementType.ONLINE_FILE):
                filename = html.escape(element.content.get('filename') or '')
                return f'<span class="quote-media-label">[文件] {filename}</span>'
            if element.type == ElementType.MARKET_FACE:
                label = html.escape(element.content.get('text') or '[商城表情]')
                return f'<span class="quote-media-label">{label}</span>'

        preview = self._extract_text_content(elements) if elements else ''
        preview = preview[:50] + ('...' if len(preview) > 50 else '')
        return html.escape(preview or '引用了一条消息')

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
            content-visibility: auto;
            contain-intrinsic-size: 1px 900px;
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
            cursor: default;
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

        .quote-media .image-button {{
            width: fit-content;
            margin: 2px 0 0;
        }}

        .quote-media .message-image {{
            max-width: 150px;
            max-height: 96px;
            border-radius: 6px;
        }}

        .quote-media-label {{
            color: var(--text-secondary);
            font-size: 12px;
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
            display: flex;
            width: 100%;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 0;
            border: 0;
            background: none;
            color: inherit;
            font: inherit;
            font-weight: 600;
            cursor: pointer;
        }}

        .forward-header small {{
            color: var(--accent);
            font-size: 11px;
            font-weight: 500;
        }}

        .forward-header span::before {{
            content: '▸';
            display: inline-block;
            margin-right: 5px;
            transition: transform .15s ease;
        }}

        .forward-header[aria-expanded="true"] span::before {{
            transform: rotate(90deg);
        }}

        .forward-body {{
            margin-top: 8px;
        }}

        .forward-meta {{
            display: flex;
            align-items: baseline;
            gap: 7px;
        }}

        .forward-meta time {{
            color: var(--text-secondary);
            font-size: 11px;
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

        .forward-content {{
            padding: 2px 0 3px 8px;
        }}

        .forward-content .message-image {{
            max-width: 180px;
            max-height: 140px;
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

        /* 现代聊天记录布局：借鉴 QCE 的工具栏与 WebArk 的对话密度 */
        :root {{
            --page-bg: #eef0f2;
            --panel-bg: rgba(255, 255, 255, 0.92);
            --chat-bg: #f3f4f5;
            --control-bg: #f0f1f3;
            --control-hover: #e5e7ea;
            --accent: #1296db;
            --accent-soft: rgba(18, 150, 219, 0.12);
            --bubble-self: #12a0e8;
            --bubble-other: #ffffff;
            --text-primary: #17191c;
            --text-secondary: #7b8088;
            --text-self: #ffffff;
            --text-other: #17191c;
            --border: rgba(20, 25, 32, 0.09);
            --shadow: rgba(24, 31, 40, 0.08);
        }}

        [data-theme="dark"] {{
            --page-bg: #111315;
            --panel-bg: rgba(28, 30, 33, 0.94);
            --chat-bg: #181a1d;
            --control-bg: #292c30;
            --control-hover: #34383d;
            --accent: #42b7f5;
            --accent-soft: rgba(66, 183, 245, 0.15);
            --bubble-self: #168fcf;
            --bubble-other: #292c30;
            --text-primary: #f2f3f5;
            --text-secondary: #a0a5ad;
            --text-self: #ffffff;
            --text-other: #f2f3f5;
            --border: rgba(255, 255, 255, 0.09);
            --shadow: rgba(0, 0, 0, 0.24);
            --system-bg: #292c30;
            --system-text: #a0a5ad;
        }}

        html {{
            scroll-behavior: smooth;
            scroll-padding-top: 84px;
        }}

        body {{
            min-width: 320px;
            background: var(--page-bg);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system,
                BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
        }}

        button, input, select {{
            font: inherit;
        }}

        header.topbar {{
            position: sticky;
            top: 0;
            z-index: 100;
            display: grid;
            grid-template-columns: minmax(180px, 1fr) minmax(420px, 680px);
            align-items: center;
            gap: 24px;
            min-height: 68px;
            padding: 10px 24px;
            border-bottom: 1px solid var(--border);
            background: var(--panel-bg);
            backdrop-filter: blur(18px) saturate(150%);
            text-align: left;
        }}

        .brand {{
            display: flex;
            min-width: 0;
            align-items: center;
            gap: 12px;
        }}

        .brand-copy {{ min-width: 0; }}
        .brand h1 {{
            overflow: hidden;
            margin: 0;
            font-size: 17px;
            font-weight: 650;
            line-height: 1.25;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .brand p {{
            margin: 2px 0 0;
            color: var(--text-secondary);
            font-size: 12px;
        }}

        .toolbar {{
            display: flex;
            min-width: 0;
            align-items: center;
            justify-content: flex-end;
            gap: 8px;
        }}

        .search-box {{
            position: relative;
            display: flex;
            min-width: 210px;
            flex: 1;
            align-items: center;
        }}

        .search-input {{
            width: 100%;
            height: 38px;
            padding: 0 76px 0 34px;
            border: 1px solid transparent;
            border-radius: 10px;
            background: var(--control-bg);
            color: var(--text-primary);
            font-size: 14px;
        }}
        .search-input:focus {{
            border-color: var(--accent);
            background: var(--bg-primary);
            box-shadow: 0 0 0 3px var(--accent-soft);
        }}
        .search-symbol {{
            position: absolute;
            left: 11px;
            color: var(--text-secondary);
            font-size: 15px;
            pointer-events: none;
        }}
        .search-status {{
            position: absolute;
            right: 9px;
            color: var(--text-secondary);
            font-size: 11px;
            font-variant-numeric: tabular-nums;
        }}

        .sender-filter {{
            width: 132px;
            height: 38px;
            padding: 0 30px 0 11px;
            border: 0;
            border-radius: 10px;
            outline: none;
            background: var(--control-bg);
            color: var(--text-primary);
            cursor: pointer;
        }}

        .icon-button {{
            display: inline-grid;
            width: 38px;
            height: 38px;
            flex: 0 0 38px;
            place-items: center;
            border: 0;
            border-radius: 10px;
            background: var(--control-bg);
            color: var(--text-primary);
            cursor: pointer;
            transition: background .15s, transform .15s;
        }}
        .icon-button:hover {{ background: var(--control-hover); }}
        .icon-button:active {{ transform: scale(.94); }}
        #timelineToggle {{ display: none; }}

        .page-shell {{
            display: grid;
            grid-template-columns: 220px minmax(0, 820px);
            justify-content: center;
            gap: 34px;
            padding: 28px 24px 100px;
        }}

        .timeline-sidebar {{
            position: sticky;
            top: 96px;
            left: auto;
            z-index: 10;
            width: auto;
            height: calc(100vh - 120px);
            border: 1px solid var(--border);
            border-radius: 16px;
            background: var(--panel-bg);
            box-shadow: 0 10px 30px var(--shadow);
            overflow: hidden;
        }}
        .timeline-header {{ padding: 16px 16px 10px; border: 0; }}
        .timeline-header h2 {{ font-size: 14px; font-weight: 650; }}
        .timeline-close {{ display: none; }}
        .timeline-content {{ padding: 4px 8px 12px; }}
        .timeline-item {{
            display: flex;
            width: 100%;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin: 2px 0;
            padding: 9px 10px;
            border: 0;
            border-radius: 9px;
            background: transparent;
            text-align: left;
        }}
        .timeline-item .date {{ margin: 0; font-size: 13px; font-weight: 550; }}
        .timeline-item .count {{ font-size: 11px; white-space: nowrap; }}
        .timeline-item.active {{
            background: var(--accent-soft);
            color: var(--accent);
        }}
        .timeline-item.hidden {{ display: none; }}

        main.chat-main {{
            width: 100%;
            max-width: none;
            margin: 0;
            padding: 0;
        }}

        .hero {{
            margin-bottom: 18px;
            padding: 28px 30px;
            border: 1px solid var(--border);
            border-radius: 18px;
            background: var(--panel-bg);
            box-shadow: 0 12px 34px var(--shadow);
        }}
        .hero-kicker {{
            margin-bottom: 7px;
            color: var(--accent);
            font-size: 12px;
            font-weight: 700;
            letter-spacing: .08em;
        }}
        .hero h2 {{
            margin: 0;
            font-size: clamp(28px, 4vw, 44px);
            font-weight: 720;
            letter-spacing: -.035em;
            line-height: 1.12;
        }}
        .stats {{
            display: flex;
            flex-wrap: wrap;
            gap: 22px;
            margin-top: 22px;
        }}
        .stat {{ display: grid; gap: 2px; }}
        .stat strong {{ font-size: 15px; font-weight: 650; }}
        .stat span {{ color: var(--text-secondary); font-size: 11px; }}

        .chat-surface {{
            padding: 20px 22px 48px;
            border: 1px solid var(--border);
            border-radius: 18px;
            background: var(--chat-bg);
            box-shadow: 0 12px 34px var(--shadow);
        }}
        .date-block {{ margin: 0 0 32px; scroll-margin-top: 88px; }}
        .date-block.hidden {{ display: none; }}
        .date-divider {{
            position: sticky;
            top: 78px;
            z-index: 5;
            display: flex;
            width: max-content;
            align-items: center;
            gap: 7px;
            margin: 2px auto 22px;
            padding: 5px 10px;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--panel-bg);
            color: var(--text-secondary);
            box-shadow: 0 4px 12px var(--shadow);
            backdrop-filter: blur(12px);
            font-size: 11px;
        }}
        .date-divider small {{ opacity: .75; }}

        .messages {{ padding: 0; }}
        .message-chunk {{ display: flow-root; }}
        .message-entry.hidden {{ display: none; }}
        .message-entry {{
            content-visibility: auto;
            contain-intrinsic-size: auto 82px;
        }}
        .message-group {{ gap: 10px; margin-bottom: 18px; scroll-margin-top: 120px; }}
        .avatar {{
            width: 38px;
            height: 38px;
            border: 1px solid var(--border);
            background: var(--panel-bg);
            font-size: 13px;
            box-shadow: 0 2px 7px var(--shadow);
        }}
        .message-wrapper {{ max-width: min(72%, 620px); }}
        .meta {{ margin: 0 3px 5px; gap: 7px; }}
        .sender {{ font-size: 12px; font-weight: 550; }}
        .time {{ font-size: 11px; }}
        .bubble {{
            position: relative;
            padding: 10px 13px;
            border: 1px solid var(--border);
            border-radius: 5px 14px 14px 14px;
            background: var(--bubble-other);
            box-shadow: 0 3px 10px var(--shadow);
            font-size: 15px;
            line-height: 1.55;
        }}
        .is-self .bubble {{
            border-color: transparent;
            border-radius: 14px 5px 14px 14px;
        }}
        .bubble::before {{
            content: '';
            position: absolute;
            top: 0;
            left: -6px;
            width: 10px;
            height: 12px;
            background: var(--bubble-other);
            clip-path: polygon(100% 0, 100% 100%, 0 0);
        }}
        .is-self .bubble::before {{
            right: -6px;
            left: auto;
            background: var(--bubble-self);
            clip-path: polygon(0 0, 100% 0, 0 100%);
        }}

        .text + .text {{ margin-top: 5px; }}
        .image-button {{
            display: block;
            max-width: 100%;
            margin: 2px 0;
            padding: 0;
            overflow: hidden;
            border: 0;
            border-radius: 10px;
            background: transparent;
            cursor: zoom-in;
        }}
        .message-image {{
            width: auto;
            max-width: min(100%, 420px);
            max-height: 440px;
            margin: 0;
            border-radius: 10px;
            object-fit: contain;
        }}
        .attachment-card, .media-chip, .wallet-card, .feed-card, .ark-card,
        .placeholder-card {{ margin: 3px 0; }}
        .attachment-card {{
            display: grid;
            min-width: 230px;
            grid-template-columns: 38px minmax(0, 1fr);
            align-items: center;
            gap: 10px;
            padding: 10px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: rgba(127, 127, 127, .08);
        }}
        .attachment-icon {{
            display: grid;
            width: 38px;
            height: 38px;
            place-items: center;
            border-radius: 9px;
            background: var(--accent-soft);
            color: var(--accent);
            font-size: 12px;
            font-weight: 700;
        }}
        .attachment-card > span:last-child {{ display: grid; min-width: 0; }}
        .attachment-card strong {{ font-size: 13px; }}
        .attachment-card small {{
            overflow: hidden;
            color: var(--text-secondary);
            font-size: 11px;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .media-chip {{ display: flex; align-items: center; gap: 8px; }}
        .media-chip span {{
            padding: 2px 6px;
            border-radius: 5px;
            background: var(--accent-soft);
            color: var(--accent);
            font-size: 11px;
            font-weight: 650;
        }}
        .wallet-card {{
            display: grid;
            min-width: 210px;
            gap: 4px;
            padding: 12px;
            border-radius: 10px;
            background: linear-gradient(135deg, #ff9f43, #ff6b35);
            color: #fff;
        }}
        .wallet-card span, .wallet-card small {{ font-size: 12px; opacity: .88; }}
        .wallet-designated {{ background: linear-gradient(135deg, #f59f35, #e85d3f); }}
        .wallet-transfer {{ background: linear-gradient(135deg, #4c9aff, #3375d6); }}
        .ark-card {{
            display: grid;
            min-width: 230px;
            max-width: 360px;
            gap: 6px;
            padding: 12px;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: rgba(127, 127, 127, .07);
            color: inherit;
            text-decoration: none;
        }}
        .ark-card:hover {{ border-color: var(--accent); }}
        .ark-card strong {{ font-size: 14px; line-height: 1.4; }}
        .ark-card span, .ark-card small {{
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 1.45;
            white-space: pre-wrap;
        }}
        .ark-label {{
            color: var(--accent);
            font-size: 11px;
            font-weight: 700;
        }}
        .ark-image {{
            width: 100%;
            max-height: 180px;
            border-radius: 7px;
            object-fit: cover;
        }}
        .ark-announcement {{ border-left: 3px solid var(--accent); }}
        .feed-card, .placeholder-card {{
            padding: 10px 11px;
            border: 1px solid var(--border);
            border-radius: 9px;
            background: rgba(127, 127, 127, .07);
        }}
        .placeholder-card {{ color: var(--text-secondary); font-size: 13px; }}
        .forward-container {{
            min-width: 260px;
            padding: 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: rgba(127, 127, 127, .07);
        }}
        .forward-item {{ color: var(--text-secondary); font-size: 12px; }}
        .quote {{ border-left-color: var(--accent); border-radius: 6px; }}
        .quote-sender {{ color: var(--accent); }}
        .quote {{
            position: relative;
            display: block;
            width: 100%;
            border-top: 0;
            border-right: 0;
            border-bottom: 0;
            color: inherit;
            font: inherit;
            text-align: left;
        }}
        .quote-link {{ cursor: pointer; }}
        .quote-link:focus-visible {{
            outline: 2px solid var(--accent);
            outline-offset: 2px;
        }}
        .quote-jump {{
            position: absolute;
            top: 7px;
            right: 8px;
            color: var(--text-secondary);
            font-size: 11px;
            opacity: .65;
        }}

        .system-message {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 7px;
            margin: 18px 0;
            scroll-margin-top: 120px;
        }}
        .system-message time {{ color: var(--text-secondary); font-size: 10px; }}
        .system-text {{ border: 1px solid var(--border); font-size: 11px; }}

        .search-match .bubble,
        .search-match .system-text {{
            outline: 2px solid var(--accent);
            outline-offset: 2px;
        }}
        .message-highlight .bubble,
        .message-highlight .system-text {{
            animation: none;
            box-shadow: 0 0 0 5px var(--accent-soft), 0 3px 10px var(--shadow);
        }}
        .empty-results {{
            display: none;
            padding: 70px 20px;
            color: var(--text-secondary);
            text-align: center;
        }}
        .empty-results.visible {{ display: block; }}
        .filter-summary {{
            display: none;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin: 0 0 18px;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            background: var(--panel-bg);
            color: var(--text-secondary);
            font-size: 12px;
        }}
        .filter-summary.visible {{ display: flex; }}

        #backToTop {{
            position: fixed;
            right: 22px;
            bottom: 22px;
            z-index: 30;
            opacity: 0;
            pointer-events: none;
            box-shadow: 0 8px 24px var(--shadow);
            transition: opacity .2s, transform .2s;
            transform: translateY(8px);
        }}
        #backToTop.visible {{ opacity: 1; pointer-events: auto; transform: none; }}

        #imageModal {{
            background: rgba(8, 10, 12, .94);
            cursor: zoom-out;
            backdrop-filter: blur(10px);
        }}
        #modalImage {{ max-width: 94%; max-height: 92%; object-fit: contain; }}
        .modal-close {{
            position: absolute;
            top: 18px;
            right: 18px;
            color: #fff;
            background: rgba(255, 255, 255, .14);
        }}

        @media (max-width: 860px) {{
            header.topbar {{
                grid-template-columns: 1fr;
                gap: 8px;
                padding: 9px 12px;
            }}
            .brand p {{ display: none; }}
            #timelineToggle {{ display: inline-grid; }}
            .toolbar {{ justify-content: stretch; }}
            .sender-filter {{ width: 110px; }}
            .page-shell {{ display: block; padding: 16px 12px 80px; }}
            .timeline-sidebar {{
                position: fixed;
                top: 0;
                bottom: 0;
                left: -290px;
                z-index: 200;
                width: 280px;
                height: 100vh;
                border-radius: 0 16px 16px 0;
                transition: left .2s ease;
            }}
            .timeline-sidebar.active {{ left: 0; }}
            .timeline-close {{ display: grid; }}
            .hero {{ padding: 22px; }}
            .chat-surface {{ padding: 18px 12px 40px; }}
            .date-divider {{ top: 118px; }}
        }}

        @media (max-width: 560px) {{
            header.topbar {{ min-height: 0; }}
            .toolbar {{ display: grid; grid-template-columns: 1fr auto auto; }}
            .search-box {{ min-width: 0; grid-column: 1 / -1; }}
            .sender-filter {{ width: 100%; }}
            .hero {{ margin-bottom: 10px; border-radius: 14px; }}
            .hero h2 {{ font-size: 28px; }}
            .stats {{ gap: 14px 20px; }}
            .chat-surface {{ border-radius: 14px; }}
            .message-group {{ gap: 7px; }}
            .avatar {{ width: 34px; height: 34px; }}
            .message-wrapper {{ max-width: 82%; }}
            .bubble {{ font-size: 14px; }}
            .attachment-card, .forward-container {{ min-width: 0; }}
            .date-divider {{ top: 156px; }}
        }}
    </style>
</head>
<body>
    <header class="topbar">
        <div class="brand">
            <button id="timelineToggle" class="icon-button" title="打开日期导航" aria-label="打开日期导航">☰</button>
            <div class="brand-copy">
                <h1>{chat_name}</h1>
                <p><span id="chatTypeLabel">{chat_type}</span> · <span id="topMessageCount">{message_count}</span> 条消息</p>
            </div>
        </div>
        <div class="toolbar">
            <label class="search-box">
                <span class="search-symbol">⌕</span>
                <input type="search" id="searchInput" placeholder="搜索消息或发送者" class="search-input" autocomplete="off">
                <span id="searchStatus" class="search-status">{message_count} 条</span>
            </label>
            <select id="senderFilter" class="sender-filter" title="按发送者筛选">
                <option value="">全部发送者</option>
                {sender_options}
            </select>
            <button id="previousResult" class="icon-button" title="上一条结果" aria-label="上一条结果">↑</button>
            <button id="nextResult" class="icon-button" title="下一条结果" aria-label="下一条结果">↓</button>
            <button id="themeToggle" class="icon-button" title="切换主题" aria-label="切换主题">◐</button>
        </div>
    </header>

    <div class="page-shell">
        <aside class="timeline-sidebar" id="timelineSidebar">
            <div class="timeline-header">
                <h2>日期导航</h2>
                <button class="timeline-close icon-button" onclick="toggleTimeline(false)" aria-label="关闭日期导航">×</button>
            </div>
            <nav class="timeline-content" aria-label="聊天日期">
                {timeline_items}
            </nav>
        </aside>

        <main class="chat-main">
            <section class="hero">
                <div class="hero-kicker">QQNT EXPORT</div>
                <h2>{chat_name}</h2>
                <div class="stats">
                    <div class="stat"><strong id="heroMessageCount">{message_count}</strong><span>消息</span></div>
                    <div class="stat"><strong id="heroMemberCount">{member_count}</strong><span>发送者</span></div>
                    <div class="stat"><strong id="heroDateRange">{date_range}</strong><span>时间范围</span></div>
                    <div class="stat"><strong>{export_time}</strong><span>导出时间</span></div>
                </div>
            </section>
            <section class="chat-surface" aria-label="聊天消息">
                <div id="filterSummary" class="filter-summary">
                    <span id="filterSummaryText"></span>
                </div>
                <div id="emptyResults" class="empty-results">没有找到匹配的消息</div>
                {date_blocks}
            </section>
        </main>
    </div>

    <button id="backToTop" class="icon-button" title="返回顶部" aria-label="返回顶部">↑</button>

    <div id="imageModal" onclick="closeModal()" role="dialog" aria-label="图片预览">
        <button class="modal-close icon-button" onclick="closeModal()" aria-label="关闭图片预览">×</button>
        <img id="modalImage" src="" alt="图片预览" onclick="event.stopPropagation()">
    </div>

    <script>
        const root = document.documentElement;
        const searchInput = document.getElementById('searchInput');
        const searchStatus = document.getElementById('searchStatus');
        const senderFilter = document.getElementById('senderFilter');
        const timelineSidebar = document.getElementById('timelineSidebar');
        const chatSurface = document.querySelector('.chat-surface');
        const filterSummary = document.getElementById('filterSummary');
        const filterSummaryText = document.getElementById('filterSummaryText');
        const emptyResults = document.getElementById('emptyResults');
        const exportMeta = window.__QQNT_EXPORT_META__;
        if (exportMeta) {{
            document.getElementById('topMessageCount').textContent = exportMeta.messageCount;
            document.getElementById('heroMessageCount').textContent = exportMeta.messageCount;
            document.getElementById('heroMemberCount').textContent = exportMeta.memberCount;
            document.getElementById('heroDateRange').textContent = exportMeta.dateRange;
            searchStatus.textContent = exportMeta.messageCount + ' 条';

            for (const sender of exportMeta.senders) {{
                const option = document.createElement('option');
                option.value = sender.uid;
                option.textContent = sender.name;
                senderFilter.appendChild(option);
            }}

            const timeline = document.querySelector('.timeline-content');
            for (const [date, count] of Object.entries(exportMeta.dateCounts)) {{
                const dateId = date.replaceAll(' ', '-').replaceAll('/', '-');
                const item = document.createElement('button');
                item.className = 'timeline-item';
                item.dataset.date = dateId;
                const dateLabel = document.createElement('div');
                dateLabel.className = 'date';
                dateLabel.textContent = date;
                const countLabel = document.createElement('div');
                countLabel.className = 'count';
                countLabel.textContent = count + ' 条消息';
                item.append(dateLabel, countLabel);
                item.addEventListener('click', () => scrollToDate(dateId));
                timeline.appendChild(item);
                const dividerCount = document.querySelector(
                    '[data-date-count="' + dateId + '"]'
                );
                if (dividerCount) dividerCount.textContent = count + ' 条';
            }}
        }}
        const dateBlocks = Array.from(document.querySelectorAll('.date-block'));
        const dateBlockMap = new Map(dateBlocks.map(block => [block.dataset.date, block]));
        const messageRecords = [];
        const messageReferenceMap = new Map();
        const virtualChunks = [];
        const virtualChunkMap = new WeakMap();
        const firstRecordByDate = new Map();
        const virtualChunkSize = 200;
        for (const block of dateBlocks) {{
            const container = block.querySelector('.messages');
            const entries = Array.from(container.querySelectorAll(':scope > .message-entry'));
            for (let offset = 0; offset < entries.length; offset += virtualChunkSize) {{
                const chunkEntries = entries.slice(offset, offset + virtualChunkSize);
                const chunkElement = document.createElement('div');
                chunkElement.className = 'message-chunk';
                container.insertBefore(chunkElement, chunkEntries[0]);
                const records = chunkEntries.map(element => {{
                    const record = {{
                        id: element.id,
                        messageId: element.id.slice(4),
                        seq: element.dataset.messageSeq,
                        html: element.outerHTML,
                        search: element.dataset.search,
                        sender: element.dataset.sender,
                        date: block.dataset.date,
                        chunk: null
                    }};
                    chunkElement.appendChild(element);
                    messageRecords.push(record);
                    messageReferenceMap.set(record.messageId, record);
                    if (record.seq && !messageReferenceMap.has(record.seq)) {{
                        messageReferenceMap.set(record.seq, record);
                    }}
                    if (!firstRecordByDate.has(record.date)) {{
                        firstRecordByDate.set(record.date, record);
                    }}
                    return record;
                }});
                const chunk = {{
                    element: chunkElement,
                    height: Math.max(chunkElement.offsetHeight, 1),
                    loaded: true,
                    records
                }};
                records.forEach(record => {{ record.chunk = chunk; }});
                virtualChunks.push(chunk);
                virtualChunkMap.set(chunkElement, chunk);
            }}
        }}
        const originalContent = document.createDocumentFragment();
        let matches = messageRecords.slice();
        let renderedMatches = [];
        let filterActive = false;
        let currentMatch = -1;
        let searchGeneration = 0;
        let searchInProgress = false;
        let searchTimer;
        let timelineJumpGeneration = 0;

        function setTheme(theme) {{
            root.setAttribute('data-theme', theme);
            localStorage.setItem('qqnt-export-theme', theme);
            document.getElementById('themeToggle').textContent = theme === 'dark' ? '◑' : '◐';
        }}

        const savedTheme = localStorage.getItem('qqnt-export-theme');
        setTheme(savedTheme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
        document.getElementById('themeToggle').onclick = () => {{
            setTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
        }};

        function toggleTimeline(force) {{
            const active = typeof force === 'boolean'
                ? force : !timelineSidebar.classList.contains('active');
            timelineSidebar.classList.toggle('active', active);
        }}
        document.getElementById('timelineToggle').onclick = () => toggleTimeline();

        function updateTimelineDates(visibleDates) {{
            document.querySelectorAll('.timeline-item').forEach(item => {{
                item.classList.toggle(
                    'hidden', Boolean(visibleDates) && !visibleDates.has(item.dataset.date)
                );
            }});
        }}

        function removeFilteredBlocks() {{
            document.querySelectorAll('.filtered-date-block').forEach(block => block.remove());
        }}

        function loadVirtualChunk(chunk) {{
            if (chunk.loaded) return;
            chunk.element.classList.remove('is-virtualized');
            chunk.element.style.minHeight = '';
            chunk.element.innerHTML = chunk.records
                .map(record => record.html).join('');
            chunk.loaded = true;
        }}

        function unloadVirtualChunk(chunk) {{
            if (!chunk.loaded || filterActive) return;
            chunk.height = Math.max(chunk.element.offsetHeight, chunk.height, 1);
            chunk.element.replaceChildren();
            chunk.element.style.minHeight = chunk.height + 'px';
            chunk.element.classList.add('is-virtualized');
            chunk.loaded = false;
        }}

        function enterFilteredMode() {{
            if (filterActive) return;
            dateObserver.disconnect();
            virtualObserver.disconnect();
            dateBlocks.forEach(block => originalContent.appendChild(block));
            filterActive = true;
        }}

        function leaveFilteredMode() {{
            if (!filterActive) return;
            dateObserver.disconnect();
            removeFilteredBlocks();
            chatSurface.appendChild(originalContent);
            filterActive = false;
            currentMatch = -1;
            renderedMatches = [];
            filterSummary.classList.remove('visible');
            emptyResults.classList.remove('visible');
            updateTimelineDates(null);
            dateBlocks.forEach(block => dateObserver.observe(block));
            virtualChunks.forEach(chunk => virtualObserver.observe(chunk.element));
        }}

        function renderResults(generation) {{
            enterFilteredMode();
            dateObserver.disconnect();
            removeFilteredBlocks();
            emptyResults.classList.toggle('visible', matches.length === 0);
            filterSummary.classList.toggle('visible', matches.length > 0);
            filterSummaryText.textContent = matches.length
                ? '找到 ' + matches.length + ' 条消息' : '';
            updateTimelineDates(new Set(matches.map(record => record.date)));

            if (!matches.length) {{
                renderedMatches = [];
                searchInProgress = false;
                searchStatus.textContent = '0 条';
                return;
            }}

            searchStatus.textContent = '渲染中…';
            const fragment = document.createDocumentFragment();
            const containers = new Map();
            let cursor = 0;
            const renderChunkSize = 500;

            function renderChunk() {{
                if (generation !== searchGeneration) return;
                const end = Math.min(cursor + renderChunkSize, matches.length);
                for (; cursor < end; cursor++) {{
                    const record = matches[cursor];
                    let container = containers.get(record.date);
                    if (!container) {{
                        const source = dateBlockMap.get(record.date);
                        const section = source.cloneNode(false);
                        section.classList.add('filtered-date-block');
                        section.appendChild(
                            source.querySelector('.date-divider').cloneNode(true)
                        );
                        container = document.createElement('div');
                        container.className = 'messages';
                        section.appendChild(container);
                        fragment.appendChild(section);
                        containers.set(record.date, container);
                    }}
                    container.insertAdjacentHTML('beforeend', record.html);
                }}

                if (cursor < matches.length) {{
                    searchStatus.textContent = '渲染中 '
                        + Math.round(cursor / matches.length * 100) + '%';
                    setTimeout(renderChunk, 0);
                    return;
                }}

                chatSurface.appendChild(fragment);
                renderedMatches = Array.from(
                    chatSurface.querySelectorAll('.filtered-date-block .message-entry')
                );
                document.querySelectorAll('.filtered-date-block').forEach(
                    block => dateObserver.observe(block)
                );
                searchInProgress = false;
                searchStatus.textContent = matches.length + ' 条';
            }}

            renderChunk();
        }}

        function applyFilters() {{
            const query = searchInput.value.toLowerCase().trim();
            const sender = senderFilter.value;
            const generation = ++searchGeneration;
            currentMatch = -1;

            if (!query && !sender) {{
                searchInProgress = false;
                leaveFilteredMode();
                matches = messageRecords.slice();
                searchStatus.textContent = messageRecords.length + ' 条';
                return;
            }}

            searchInProgress = true;
            searchStatus.textContent = '搜索中…';
            const found = [];
            let cursor = 0;
            const chunkSize = 8000;

            function scanChunk() {{
                if (generation !== searchGeneration) return;
                const end = Math.min(cursor + chunkSize, messageRecords.length);
                for (; cursor < end; cursor++) {{
                    const record = messageRecords[cursor];
                    if (
                        (!query || record.search.includes(query))
                        && (!sender || record.sender === sender)
                    ) found.push(record);
                }}

                if (cursor < messageRecords.length) {{
                    searchStatus.textContent = '搜索中 '
                        + Math.round(cursor / messageRecords.length * 100) + '%';
                    setTimeout(scanChunk, 0);
                    return;
                }}

                matches = found;
                renderResults(generation);
            }}

            scanChunk();
        }}

        function moveToResult(step) {{
            if (searchInProgress || !filterActive || !matches.length) return;
            if (currentMatch < 0) {{
                currentMatch = step > 0 ? 0 : matches.length - 1;
            }} else {{
                currentMatch = (currentMatch + step + matches.length) % matches.length;
            }}
            renderedMatches.forEach(element => element.classList.remove('search-match'));
            const target = renderedMatches[currentMatch];
            target.classList.add('search-match');
            target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            searchStatus.textContent = (currentMatch + 1) + ' / ' + matches.length;
        }}

        searchInput.addEventListener('input', () => {{
            searchGeneration++;
            searchInProgress = false;
            clearTimeout(searchTimer);
            searchStatus.textContent = '…';
            searchTimer = setTimeout(applyFilters, 500);
        }});
        senderFilter.addEventListener('change', applyFilters);
        document.getElementById('previousResult').onclick = () => moveToResult(-1);
        document.getElementById('nextResult').onclick = () => moveToResult(1);

        function showImage(src) {{
            const modal = document.getElementById('imageModal');
            document.getElementById('modalImage').src = src;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }}
        function closeModal() {{
            const modal = document.getElementById('imageModal');
            modal.style.display = 'none';
            document.getElementById('modalImage').src = '';
            document.body.style.overflow = '';
        }}

        function scrollToMessage(msgId) {{
            const record = messageReferenceMap.get(String(msgId));
            const elementId = record ? record.id : 'msg-' + msgId;
            let target = document.getElementById(elementId);
            if (!target && filterActive && record) {{
                searchInput.value = '';
                senderFilter.value = '';
                leaveFilteredMode();
            }}
            if (!target && record) {{
                loadVirtualChunk(record.chunk);
                target = document.getElementById(elementId);
            }}
            if (!target) return;
            target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            target.classList.add('message-highlight');
            setTimeout(() => target.classList.remove('message-highlight'), 1800);
        }}

        document.addEventListener('click', event => {{
            const forwardToggle = event.target.closest(
                '.forward-header[data-forward-toggle]'
            );
            if (forwardToggle) {{
                event.preventDefault();
                const body = forwardToggle.nextElementSibling;
                const expanded = forwardToggle.getAttribute('aria-expanded') === 'true';
                forwardToggle.setAttribute('aria-expanded', String(!expanded));
                forwardToggle.querySelector('small').textContent = expanded ? '点击查看' : '收起';
                body.hidden = expanded;
                return;
            }}
            const quote = event.target.closest(
                '.quote-link[data-target-message-id]'
            );
            if (!quote) return;
            event.preventDefault();
            scrollToMessage(quote.dataset.targetMessageId);
        }});

        function alignDateTarget(target) {{
            const topbar = document.querySelector('.topbar');
            const offset = (topbar ? topbar.offsetHeight : 0) + 12;
            const top = target.getBoundingClientRect().top + scrollY - offset;
            scrollTo({{ top, behavior: 'auto' }});
        }}

        function scrollToDate(dateId) {{
            const target = document.getElementById('date-' + dateId);
            if (!target) return;
            const jumpGeneration = ++timelineJumpGeneration;
            if (!filterActive) {{
                virtualObserver.disconnect();
                const firstRecord = firstRecordByDate.get(dateId);
                if (firstRecord) loadVirtualChunk(firstRecord.chunk);
            }}
            alignDateTarget(target);
            requestAnimationFrame(() => {{
                if (jumpGeneration !== timelineJumpGeneration) return;
                alignDateTarget(target);
                if (!filterActive) {{
                    virtualChunks.forEach(chunk => virtualObserver.observe(chunk.element));
                }}
                requestAnimationFrame(() => {{
                    if (jumpGeneration === timelineJumpGeneration) alignDateTarget(target);
                }});
                setTimeout(() => {{
                    if (jumpGeneration === timelineJumpGeneration) alignDateTarget(target);
                }}, 120);
            }});
            if (matchMedia('(max-width: 860px)').matches) toggleTimeline(false);
        }}

        const dateObserver = new IntersectionObserver(entries => {{
            const visible = entries
                .filter(entry => entry.isIntersecting)
                .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
            if (!visible) return;
            document.querySelectorAll('.timeline-item').forEach(item => {{
                item.classList.toggle('active', item.dataset.date === visible.target.dataset.date);
            }});
        }}, {{ rootMargin: '-80px 0px -65% 0px', threshold: [0, .1, .5] }});
        dateBlocks.forEach(block => dateObserver.observe(block));

        const virtualObserver = new IntersectionObserver(entries => {{
            for (const entry of entries) {{
                const chunk = virtualChunkMap.get(entry.target);
                if (!chunk) continue;
                if (entry.isIntersecting) loadVirtualChunk(chunk);
                else unloadVirtualChunk(chunk);
            }}
        }}, {{ rootMargin: '1200px 0px 1200px 0px' }});
        virtualChunks.forEach(chunk => virtualObserver.observe(chunk.element));

        const backToTop = document.getElementById('backToTop');
        addEventListener('scroll', () => {{
            backToTop.classList.toggle('visible', scrollY > 700);
        }}, {{ passive: true }});
        backToTop.onclick = () => scrollTo({{ top: 0, behavior: 'smooth' }});

        document.addEventListener('keydown', event => {{
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {{
                event.preventDefault();
                searchInput.focus();
                searchInput.select();
            }} else if (event.key === '/' && document.activeElement !== searchInput) {{
                event.preventDefault();
                searchInput.focus();
            }} else if (event.key === 'Enter' && document.activeElement === searchInput) {{
                event.preventDefault();
                moveToResult(event.shiftKey ? -1 : 1);
            }} else if (event.key === 'Escape') {{
                closeModal();
                toggleTimeline(false);
                searchInput.blur();
            }}
        }});
    </script>
</body>
</html>
'''
