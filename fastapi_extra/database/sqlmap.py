__author__ = "ziyan.yin"
__date__ = "2026-05-14"


import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import (Any, Callable, Protocol, get_args, get_origin,
                    get_type_hints)

from pydantic import BaseModel, Field
from sqlmodel import text
from sqlmodel.ext.asyncio.session import AsyncSession

from fastapi_extra.settings import Settings
from fastapi_extra.types import NoneType, P, T


class SQLTemplateConfig(BaseModel):
    path: str = Field(default="./template/sql")
    suffix: str = Field(default=".sql")


class SQLTemplateSettings(Settings):
    sqlmap: SQLTemplateConfig = Field(alias="sqlmap")


_settings = SQLTemplateSettings() # type: ignore
_templates = {}


def install() -> None:
    path = Path(_settings.sqlmap.path)
    if not path.exists():
        return
    for file in path.glob(f"*{_settings.sqlmap.suffix}"):
        _templates[file.stem] = text(file.read_text(encoding="utf-8"))


def _is_base_model(cls: Any) -> bool:
    """安全判断是否为 Pydantic BaseModel"""
    try:
        return isinstance(cls, type) and issubclass(cls, BaseModel)
    except TypeError:
        return False


class SessionService(Protocol):
    session: AsyncSession


def Mapped(func: Callable[P, T]) -> Callable[P, T]:
    func_name = func.__name__
    
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    return_hint = hints.get("return", NoneType)
    
    origin = get_origin(return_hint)
    args = get_args(return_hint)

    # 1. 预校验 SQL 模板是否存在
    if func_name not in _templates:
        # 这里可以选择抛异常或者在运行时加载
        pass
    
    # 处理 NoneType / 返回为空
    if return_hint is NoneType:
        async def execute_only(self: SessionService, *args: Any, **kwargs: Any) -> None:
            bound_args = sig.bind(self, *args, **kwargs)
            bound_args.apply_defaults()
        
            # 3. 构造 SQL 参数字典
            # 排除掉第一个参数 (self 或 service)，剩下的传给 SQL execute
            all_params = bound_args.arguments
            param_names = list(all_params.keys())
            if param_names:
                sql_params = {k: all_params[k] for k in param_names[1:]}
            else:
                sql_params = {}
            
            await self.session.execute(_templates[func_name], params=sql_params)
        
        execute_only.__signature__ = sig
        return execute_only # type: ignore
    
    # 2. 解析返回逻辑
    # 处理列表/序列返回: List[User], Sequence[User]
    if origin is not None and issubclass(origin, Sequence):
        inner_type = args[0] if args else Any
        is_model = _is_base_model(inner_type)

        async def fetch_all(self: SessionService, *args: Any, **kwargs: Any) -> Sequence:
            bound_args = sig.bind(self, *args, **kwargs)
            bound_args.apply_defaults()
        
            # 3. 构造 SQL 参数字典
            # 排除掉第一个参数 (self 或 service)，剩下的传给 SQL execute
            all_params = bound_args.arguments
            param_names = list(all_params.keys())
            if param_names:
                sql_params = {k: all_params[k] for k in param_names[1:]}
            else:
                sql_params = {}
            
            sql = _templates[func_name]
            result = await self.session.execute(sql, params=sql_params)
            # 使用 scalars() 获取单列结果，如果是多列会自动映射到 Row
            items = result.all() if is_model else result.scalars().all()
            if is_model:
                return [inner_type.model_validate(row, from_attributes=True) for row in items] # type: ignore
            return items
        
        fetch_all.__signature__ = sig
        return fetch_all # type: ignore
    
    # 处理单体返回 (Optional[User] 或 User)
    is_nullable = NoneType in args
    # 提取实际类型 (处理 Optional[User] 拿到 User)
    actual_type = next((a for a in args if a is not NoneType), return_hint)
    is_model = _is_base_model(actual_type)

    async def fetch_one(self: SessionService, *args: Any, **kwargs: Any) -> Any:
        bound_args = sig.bind(self, *args, **kwargs)
        bound_args.apply_defaults()
        
         # 3. 构造 SQL 参数字典
        # 排除掉第一个参数 (self 或 service)，剩下的传给 SQL execute
        all_params = bound_args.arguments
        param_names = list(all_params.keys())
        if param_names:
            sql_params = {k: all_params[k] for k in param_names[1:]}
        else:
            sql_params = {}
        
        sql = _templates[func_name]
        result = await self.session.execute(sql, params=sql_params)
        
        # 根据是否是模型决定取 row 还是 scalar
        data = result.first() if is_model else result.scalar_one_or_none()
        
        if data is None:
            if is_nullable: 
                return None
            raise ValueError(f"Query {func_name} expected a result but got None")
            
        if is_model:
            # 将 Row 转为 dict 再校验
            return actual_type.model_validate(data, from_attributes=True)
        return data
    
    fetch_one.__signature__ = sig
    return fetch_one # type: ignore
    