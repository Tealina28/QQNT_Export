"""
测试脚本 - 验证重构后的架构

测试各个模块的基本功能。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))


def test_parser_models():
    """测试 parser 数据模型"""
    from parser.models import ParsedElement, ParsedMessage, ParsedMember, ElementType

    print("测试 ParsedElement...")
    elem = ParsedElement(
        type=ElementType.TEXT,
        content={'text': '你好'}
    )
    assert elem.type == ElementType.TEXT
    assert elem.content['text'] == '你好'
    print(f"  ✓ {elem}")

    print("测试 ParsedMessage...")
    msg = ParsedMessage(
        msg_id="123",
        sender_uid="uid_456",
        sender_num=789,
        timestamp=1700000000,
        elements=[elem]
    )
    assert not msg.is_group_message()
    print(f"  ✓ ParsedMessage(msg_id={msg.msg_id}, elements={len(msg.elements)})")

    print("测试 ParsedMember...")
    member = ParsedMember(
        platform_id="uid_123",
        qq_num=123456,
        nickname="张三",
        is_admin=True
    )
    assert member.get_display_name() == "张三"
    print(f"  ✓ {member.get_display_name()}")


def test_element_parser():
    """测试 Element 解析器注册机制"""
    from parser.elements import ElementParser
    from parser.models import ElementType

    print("\n测试 ElementParser 注册机制...")

    # 创建一个模拟的 element 对象
    class MockElement:
        def __init__(self, type_id, text=""):
            self.type = type_id
            self.text = text

    # 测试文本解析
    text_elem = MockElement(1, "测试文本")
    parsed = ElementParser.parse(text_elem)
    assert parsed.type == ElementType.TEXT
    assert parsed.content['text'] == "测试文本"
    print(f"  ✓ 文本解析: {parsed.content}")

    # 测试未知类型
    unknown_elem = MockElement(999)
    parsed = ElementParser.parse(unknown_elem)
    assert parsed.type == ElementType.OTHER
    print(f"  ✓ 未知类型处理: {parsed.type.name}")


def test_exporters():
    """测试导出器基本结构"""
    from exporters import EXPORTER_MAP, ChatLabJSONExporter, ChatLabJSONLExporter
    from parser.models import ParsedMessage, ParsedMember, ParsedElement, ElementType

    print("\n测试导出器...")

    # 检查导出器注册
    assert 'chatlab_json' in EXPORTER_MAP
    assert 'chatlab_jsonl' in EXPORTER_MAP
    print("  ✓ 导出器已注册")

    # 检查文件扩展名
    assert ChatLabJSONExporter(Path('/tmp/test'), {}).get_file_extension() == '.json'
    assert ChatLabJSONLExporter(Path('/tmp/test'), {}).get_file_extension() == '.jsonl'
    print("  ✓ 文件扩展名正确")


def test_integration():
    """集成测试：模拟完整流程"""
    from parser.models import ParsedMessage, ParsedMember, ParsedElement, ElementType
    from exporters import ChatLabJSONExporter
    import json
    import tempfile

    print("\n集成测试...")

    # 准备测试数据
    members = [
        ParsedMember(
            platform_id="uid_123",
            qq_num=123456,
            nickname="张三",
            is_owner=True
        ),
        ParsedMember(
            platform_id="uid_456",
            qq_num=456789,
            nickname="李四"
        )
    ]

    messages = [
        ParsedMessage(
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
        ),
        ParsedMessage(
            msg_id="2",
            sender_uid="uid_456",
            sender_num=456789,
            timestamp=1700000010,
            elements=[
                ParsedElement(
                    type=ElementType.TEXT,
                    content={'text': '你好！'}
                )
            ]
        )
    ]

    meta = {
        'name': '测试群',
        'platform': 'qq',
        'type': 'group',
        'groupId': '123456'
    }

    # 导出到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_path = Path(f.name)

    try:
        exporter = ChatLabJSONExporter(output_path, {})
        exporter.export(meta, members, messages)

        # 验证生成的 JSON
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert data['chatlab']['version'] == '0.0.2'
        assert data['meta']['name'] == '测试群'
        assert len(data['members']) == 2
        assert len(data['messages']) == 2
        assert data['messages'][0]['content'] == '大家好！'

        print(f"  ✓ ChatLab JSON 导出成功")
        print(f"  ✓ 验证: {len(data['messages'])} 条消息, {len(data['members'])} 个成员")

    finally:
        output_path.unlink()


if __name__ == '__main__':
    print("=" * 60)
    print("QQNT Export - 架构测试")
    print("=" * 60)

    try:
        test_parser_models()
        test_element_parser()
        test_exporters()
        test_integration()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
