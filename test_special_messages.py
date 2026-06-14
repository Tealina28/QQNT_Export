"""
测试特殊消息类型的 ChatLab 格式输出
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parser.models import ParsedMessage, ParsedMember, ParsedElement, ElementType
from exporters import ChatLabJSONExporter


def test_image_message():
    """测试图片消息 content 的处理"""
    print("测试图片消息...")

    # 测试 1: 有描述文本
    msg1 = ParsedMessage(
        msg_id="1",
        sender_uid="uid_123",
        sender_num=123456,
        timestamp=1700000000,
        elements=[
            ParsedElement(
                type=ElementType.IMAGE,
                content={'text': '风景照', 'filename': 'img.jpg', 'size': 102400}
            )
        ]
    )

    # 测试 2: 无描述文本
    msg2 = ParsedMessage(
        msg_id="2",
        sender_uid="uid_123",
        sender_num=123456,
        timestamp=1700000010,
        elements=[
            ParsedElement(
                type=ElementType.IMAGE,
                content={'filename': 'img2.jpg', 'size': 204800}
            )
        ]
    )

    members = [ParsedMember(platform_id="uid_123", qq_num=123456, nickname="张三")]
    meta = {'name': '测试', 'platform': 'qq', 'type': 'private'}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_path = Path(f.name)

    try:
        exporter = ChatLabJSONExporter(output_path, {})
        exporter.export(meta, members, [msg1, msg2])

        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 验证
        assert data['messages'][0]['content'] == '[图片: 风景照]', "有描述文本应显示"
        assert data['messages'][1]['content'] is None, "无描述文本应为 null"

        print(f"  ✓ 图片消息 - 有描述: {data['messages'][0]['content']}")
        print(f"  ✓ 图片消息 - 无描述: {data['messages'][1]['content']}")

    finally:
        output_path.unlink()


def test_quote_message():
    """测试引用消息的处理"""
    print("\n测试引用消息...")

    # 原始消息
    original_msg = ParsedMessage(
        msg_id="1",
        sender_uid="uid_123",
        sender_num=123456,
        timestamp=1700000000,
        elements=[
            ParsedElement(
                type=ElementType.TEXT,
                content={'text': '大家好！'}
            )
        ]
    )

    # 引用回复（包含引用元素 + 文本元素）
    reply_msg = ParsedMessage(
        msg_id="2",
        sender_uid="uid_456",
        sender_num=456789,
        timestamp=1700000010,
        quoted_msg_id="1",
        elements=[
            ParsedElement(
                type=ElementType.QUOTE,
                content={
                    'sender_uid': 'uid_123',
                    'quoted_content': {'text': '大家好！'}
                }
            ),
            ParsedElement(
                type=ElementType.TEXT,
                content={'text': '收到！'}
            )
        ]
    )

    members = [
        ParsedMember(platform_id="uid_123", qq_num=123456, nickname="张三"),
        ParsedMember(platform_id="uid_456", qq_num=456789, nickname="李四")
    ]
    meta = {'name': '测试', 'platform': 'qq', 'type': 'group'}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_path = Path(f.name)

    try:
        exporter = ChatLabJSONExporter(output_path, {})
        exporter.export(meta, members, [original_msg, reply_msg])

        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 验证
        msg1_data = data['messages'][0]
        msg2_data = data['messages'][1]

        assert msg1_data['content'] == '大家好！', "原始消息内容"
        assert 'replyToMessageId' not in msg1_data, "原始消息无引用"

        assert msg2_data['content'] == '收到！', "引用消息应显示实际回复内容"
        assert msg2_data['replyToMessageId'] == '1', "引用消息应有 replyToMessageId"
        assert msg2_data['type'] == 25, "引用消息类型应为 REPLY (25)"

        print(f"  ✓ 原始消息 content: {msg1_data['content']}")
        print(f"  ✓ 引用消息 content: {msg2_data['content']}")
        print(f"  ✓ 引用消息 replyToMessageId: {msg2_data['replyToMessageId']}")
        print(f"  ✓ 引用消息 type: {msg2_data['type']} (REPLY)")

    finally:
        output_path.unlink()


def test_mixed_elements():
    """测试混合元素消息"""
    print("\n测试混合元素...")

    msg = ParsedMessage(
        msg_id="1",
        sender_uid="uid_123",
        sender_num=123456,
        timestamp=1700000000,
        elements=[
            ParsedElement(
                type=ElementType.TEXT,
                content={'text': '看这个'}
            ),
            ParsedElement(
                type=ElementType.IMAGE,
                content={'filename': 'img.jpg'}  # 无描述文本
            ),
            ParsedElement(
                type=ElementType.TEXT,
                content={'text': '不错吧'}
            )
        ]
    )

    members = [ParsedMember(platform_id="uid_123", qq_num=123456, nickname="张三")]
    meta = {'name': '测试', 'platform': 'qq', 'type': 'private'}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_path = Path(f.name)

    try:
        exporter = ChatLabJSONExporter(output_path, {})
        exporter.export(meta, members, [msg])

        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 验证：图片元素被跳过，只显示文本
        content = data['messages'][0]['content']
        assert content == '看这个\n不错吧', "无描述图片应被跳过"

        print(f"  ✓ 混合消息 content: {repr(content)}")
        print(f"  ✓ 图片元素被正确跳过")

    finally:
        output_path.unlink()


if __name__ == '__main__':
    print("=" * 60)
    print("特殊消息类型 ChatLab 格式测试")
    print("=" * 60)

    try:
        test_image_message()
        test_quote_message()
        test_mixed_elements()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
