__author__ = "ziyan.yin"
__describe__ = ""


def unquote(val: bytes, encoding: str = "utf-8") -> str: ...


def unquote_plus(val: bytes, encoding: str = "utf-8") -> str: ...


def parse_qsl(qs: bytes, keep_blank_values: bool = False) -> list[tuple[str, str]]: ...
