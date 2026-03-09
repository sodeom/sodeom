"""UTF-8 / binary string encoding utilities."""


def utf8_string_to_binary(input_str: str) -> str:
    """Encode a UTF-8 string as a binary digit string, padded to 64-bit alignment."""
    byte_data = input_str.encode("utf-8")
    binary = "".join(format(byte, "08b") for byte in byte_data)
    while len(binary) % 64 != 0:
        binary += "0"
    return binary


def binary_to_utf8_string(binary_str: str) -> str:
    """Decode a binary digit string back to a UTF-8 string (strips zero-byte padding)."""
    if len(binary_str) % 8 != 0:
        raise ValueError("Binary string length must be a multiple of 8")
    byte_list = [int(binary_str[i : i + 8], 2) for i in range(0, len(binary_str), 8)]
    while byte_list and byte_list[-1] == 0:
        byte_list.pop()
    return bytes(byte_list).decode("utf-8")
