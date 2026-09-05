from typing import List
import re

def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 100) -> List[str]:
    '''
    简单的滑动窗口分块策略。
    按段落或句子优先分块，如果一个段落太长没法按标点拆，则强制按字数切断。
    '''
    if not text:
        return []
    
    # 简单的按字切分（基于滑动窗口）
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= text_len:
            break
        # 加上重叠部分前移
        start += chunk_size - chunk_overlap
        
    return chunks
