# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QQNT_Export is a Python tool for reading and exporting chat records from **decrypted** QQNT (Tencent QQ NT) databases. It parses SQLite databases containing QQ messages and exports them to standardized formats.

**Current version exports to ChatLab format (v0.0.2)** - a standardized chat data exchange format that supports both JSON and JSONL formats.

## Running the Application

### Installation
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### Usage
Create a `.toml` configuration file based on `example.toml`, then run:
```bash
python main.py path/to/config.toml
```

Configuration format (see `example.toml`):
- `db_path`: Path to decrypted database directory
- `pic_path`: Path to chatpic directory (optional, for image path resolution)
- `output_path`: Export destination (defaults to `{db_path}/../output`)
- `c2c_filters`: List of QQ numbers for private chats to export (empty = all)
- `group_filters`: List of group numbers to export (empty = all)
- `output_format`: Array of formats: `["chatlab_json", "chatlab_jsonl"]`

Output structure: `output/c2c/` for private chats, `output/group/` for group chats.

## Architecture (Refactored)

The project follows a **three-layer decoupled architecture**:

```
Database Layer → Parser Layer → Exporter Layer
      ↓               ↓               ↓
   db/          parser/         exporters/
```

### 1. Database Layer (`db/`)

**Unchanged from original** - handles SQLite database access via SQLAlchemy.

- `man.py`: `DatabaseManager` - manages connections to multiple `.db` files
  - Uses `@DatabaseManager.register_model(db_id)` decorator
  - Provides query methods: `c2c_messages()`, `group_messages()`, `profile_info()`, `group_info()`
- `models.py`: SQLAlchemy ORM models with numeric column names (e.g., `"40001"`)
  - `C2cMessage`, `GroupMessage`: message tables with `message_body` (protobuf)
  - `ProfileInfo`, `GroupList`, `GroupMember`: metadata tables

### 2. Parser Layer (`parser/`) - NEW

**Core innovation**: format-agnostic parsing that converts raw data to Python objects.

#### `parser/models.py`
Defines data models for parsed data:
- `ParsedElement`: A single message element (text, image, file, etc.)
  - `type`: ElementType enum
  - `content`: flexible dict with type-specific fields
- `ParsedMessage`: A complete message with metadata
  - Contains sender info, timestamp, list of elements, quote references
- `ParsedMember`: User/member information
  - Includes roles (owner/admin) for group members

#### `parser/elements.py`
**Registry-based element parser** - highly extensible.

- `ElementParser`: Central registry using decorator pattern
- Each element type (1-26) has a registered parser function
- To add new protobuf fields: just add a new `@ElementParser.register(type_id)` function
- Handles recursive parsing (e.g., quoted messages)
- Special logic:
  - Image cache path calculation (CRC64 algorithm)
  - XML parsing for notice messages
  - Emoji lookup from `emojis.py`

#### `parser/message.py`
Converts database message objects to `ParsedMessage`:
- `MessageParser.parse_c2c_message()`: parse private chat
- `MessageParser.parse_group_message()`: parse group chat
- Member info retrieval with role detection (owner/admin via `manager_flag`)

### 3. Exporter Layer (`exporters/`) - NEW

**Plugin architecture**: each format is an independent exporter class.

#### `exporters/base.py`
- `BaseExporter`: Abstract base class
  - `export(meta, members, messages)`: main export method
  - `get_file_extension()`: returns file extension

#### `exporters/chatlab_json.py`
- `ChatLabJSONExporter`: Exports to ChatLab JSON format
  - Builds complete JSON structure in memory
  - Maps `ElementType` → ChatLab message type codes (0-99)
  - Constructs human-readable content strings from elements
  - Handles optional fields (roles, replyTo, groupNickname)

#### `exporters/chatlab_jsonl.py`
- `ChatLabJSONLExporter`: Exports to ChatLab JSONL format
  - Inherits from `ChatLabJSONExporter` to reuse logic
  - Streams output line-by-line (constant memory usage)
  - Format: `{"_type": "header/member/message", ...}`
  - Ideal for large datasets (>100万 messages)

### Data Flow

1. `main.py` loads config → creates `DatabaseManager`
2. Queries messages → `{uid/group_num: Query}` dict
3. For each conversation:
   - **Parse**: `MessageParser` converts DB messages → `ParsedMessage` list
   - **Gather**: Collect members, build meta dict
   - **Export**: Pass to exporter(s) → write files
4. Each exporter independently transforms `ParsedMessage` → target format

### Key Design Patterns

**Registry Pattern**: `ElementParser` uses decorators to register parsers, avoiding giant if-else chains.

**Plugin Architecture**: New export formats only need to implement `BaseExporter` interface.

**Data Model Decoupling**: `ParsedMessage` is format-agnostic; exporters decide how to serialize.

**Streaming Support**: JSONL exporter writes incrementally for memory efficiency.

## ChatLab Format (v0.0.2)

Standard chat data exchange format with two variants:

**JSON** (`.json`): Complete structure, easy to read, for <100万 messages
```json
{
  "chatlab": {"version": "0.0.2", "exportedAt": 1703001600},
  "meta": {"name": "群名", "platform": "qq", "type": "group"},
  "members": [...],
  "messages": [...]
}
```

**JSONL** (`.jsonl`): One JSON object per line, streaming-friendly, for >100万 messages
```jsonl
{"_type":"header","chatlab":{...},"meta":{...}}
{"_type":"member","platformId":"123","accountName":"张三"}
{"_type":"message","sender":"123","timestamp":1703001600,"type":0,"content":"你好"}
```

Message types: 0=TEXT, 1=IMAGE, 2=VOICE, 3=VIDEO, 4=FILE, 5=EMOJI, 20=RED_PACKET, 23=CALL, 25=REPLY, 80=SYSTEM, 99=OTHER

## Extending the Project

### Adding a new Element type
If you discover a new protobuf element type, add to `parser/elements.py`:

```python
@ElementParser.register(99)  # new type ID
def parse_new_type(element) -> ParsedElement:
    return ParsedElement(
        type=ElementType.OTHER,
        content={'custom_field': element.customField}
    )
```

### Adding a new Export format
Create a new exporter in `exporters/`:

```python
class MyFormatExporter(BaseExporter):
    def export(self, meta, members, messages):
        # Transform ParsedMessage → your format
        pass
    
    def get_file_extension(self) -> str:
        return '.myformat'
```

Then register in `exporters/__init__.py` → `EXPORTER_MAP`.

## Important Notes

- Database decryption is **external** to this project
- Numeric column names reflect QQ's internal schema
- `manager_flag`: 0=member, 1=admin, 2=owner (群主)
- Image cache paths use CRC64 algorithm matching QQ's structure
- Element type 7 (quote) recursively parses referenced content

## Dependencies

- `humanize`: Human-readable file sizes
- `protobuf`: Parse message bodies
- `SQLAlchemy`: ORM for database access
- `lxml`: XML parsing for notice messages

**Development**: Run inside virtual environment (`venv/`)
