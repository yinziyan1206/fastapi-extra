# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False


__author__ = "ziyan.yin"
__describe__ = ""


from libc.stdlib cimport strtol
from libc.string cimport memmove, strlen


cdef inline size_t _unquote_optimized(char* c_str, bint change_plus) nogil:
    cdef:
        size_t n = strlen(c_str)
        size_t read_pos = 0
        size_t write_pos = 0
        char hex_buf[3]
        
    hex_buf[2] = 0 # 确保 strtol 有终止符

    while read_pos < n:
        if c_str[read_pos] == b'+' and change_plus:
            c_str[write_pos] = b' '
            read_pos += 1
            write_pos += 1
        elif c_str[read_pos] == b'%' and read_pos + 2 < n:
            # 提取两位十六进制数
            hex_buf[0] = c_str[read_pos + 1]
            hex_buf[1] = c_str[read_pos + 2]
            # 转换为字符
            c_str[write_pos] = <char>strtol(hex_buf, NULL, 16)
            read_pos += 3
            write_pos += 1
        else:
            # 普通字符移动
            c_str[write_pos] = c_str[read_pos]
            read_pos += 1
            write_pos += 1
            
    return write_pos

def unquote(bytes val, str encoding = "utf-8"):
    if not val: return ""
    # 注意：这里会修改原始 bytes 的内存（如果是从 Python 传进来的，通常是只读的）
    # 建议先 copy 一份或者使用 bytearray
    cdef bytearray tmp = bytearray(val)
    cdef char* c_raw = tmp
    cdef size_t new_len = _unquote_optimized(c_raw, 0)
    return tmp[:new_len].decode(encoding)


def unquote_plus(val: bytes, encoding: str = "utf-8") -> str:
    if not val: return ""
    # 注意：这里会修改原始 bytes 的内存（如果是从 Python 传进来的，通常是只读的）
    # 建议先 copy 一份或者使用 bytearray
    cdef bytearray tmp = bytearray(val)
    cdef char* c_raw = tmp
    cdef size_t new_len = _unquote_optimized(c_raw, 1)
    return tmp[:new_len].decode(encoding)


def parse_qsl(bytes qs, bint keep_blank_values = False):
    if not qs:
        return []
    
    cdef list r = []  # 修复未定义错误
    query_args = qs.split(b'&')
    
    for name_value in query_args:
        if not name_value:
            continue
        nv = name_value.split(b'=')
        
        if len(nv) < 2:
            if not keep_blank_values:
                continue
            name = unquote_plus(nv[0])
            value = ""
        else:
            name = unquote_plus(nv[0])
            value = unquote_plus(nv[1])
            
        r.append((name, value))
    return r
