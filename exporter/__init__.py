import re

def sanitize_filename(filename):
    illegal_chars = r'[<>:"/\\|?*]'
    if isinstance(filename,int):
        return filename
    return re.sub(illegal_chars, '_', filename)