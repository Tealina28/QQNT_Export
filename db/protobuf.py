"""Schema-aware protobuf recovery helpers for partially mismatched QQNT data."""

from __future__ import annotations

from google.protobuf.descriptor import Descriptor, FieldDescriptor


class WireDecodeError(ValueError):
    """The raw protobuf stream is truncated or uses an unsupported wire type."""


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise WireDecodeError('truncated varint')
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return value, offset
    raise WireDecodeError('varint exceeds 10 bytes')


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7f:
        output.append((value & 0x7f) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _expected_wire_type(field: FieldDescriptor) -> int:
    if field.type in (
        FieldDescriptor.TYPE_DOUBLE,
        FieldDescriptor.TYPE_FIXED64,
        FieldDescriptor.TYPE_SFIXED64,
    ):
        return 1
    if field.type in (
        FieldDescriptor.TYPE_STRING,
        FieldDescriptor.TYPE_BYTES,
        FieldDescriptor.TYPE_MESSAGE,
    ):
        return 2
    if field.type in (
        FieldDescriptor.TYPE_FLOAT,
        FieldDescriptor.TYPE_FIXED32,
        FieldDescriptor.TYPE_SFIXED32,
    ):
        return 5
    return 0


def _is_packable(field: FieldDescriptor) -> bool:
    return field.type not in (
        FieldDescriptor.TYPE_STRING,
        FieldDescriptor.TYPE_BYTES,
        FieldDescriptor.TYPE_MESSAGE,
        FieldDescriptor.TYPE_GROUP,
    )


def _wire_type_matches(field: FieldDescriptor, wire_type: int) -> bool:
    expected = _expected_wire_type(field)
    if field.is_repeated and _is_packable(field):
        return wire_type in (expected, 2)
    return wire_type == expected


def _field_bounds(
    data: bytes,
    offset: int,
) -> tuple[int, int, int, int, int]:
    """Return (field_number, wire_type, payload_start, payload_end, field_end)."""
    key, cursor = _read_varint(data, offset)
    field_number = key >> 3
    wire_type = key & 0x07
    if not field_number:
        raise WireDecodeError('field number 0 is invalid')

    if wire_type == 0:
        payload_start = cursor
        _, field_end = _read_varint(data, cursor)
        return field_number, wire_type, payload_start, field_end, field_end
    if wire_type == 1:
        field_end = cursor + 8
        if field_end > len(data):
            raise WireDecodeError(f'truncated fixed64 field {field_number}')
        return field_number, wire_type, cursor, field_end, field_end
    if wire_type == 2:
        length, payload_start = _read_varint(data, cursor)
        field_end = payload_start + length
        if field_end > len(data):
            raise WireDecodeError(f'truncated length-delimited field {field_number}')
        return field_number, wire_type, payload_start, field_end, field_end
    if wire_type == 5:
        field_end = cursor + 4
        if field_end > len(data):
            raise WireDecodeError(f'truncated fixed32 field {field_number}')
        return field_number, wire_type, cursor, field_end, field_end
    raise WireDecodeError(
        f'unsupported wire type {wire_type} at field {field_number}'
    )


def sanitize_protobuf(
    data: bytes,
    descriptor: Descriptor,
    path: tuple[int, ...] = (),
) -> tuple[bytes, list[dict]]:
    """Remove schema-conflicting fields while preserving their raw bytes.

    Unknown tags are retained verbatim. Known nested messages are sanitized
    recursively. The returned metadata records every removed field so callers
    can keep the original data in their format-independent parsed model.
    """
    chunks: list[bytes] = []
    dropped: list[dict] = []
    offset = 0

    while offset < len(data):
        start = offset
        try:
            (
                field_number,
                wire_type,
                payload_start,
                payload_end,
                offset,
            ) = _field_bounds(data, offset)
        except WireDecodeError as exc:
            dropped.append({
                'path': '.'.join(map(str, path)) or '<root>',
                'field_number': None,
                'field_name': None,
                'wire_type': None,
                'expected_wire_type': None,
                'reason': str(exc),
                'raw_hex': data[start:].hex(),
            })
            break

        raw_field = data[start:offset]
        field = descriptor.fields_by_number.get(field_number)
        if field is None:
            chunks.append(raw_field)
            continue

        expected_wire_type = _expected_wire_type(field)
        field_path = (*path, field_number)
        if not _wire_type_matches(field, wire_type):
            dropped.append({
                'path': '.'.join(map(str, field_path)),
                'field_number': field_number,
                'field_name': field.name,
                'wire_type': wire_type,
                'expected_wire_type': expected_wire_type,
                'reason': 'wire_type_mismatch',
                'raw_hex': raw_field.hex(),
            })
            continue

        payload = data[payload_start:payload_end]
        if field.type == FieldDescriptor.TYPE_STRING and wire_type == 2:
            try:
                payload.decode('utf-8')
            except UnicodeDecodeError:
                dropped.append({
                    'path': '.'.join(map(str, field_path)),
                    'field_number': field_number,
                    'field_name': field.name,
                    'wire_type': wire_type,
                    'expected_wire_type': expected_wire_type,
                    'reason': 'invalid_utf8',
                    'raw_hex': raw_field.hex(),
                })
                continue

        if field.type == FieldDescriptor.TYPE_MESSAGE and wire_type == 2:
            cleaned, nested_dropped = sanitize_protobuf(
                payload, field.message_type, field_path
            )
            dropped.extend(nested_dropped)
            if cleaned != payload:
                key = (field_number << 3) | 2
                chunks.extend((
                    _encode_varint(key),
                    _encode_varint(len(cleaned)),
                    cleaned,
                ))
                continue

        chunks.append(raw_field)

    cleaned = b''.join(chunks)
    return (cleaned if dropped else data), dropped
