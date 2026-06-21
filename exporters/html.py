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

        # 构建成员映射
        member_map = {m.platform_id: m for m in members}

        # 获取所有者 ID（判断"我"）
        owner_id = meta.get('ownerId', '')

        # 构建头像映射（从数据库查询）
        avatar_map = self._build_avatar_map(members)

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

        # 渲染日期块
        date_blocks_html = []
        for date_str, msgs in messages_by_date:
            msgs_html = []
            for msg in msgs:
                msgs_html.append(self._render_message(msg, member_map, owner_id, avatar_map))

            date_blocks_html.append(f'''
<details class="date-block" open>
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
            date_blocks=''.join(date_blocks_html)
        )

    def _render_message(
        self,
        msg: ParsedMessage,
        member_map: dict[str, ParsedMember],
        owner_id: str,
        avatar_map: dict[str, str]
    ) -> str:
        """渲染单条消息"""
        is_self = (msg.sender_uid == owner_id)

        # 获取发送者信息
        sender_member = member_map.get(msg.sender_uid)
        sender_name = sender_member.get_display_name() if sender_member else msg.sender_uid

        # 检查是否为系统消息
        if msg.elements and msg.elements[0].type == ElementType.NOTICE:
            notice_text = self._format_notice_text(msg.elements[0].content, member_map)
            return f'<div class="system-message"><span class="system-text">{html.escape(notice_text)}</span></div>'

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

        # 引用消息（TODO: 需要找到被引用的消息内容）
        quoted_html = ''
        if msg.quoted_msg_id:
            quoted_html = f'''
<div class="quote">
    <div class="quote-content">回复了一条消息</div>
</div>
            '''

        return f'''
<div class="message-group {'is-self' if is_self else 'is-other'}">
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
            if elem.type == ElementType.TEXT:
                text = html.escape(elem.content.get('text', ''))
                # 简单换行处理
                text = text.replace('\n', '<br>')
                parts.append(f'<div class="text">{text}</div>')

            elif elem.type == ElementType.IMAGE:
                img_html = self._render_image(elem.content)
                if img_html:
                    parts.append(img_html)

            elif elem.type == ElementType.FILE:
                filename = html.escape(elem.content.get('filename', ''))
                parts.append(f'<div class="text">[文件: {filename}]</div>')

            elif elem.type == ElementType.VOICE:
                duration = elem.content.get('duration', 0)
                parts.append(f'<div class="text">[语音 {duration}秒]</div>')

            elif elem.type == ElementType.VIDEO:
                filename = html.escape(elem.content.get('filename', ''))
                parts.append(f'<div class="text">[视频: {filename}]</div>')

            elif elem.type == ElementType.APPLICATION:
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
                parts.append(f'<div class="text">[红包: {prompt}]</div>')

            else:
                # 其他类型暂时用占位符
                parts.append(f'<div class="text">[{elem.type.name}]</div>')

        return ''.join(parts) if parts else '<div class="text">[空消息]</div>'

    def _render_image(self, content: dict) -> str:
        """渲染图片"""
        md5 = content.get('md5')
        if not md5:
            return '<div class="text">[图片]</div>'

        # 查找已落地的图片（在 resources/images/ 目录）
        resources_dir = self.output_path.parent / 'resources' / 'images'
        if not resources_dir.exists():
            return '<div class="text">[图片]</div>'

        # 尝试找到对应的图片文件
        for img_file in resources_dir.iterdir():
            if img_file.stem == md5:
                # 相对路径（相对于 HTML 文件）
                rel_path = f"resources/images/{img_file.name}"
                return f'<img src="{rel_path}" class="message-image" onclick="showImage(\'{rel_path}\')" alt="图片">'

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

    def _format_notice_text(self, content: dict, member_map: dict[str, ParsedMember]) -> str:
        """格式化系统提示文本"""
        notice_type = content.get('notice_type', 'generic')

        if notice_type == 'withdraw':
            recaller_uid = content.get('recaller_uid', '')
            recaller = member_map.get(recaller_uid)
            recaller_name = recaller.get_display_name() if recaller else recaller_uid
            return f"{recaller_name} 撤回了一条消息"

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
        }}

        .is-self .quote {{
            background: rgba(255, 255, 255, 0.2);
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
        </div>
    </header>

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
