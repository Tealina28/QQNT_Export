import re

def sanitize_filename(filename):
    illegal_chars = r'[<>:"/\\|?*]'
    return re.sub(illegal_chars, '_', str(filename))