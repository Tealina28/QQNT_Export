import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import element_pb2

from exporters.chatlab_json import ChatLabJSONExporter
from parser.dataline import (
    DATALINE_PAD_UID,
    DATALINE_PC_UID,
    DATALINE_PHONE_UID,
    dataline_conversation_name,
    resolve_dataline_owner_id,
)
from parser.elements import (
    ElementParser,
    _parse_forward_cache,
    compute_image_cache_path,
    compute_image_cache_paths,
)
from parser.message import MessageParser
from parser.models import ElementType, ParsedElement, ParsedMessage


def make_c2c_message(elements, **overrides):
    values = {
        'id': 100,
        'seq': 10,
        'sender_uid': 'sender_uid',
        'sender_num': 12345,
        'time': 1700000000,
        'msg_type': 2,
        'UNK_18': None,
        'quoted_seq': 0,
        'elements': element_pb2.Elements(elements=elements),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ImageCachePathTests(unittest.TestCase):
    def test_keeps_existing_preferred_directory_order(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            non_original = compute_image_cache_paths('ab' * 16, 0, root)
            original = compute_image_cache_paths('cd' * 16, 1, root)

            self.assertEqual(
                [path.parent.parent.name for path in non_original],
                ['chatraw', 'chatimg', 'chatthumb'],
            )
            self.assertEqual(
                [path.parent.parent.name for path in original],
                ['chatimg', 'chatraw', 'chatthumb'],
            )

    def test_falls_back_to_existing_alternate_cache(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidates = compute_image_cache_paths('12' * 16, 0, root)
            alternate = candidates[1]
            alternate.parent.mkdir(parents=True)
            alternate.write_bytes(b'image')

            self.assertEqual(
                compute_image_cache_path('12' * 16, 0, root),
                alternate,
            )

    def test_falls_back_to_thumbnail_cache(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thumbnail = compute_image_cache_paths('34' * 16, 1, root)[2]
            thumbnail.parent.mkdir(parents=True)
            thumbnail.write_bytes(b'thumbnail')

            self.assertEqual(
                compute_image_cache_path('34' * 16, 1, root),
                thumbnail,
            )


class DatalineTests(unittest.TestCase):
    def test_conversation_name_uses_peer_device(self):
        self.assertEqual(
            dataline_conversation_name([DATALINE_PC_UID, DATALINE_PHONE_UID]),
            '我的手机',
        )

        self.assertEqual(
            dataline_conversation_name(
                [DATALINE_PC_UID, DATALINE_PHONE_UID],
                DATALINE_PHONE_UID,
            ),
            '我的电脑',
        )

    def test_owner_id_is_resolved_from_device_name(self):
        self.assertEqual(resolve_dataline_owner_id('pad'), DATALINE_PAD_UID)
        self.assertEqual(resolve_dataline_owner_id('phone'), DATALINE_PHONE_UID)
        self.assertEqual(resolve_dataline_owner_id(None), DATALINE_PC_UID)
        with self.assertRaises(ValueError):
            resolve_dataline_owner_id('unknown')

    def test_device_members_use_pc_as_owner_identity(self):
        dbman = SimpleNamespace(
            self_uid_mapping=lambda: SimpleNamespace(qq_num=123456)
        )
        parser = MessageParser(dbman)
        messages = [
            ParsedMessage(
                msg_id='1', seq=1, sender_uid=DATALINE_PHONE_UID,
                sender_num=123456, timestamp=1700000000, elements=[],
            ),
            ParsedMessage(
                msg_id='2', seq=2, sender_uid=DATALINE_PC_UID,
                sender_num=123456, timestamp=1700000001, elements=[],
            ),
        ]

        members = parser.get_dataline_members(messages)

        self.assertEqual(
            [member.platform_id for member in members],
            [DATALINE_PC_UID, DATALINE_PHONE_UID],
        )
        self.assertEqual(
            [member.nickname for member in members],
            ['我的电脑', '我的手机'],
        )
        self.assertTrue(all(member.qq_num == 123456 for member in members))

        phone_owned = parser.get_dataline_members(messages, DATALINE_PHONE_UID)
        self.assertEqual(phone_owned[0].platform_id, DATALINE_PHONE_UID)


class ForwardCacheTests(unittest.TestCase):
    def test_multi_element_and_nested_forward_messages(self):
        nested = element_pb2.ForwardedMessage(
            msgId=202,
            msgSeq=22,
            senderUid='nested_sender',
            senderNum=20002,
            sendTime=1700000002,
            elements=[
                element_pb2.Element(type=1, text='nested text'),
                element_pb2.Element(type=2, fileName='nested.jpg'),
            ],
        )
        outer = element_pb2.ForwardedMessage(
            msgId=201,
            msgSeq=21,
            senderUid='outer_sender',
            senderNum=20001,
            sendTime=1700000001,
            elements=[
                element_pb2.Element(
                    type=16,
                    multiMsgResId='resource-id',
                    xmlContent='<msg brief="[chat history]"/>',
                    multiMsgSessionId='session-id',
                )
            ],
            subMessages=[nested],
        )
        cache = element_pb2.ForwardedMessages(messages=[outer])

        parsed = _parse_forward_cache(cache.SerializeToString())

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].seq, 21)
        self.assertEqual(parsed[0].timestamp, 1700000001)
        self.assertEqual(parsed[0].elements[0].type, ElementType.MULTI_MSG)

        nested_parsed = parsed[0].elements[0].content['forward_messages']
        self.assertEqual(len(nested_parsed), 1)
        self.assertEqual(nested_parsed[0].seq, 22)
        self.assertEqual(len(nested_parsed[0].elements), 2)
        self.assertEqual(nested_parsed[0].elements[0].content['text'], 'nested text')
        self.assertEqual(nested_parsed[0].elements[1].content['filename'], 'nested.jpg')


class QuoteTests(unittest.TestCase):
    def test_quote_keeps_message_id_seq_and_all_original_elements(self):
        quote = element_pb2.Element(
            type=7,
            origSenderUid='quoted_sender',
            origReceiverUid='quoted_receiver',
            origSenderNum=54321,
            origMsgId=9876543210123,
            origMsgSeq=77,
            origMsgTime=1699999999,
            replyTextSummary='quoted summary',
            origElements=[
                element_pb2.Element(type=1, text='quoted text'),
                element_pb2.Element(type=2, fileName='quoted.jpg'),
            ],
        )
        message = make_c2c_message(
            [quote, element_pb2.Element(type=1, text='reply text')],
            msg_type=9,
        )

        parsed = MessageParser(None).parse_c2c_message(message)

        self.assertEqual(parsed.quoted_msg_id, '9876543210123')
        self.assertEqual(parsed.quoted_msg_seq, 77)
        quoted = parsed.elements[0]
        self.assertEqual(quoted.type, ElementType.QUOTE)
        self.assertEqual(len(quoted.content['quoted_elements']), 2)
        self.assertEqual(quoted.content['quoted_elements'][0].content['text'], 'quoted text')

    def test_quote_falls_back_to_40900_cached_message(self):
        cached = element_pb2.ForwardedMessage(
            msgId=555,
            msgSeq=66,
            senderUid='quoted_sender',
            senderNum=54321,
            sendTime=1699999999,
            elements=[element_pb2.Element(type=1, text='cached quote')],
        )
        cache = element_pb2.ForwardedMessages(messages=[cached])
        message = make_c2c_message(
            [element_pb2.Element(type=7, replyTextSummary='summary')],
            msg_type=9,
            UNK_18=cache.SerializeToString(),
        )

        parsed = MessageParser(None).parse_c2c_message(message)

        self.assertEqual(parsed.quoted_msg_id, '555')
        self.assertEqual(parsed.quoted_msg_seq, 66)


class ElementFailureTests(unittest.TestCase):
    def test_bad_element_becomes_other_without_dropping_following_elements(self):
        type_id = 99
        previous = ElementParser._parsers.get(type_id)

        def fail_parser(_element):
            raise ValueError('broken element')

        ElementParser._parsers[type_id] = fail_parser
        try:
            message = make_c2c_message([
                element_pb2.Element(type=type_id, text='bad'),
                element_pb2.Element(type=1, text='still parsed'),
            ])

            with self.assertLogs('parser.elements', level='ERROR'):
                parsed = MessageParser(None).parse_c2c_message(message)

            self.assertEqual(len(parsed.elements), 2)
            self.assertEqual(parsed.elements[0].type, ElementType.OTHER)
            self.assertEqual(parsed.elements[0].content['parse_error'], 'broken element')
            self.assertTrue(parsed.elements[0].content['raw_hex'])
            self.assertEqual(parsed.elements[1].type, ElementType.TEXT)
            self.assertEqual(parsed.elements[1].content['text'], 'still parsed')
        finally:
            if previous is None:
                ElementParser._parsers.pop(type_id, None)
            else:
                ElementParser._parsers[type_id] = previous


class ExportTests(unittest.TestCase):
    def test_chatlab_uses_forward_type_and_snowflake_reply_id(self):
        message = ParsedMessage(
            msg_id='1000',
            seq=10,
            sender_uid='sender_uid',
            sender_num=12345,
            timestamp=1700000000,
            elements=[
                ParsedElement(
                    type=ElementType.MULTI_MSG,
                    content={'forward_messages': []},
                )
            ],
            quoted_msg_id='999',
            quoted_msg_seq=9,
        )

        with TemporaryDirectory() as tmp:
            exporter = ChatLabJSONExporter(Path(tmp) / 'chat.json', {})
            exported = exporter._build_messages([message], {}, Path(tmp))[0]

        self.assertEqual(exported['type'], 26)
        self.assertEqual(exported['replyToMessageId'], '999')


class MessageCapabilityTests(unittest.TestCase):
    def test_extended_element_types_and_fields(self):
        elements = [
            element_pb2.Element(
                type=1,
                text='@Alice',
                bubbleId='mention',
                atMentionMask='1',
            ),
            element_pb2.Element(
                type=6,
                emojiId=358,
                emojiText='骰子',
                subType=3,
                diceValue='6',
            ),
            element_pb2.Element(
                type=8,
                subType=4,
                groupTipType=1,
                groupTipUser1Uid='new_member',
                groupTipUser1Name='Alice',
                noticeInfo='<msg><nor txt="加入了群聊"/></msg>',
            ),
            element_pb2.Element(
                type=9,
                walletTargetNum=10001,
                walletRedbagType=1,
                walletOrderId='order-id',
                walletDetail=element_pb2.WalletDetail(
                    redbagType=1,
                    title='转账',
                    prompt='请收款',
                    display='88.00',
                ),
            ),
            element_pb2.Element(
                type=14,
                markdownText='markdown',
                markdownSummary='闪传文件',
                flashTransferInfo=element_pb2.FlashTransferInfo(
                    fileSetId='set-id',
                    thumbnailName='bundle.zip',
                    fileBytes=1024,
                ),
            ),
            element_pb2.Element(
                type=23,
                fileName='online.txt',
                filePath='/online.txt',
                fileSize=12,
                fileToken='file-token',
            ),
            element_pb2.Element(
                type=30,
                fileName='folder',
                fileToken='folder-token',
            ),
            element_pb2.Element(
                type=26,
                dynamicId='dynamic-id',
                dynamicDescription=element_pb2.DynamicDescription(
                    main='动态标题',
                    sub='动态副标题',
                ),
                dynamicCoverUrl='https://example.invalid/cover.jpg',
                dynamicTags=[element_pb2.DynamicTag(content='标签')],
            ),
            element_pb2.Element(
                type=27,
                bubbleFaceId=123,
                bubbleFaceName='平底锅',
                bubbleFaceSummary='[平底锅]x3',
            ),
            element_pb2.Element(
                type=17,
                markdownButtonAppId=102076836,
                markdownButtonRows=[
                    element_pb2.MarkdownButtonRow(buttons=[
                        element_pb2.MarkdownButton(
                            id='0',
                            label='帮助菜单',
                            action='/帮助',
                            actionType=2,
                        )
                    ])
                ],
            ),
        ]

        parsed = [ElementParser.parse(element) for element in elements]

        self.assertTrue(parsed[0].content['is_at'])
        self.assertEqual(parsed[1].content['dice_value'], '6')
        self.assertEqual(parsed[2].content['notice_type'], 'group')
        self.assertEqual(parsed[2].content['group_event'], 'join')
        self.assertEqual(parsed[3].content['wallet_type'], 'transfer')
        self.assertEqual(parsed[4].content['flash_transfer']['file_set_id'], 'set-id')
        self.assertEqual(parsed[5].type, ElementType.ONLINE_FILE)
        self.assertEqual(parsed[6].type, ElementType.ONLINE_FOLDER)
        self.assertEqual(parsed[7].content['title'], '动态标题')
        self.assertEqual(parsed[8].content['emoji_id'], 123)
        self.assertEqual(parsed[9].type, ElementType.MARKDOWN_BUTTON)
        self.assertEqual(parsed[9].content['rows'][0][0]['label'], '帮助菜单')

    def test_group_reactions_are_parsed(self):
        reaction_blob = element_pb2.EmojiStickers(stickers=[
            element_pb2.EmojiSticker(
                emojiId='14',
                setFlag=1,
                count=3,
                isSelf=True,
            )
        ]).SerializeToString()
        message = make_c2c_message(
            [element_pb2.Element(type=1, text='message')],
            reactions_body=reaction_blob,
        )

        parsed = MessageParser(None).parse_c2c_message(message)

        self.assertEqual(len(parsed.reactions), 1)
        self.assertEqual(parsed.reactions[0].emoji_id, '14')
        self.assertEqual(parsed.reactions[0].count, 3)
        self.assertTrue(parsed.reactions[0].is_self)

    def test_action_gray_tips_are_classified_by_action_semantics(self):
        poke = ElementParser.parse(element_pb2.Element(
            type=8,
            subType=12,
            actionId=12,
            actionDetailId=1061,
            noticeInfo='<msg><nor txt="戳了戳"/></msg>',
        ))
        check_in = ElementParser.parse(element_pb2.Element(
            type=8,
            subType=12,
            actionId=14,
            actionDetailId=1068,
            noticeInfo='<msg><nor txt="今日打卡"/></msg>',
        ))
        wallet = ElementParser.parse(element_pb2.Element(
            type=8,
            subType=12,
            actionId=16,
            actionDetailId=19357,
            noticeInfo='<msg><nor txt="领取了红包"/></msg>',
        ))

        self.assertEqual(poke.content['notice_type'], 'interactive')
        self.assertEqual(check_in.content['notice_type'], 'action')
        self.assertEqual(wallet.content['notice_type'], 'wallet')

    def test_chatlab_extended_type_mapping(self):
        exporter = ChatLabJSONExporter(Path('/tmp/chat.json'), {})

        transfer = ParsedElement(
            ElementType.RED_PACKET,
            {'wallet_type': 'transfer'},
        )
        online_file = ParsedElement(ElementType.ONLINE_FILE, {'filename': 'a.txt'})
        location = ParsedElement(ElementType.LOCATION, {'text': 'somewhere'})
        recall = ParsedElement(ElementType.NOTICE, {'notice_type': 'withdraw'})
        poke = ParsedElement(ElementType.NOTICE, {'notice_type': 'interactive'})

        self.assertEqual(exporter._infer_message_type([transfer]), 21)
        self.assertEqual(exporter._infer_message_type([online_file]), 4)
        self.assertEqual(exporter._infer_message_type([location]), 8)
        self.assertEqual(exporter._infer_message_type([recall]), 81)
        self.assertEqual(exporter._infer_message_type([poke]), 22)


if __name__ == '__main__':
    unittest.main()
