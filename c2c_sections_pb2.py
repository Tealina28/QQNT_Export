# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: c2c_sections.proto
# Protobuf Python Version: 6.30.1
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    6,
    30,
    1,
    '',
    'c2c_sections.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x12\x63\x32\x63_sections.proto\"(\n\x08Sections\x12\x1c\n\x08sections\x18\xe0\xbe\x02 \x03(\x0b\x32\x08.Section\"\x85\x06\n\x07Section\x12\x0c\n\x02id\x18\xc9\xdf\x02 \x01(\x04\x12\x0e\n\x04type\x18\xca\xdf\x02 \x01(\r\x12\x13\n\tsenderUid\x18\xd4\xb8\x02 \x01(\t\x12\x19\n\x0finterlocutorUid\x18\xd5\xb8\x02 \x01(\t\x12\x13\n\tsenderNum\x18\xab\xf2\x02 \x01(\r\x12\x19\n\x0fquotedTimestamp\x18\xac\xf2\x02 \x01(\r\x12\x19\n\x0finterlocutorNum\x18\xb3\xf2\x02 \x01(\r\x12!\n\rquotedSection\x18\xbf\xf2\x02 \x01(\x0b\x32\x08.Section\x12\x0e\n\x04text\x18\xad\xe0\x02 \x01(\t\x12\x12\n\x08\x66ileName\x18\xda\xe2\x02 \x01(\t\x12\x12\n\x08\x66ileSize\x18\xdd\xe2\x02 \x01(\x04\x12\x17\n\rfileTimestamp\x18\xc1\xe3\x02 \x01(\x04\x12\x17\n\rimageFileName\x18\xae\xe0\x02 \x01(\t\x12\x15\n\x0bimageUrlLow\x18\xea\xe5\x02 \x01(\t\x12\x16\n\x0cimageUrlHigh\x18\xeb\xe5\x02 \x01(\t\x12\x18\n\x0eimageUrlOrigin\x18\xec\xe5\x02 \x01(\t\x12\x17\n\rimageFilePath\x18\xf4\xe5\x02 \x01(\t\x12\x13\n\timageText\x18\xf7\xe5\x02 \x01(\t\x12\x11\n\x07\x65mojiId\x18\xf1\xf3\x02 \x01(\r\x12\x13\n\temojiText\x18\xf2\xf3\x02 \x01(\t\x12\x1c\n\x12\x61pplicationMessage\x18\x9d\xf6\x02 \x01(\t\x12\x14\n\ncallStatus\x18\x99\xf8\x02 \x01(\t\x12\x12\n\x08\x63\x61llText\x18\x9d\xf8\x02 \x01(\t\x12!\n\tfeedTitle\x18\xaf\xf8\x02 \x01(\x0b\x32\x0c.FeedMessage\x12#\n\x0b\x66\x65\x65\x64\x43ontent\x18\xb0\xf8\x02 \x01(\x0b\x32\x0c.FeedMessage\x12\x11\n\x07\x66\x65\x65\x64Url\x18\xb4\xf8\x02 \x01(\t\x12\x15\n\x0b\x66\x65\x65\x64LogoUrl\x18\xb5\xf8\x02 \x01(\t\x12\x1a\n\x10\x66\x65\x65\x64PublisherNum\x18\xb6\xf8\x02 \x01(\r\x12\x16\n\x0c\x66\x65\x65\x64JumpInfo\x18\xb7\xf8\x02 \x01(\t\x12\x1a\n\x10\x66\x65\x65\x64PublisherUid\x18\xbc\xf8\x02 \x01(\t\x12\x14\n\nnoticeInfo\x18\xd6\xf8\x02 \x01(\t\x12\x15\n\x0bnoticeInfo2\x18\x8f\xf9\x02 \x01(\t\"\x1d\n\x0b\x46\x65\x65\x64Message\x12\x0e\n\x04text\x18\xb2\xf8\x02 \x01(\tb\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'c2c_sections_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  DESCRIPTOR._loaded_options = None
  _globals['_SECTIONS']._serialized_start=22
  _globals['_SECTIONS']._serialized_end=62
  _globals['_SECTION']._serialized_start=65
  _globals['_SECTION']._serialized_end=838
  _globals['_FEEDMESSAGE']._serialized_start=840
  _globals['_FEEDMESSAGE']._serialized_end=869
# @@protoc_insertion_point(module_scope)
