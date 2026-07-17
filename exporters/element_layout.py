"""消息元素在导出展示中的行内与块级布局语义。"""

from collections.abc import Iterable
from typing import Literal, Optional

from parser.models import ElementType, ParsedElement


ElementLayout = Literal['inline', 'block']

INLINE_ELEMENT_TYPES = frozenset({
    ElementType.TEXT,
    ElementType.IMAGE,
    ElementType.EMOJI,
    ElementType.MARKET_FACE,
    ElementType.BUBBLE_FACE,
})


def element_layout(element: ParsedElement) -> Optional[ElementLayout]:
    """返回元素的展示布局；引用和恢复诊断不参与正文。"""
    if (
        element.type == ElementType.QUOTE
        or element.content.get('recovered_message_body')
    ):
        return None
    if element.type in INLINE_ELEMENT_TYPES:
        return 'inline'
    return 'block'


def join_content_fragments(
    fragments: Iterable[tuple[ElementLayout, str]],
) -> str:
    """连续行内片段直接拼接，仅在块级边界插入一个换行。"""
    output: list[str] = []
    previous_layout: Optional[ElementLayout] = None
    for layout, fragment in fragments:
        if not fragment:
            continue
        if (
            output
            and (layout == 'block' or previous_layout == 'block')
            and not output[-1].endswith('\n')
            and not fragment.startswith('\n')
        ):
            output.append('\n')
        output.append(fragment)
        previous_layout = layout
    return ''.join(output)
