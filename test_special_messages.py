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


def test_new_element_semantics():
    """测试新增元素语义：撤回/拍一拍/闪照/动画表情/Ark/引用摘要

    走完整的 protobuf -> ElementParser -> 导出层 路径。
    """
    print("\n测试新增元素语义...")

    import element_pb2
    from parser.elements import ElementParser

    exp = ChatLabJSONExporter.__new__(ChatLabJSONExporter)
    mm = {
        'uidA': ParsedMember(platform_id='uidA', qq_num=111, nickname='小明'),
        'uidB': ParsedMember(platform_id='uidB', qq_num=222, nickname='小红'),
    }

    def content(el):
        return exp._build_content([ElementParser.parse(el)], mm)

    # 撤回
    e = element_pb2.Element(type=8, recallerUid='uidA', recallSuffix='你猜猜')
    assert content(e) == '[小明 撤回了一条消息 你猜猜]', content(e)
    print(f"  ✓ 撤回: {content(e)}")

    # 拍一拍（互动灰字）
    xml = '<gtip><qq uin="uidA"/><nor txt="拍了拍"/><qq uin="uidB"/><nor txt="的脑袋"/></gtip>'
    e = element_pb2.Element(type=8, noticeInfo=xml)
    assert content(e) == '小明 拍了拍 小红的脑袋', content(e)
    print(f"  ✓ 拍一拍: {content(e)}")

    # 闪照
    e = element_pb2.Element(type=2, imageIsFlash=1)
    assert content(e) == '[闪照]', content(e)
    print(f"  ✓ 闪照: {content(e)}")

    # 特殊动画表情 sub_type=7
    e = element_pb2.Element(type=2, subType=7, imageText='嘿嘿')
    assert content(e) == '嘿嘿', content(e)
    print(f"  ✓ 动画表情: {content(e)}")

    # 普通图片无描述 -> None
    e = element_pb2.Element(type=2)
    assert content(e) is None, content(e)
    print(f"  ✓ 普通图片无描述: None")

    # Ark 合并转发
    ark = '{"app":"com.tencent.multimsg","meta":{"detail":{"source":"群聊的聊天记录","summary":"查看3条转发消息"}}}'
    e = element_pb2.Element(type=10, applicationMessage=ark)
    assert content(e) == '[聊天记录] 群聊的聊天记录: 查看3条转发消息', content(e)
    print(f"  ✓ 合并转发: {content(e)}")

    # Ark 音乐分享
    ark = '{"app":"com.tencent.music.lua","view":"music","meta":{"music":{"title":"晴天","desc":"周杰伦"}}}'
    e = element_pb2.Element(type=10, applicationMessage=ark)
    assert content(e) == '[分享] 晴天 - 周杰伦', content(e)
    print(f"  ✓ 音乐分享: {content(e)}")

    # 引用摘要：解析层保留原始 47413 字段（不输出到 chatlab）
    q = element_pb2.Element(type=7, quotedSummary='原消息文本')
    assert ElementParser.parse(q).content['summary'] == '原消息文本'
    print(f"  ✓ 引用摘要原始字段保留: 原消息文本")


if __name__ == '__main__':
    print("=" * 60)
    print("特殊消息类型 ChatLab 格式测试")
    print("=" * 60)

    try:
        test_image_message()
        test_quote_message()
        test_mixed_elements()
        test_new_element_semantics()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
