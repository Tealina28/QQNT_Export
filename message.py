from ast import literal_eval
from datetime import datetime
from json import loads
from xml.etree.ElementTree import fromstring

import sections_pb2

class Message:

    def __init__(self, time_stamp, raw, sender_num, interlocutor_num, username, remark_name):
        self.readable_time = datetime.fromtimestamp(time_stamp).strftime("%Y-%m-%d %H:%M:%S")
        self.sender_num = sender_num
        self.interlocutor_num = interlocutor_num
        self.username = username
        self.remark_name = remark_name
        # 此处 username 和 remark_name 都指 interlocutor 的
        self.sections = sections_pb2.Sections()
        try:
            self.sections.ParseFromString(raw)
        except:
            pass

        # 动态初始化 functions 字典
        self.functions = {
            1: self.text_content,
            2: self.image_content,
            3: self.file_content,
            # 4: "?",
            6: self.emoji_content,
            7: self.quote_content,
            8: self.notice_content,
            10: self.application_content,
            21: self.call_content,
            26: self.feed_content,
        }

    def parse(self):
        self.types,self.contents,self.outputs = [],[],[]
        for section in self.sections.sections:
            type = section.type
            content, output = self.parse_section(section)

            self.types.append(type)
            if content and output:
                self.contents.append(content)
                self.outputs.append(output)

    def parse_section(self,section):
        if section.type in self.functions:
            try:
                return self.functions[section.type](section)
            except Exception as e:
                print(e)
                return None,None
        else:
            return None,None

    def text_content(self,section):
        content = section.text
        output = f"[文本]{content}"
        return content,output

    def image_content(self,section):
        image_text = section.imageText
        file_name = section.fileName
        file_path = section.imageFilePath
        file_url = section.imageUrlOrigin

        content = f"{image_text}-{file_name}"
        output = f"[图片]{content}\n{file_path}\n{file_url}"
        return content,output

    def file_content(self,section):
        content = section.fileName
        output = f"[文件]{content}"
        return content,output

    def emoji_content(self,section):
        emoji_id = section.emojiId

        content = section.emojiText
        output = f"[QQ/emoji 表情]{emoji_id}-{content}"
        return content,output

    def quote_content(self,section):
        _,content = self.parse_section(section.quotedSection)
        output = f"[被引用的消息]{content}"
        return content,output

    def notice_content(self,section):
        info = section.noticeInfo
        info2 = section.noticeInfo2

        if not info and not info2:
            return None,"[提示消息]"

        if info:
            root = fromstring(info)
            texts = [
                elem.get('txt')
                for elem in root.findall('.//nor')
                if elem.get('txt')
            ]

        if info2:
            info2 = info2.replace(r"\/","/")
            info2_dict = literal_eval(info2)

            texts = [item.get("txt","")
                     for item
                     in info2_dict["items"]]

        # 此为权宜之计，有待后续改进
        content = " ".join(texts)
        output = f"[提示消息]{content}"

        return content,output

    def application_content(self,section):
        raw = section.applicationMessage

        content = loads(raw)["prompt"]
        output = f"[应用消息]{content}"

        return content,output


    def call_content(self,section):
        status = section.callStatus
        text = section.callText

        content = f"{status}-{text}"
        output = f"[通话]{content}"
        return content,output

    def feed_content(self,section):
        title = section.feedTitle.text
        feed_content = section.feedContent.text
        url = section.feedUrl
        # 分 jump_schema （QQ空间内容）和 jumpUrl （更换装扮的广告和礼物提示）
        jump_info = section.feedJumpInfo

        content = f"{title}\n{feed_content}\n{url}"
        output = f"[动态消息]\n{content}"
        return content,output


class C2cMessage(Message):

    def write(self,path):
        direction = "收" if self.sender_num == self.interlocutor_num else "发"

        with path.open(mode='a', encoding='utf-8') as f:
            f.write(f"{self.readable_time} {direction}\n")

            for section in self.outputs:
                f.write(f"{section}\n")

            f.write("\n")


class GroupMessage(Message):
    def __init__(self, time_stamp, raw, sender_num, interlocutor_num, username, remark_name, name_card):
        super().__init__(time_stamp, raw, sender_num, interlocutor_num, username, remark_name)
        self.name_card = name_card
    def write(self,path):
        if not path.exists():
            path.touch()

        with path.open(mode='a', encoding='utf-8') as f:
            f.write(f"{self.readable_time} {self.sender_num}\n")

            for section in self.outputs:
                f.write(f"{section}\n")

            f.write("\n")