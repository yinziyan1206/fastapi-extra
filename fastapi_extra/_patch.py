__author__ = "ziyan.yin"
__date__ = "2026-01-13"

from re import Pattern
from typing import Any, Mapping, Sequence

from fastapi import params
from fastapi._compat import (ModelField, get_cached_model_fields,
                             lenient_issubclass, shared)
from fastapi.dependencies import utils
from fastapi.routing import _IncludedRouter
from pydantic import BaseModel, Json
from pydantic.fields import FieldInfo
from starlette import datastructures
from starlette._utils import get_route_path
from starlette.routing import Match, compile_path

from fastapi_extra.urlparse import parse_qsl

_BOOL_MAP: dict[int, bool] = {}
_PREFIX_MAP: dict[int, Pattern[str]] = {}

_original_included_match = _IncludedRouter._match


def is_sequence_field(annotation: type[Any] | None) -> bool:
    _id = id(annotation)
    if _id not in _BOOL_MAP:
        _BOOL_MAP[_id] = shared.field_annotation_is_sequence(annotation)
    return _BOOL_MAP[_id]


def is_json_field(field_info: FieldInfo):
    _id = id(field_info)
    if _id not in _BOOL_MAP:
        _BOOL_MAP[_id] = any(type(item) is Json for item in field_info.metadata)
    return _BOOL_MAP[_id]


def _get_multidict_value(
    field: ModelField,
    values: Mapping[str, Any],
    alias: str,
    is_json: bool,
    is_sequence: bool,
) -> Any:
    if (not is_json) and is_sequence and hasattr(values, "getlist"):
        value = values.getlist(alias)  # pyright: ignore[reportAttributeAccessIssue]
    else:
        value = values.get(alias, None)

    if (value == "" and isinstance(field.field_info, params.Form)) or (
        is_sequence and len(value) == 0
    ):
        return None

    return value


def request_params_to_args(
    fields: Sequence[ModelField],
    received_params: Mapping[str, Any]
    | datastructures.QueryParams
    | datastructures.Headers,
) -> tuple[dict[str, Any], list[Any]]:
    values: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []

    if not fields:
        return values, errors

    first_field = fields[0]

    is_multidict = hasattr(received_params, "getlist")
    is_headers = isinstance(received_params, datastructures.Headers)

    # =========================================================================
    # 分支 A：单模型解析 (例如使用 Pydantic 接收整个 Query 或是 Header 结构)
    # =========================================================================
    if len(fields) == 1 and lenient_issubclass(
        first_field.field_info.annotation, BaseModel
    ):
        fields_to_extract = get_cached_model_fields(first_field.field_info.annotation)
        default_convert_underscores = getattr(
            first_field.field_info, "convert_underscores", True
        )

        params_to_process: dict[str, Any] = {}
        processed_keys = set()

        for field in fields_to_extract:
            field_alias = utils.get_validation_alias(field)
            alias = field_alias

            if is_headers:
                convert_underscores = getattr(
                    field.field_info, "convert_underscores", default_convert_underscores
                )
                if convert_underscores and alias == field.name:
                    alias = alias.replace("_", "-")

            # 提前准备属性判断
            is_json = is_json_field(field.field_info)
            is_sequence = is_sequence_field(field.field_info.annotation)

            value = _get_multidict_value(
                field,
                received_params,
                alias=alias,
                is_json=is_json,
                is_sequence=is_sequence,
            )
            if value is not None:
                params_to_process[field_alias] = value
            processed_keys.add(alias)

        # 补全未在模型中显式定义的其他传入参数
        for key in received_params.keys():
            if key not in processed_keys:
                if is_multidict:
                    value = received_params.getlist(key)  # type: ignore
                    params_to_process[key] = (
                        value[0]
                        if isinstance(value, list) and len(value) == 1
                        else value
                    )
                else:
                    params_to_process[key] = received_params.get(key)

        field_info = first_field.field_info
        assert isinstance(
            field_info, params.Param
        ), "Params must be subclasses of Param"

        v_, errors_ = first_field.validate(
            params_to_process, values, loc=(field_info.in_.value,)
        )
        return {first_field.name: v_}, errors_

    # =========================================================================
    # 分支 B：多参数平铺解析 (Fast Path - 大部分常规路由走这里)
    # =========================================================================
    else:
        for field in fields:
            field_alias = utils.get_validation_alias(field)
            field_info = field.field_info

            # 属性判断预提取与缓存
            is_json = is_json_field(field_info)
            is_sequence = is_sequence_field(field_info.annotation)

            value = _get_multidict_value(
                field,
                received_params,
                alias=field_alias,
                is_json=is_json,
                is_sequence=is_sequence,
            )

            assert isinstance(
                field_info, params.Param
            ), "Params must be subclasses of Param"
            loc = (field_info.in_.value, field_alias)

            v_, errors_ = utils._validate_value_with_model_field(
                field=field, value=value, values=values, loc=loc
            )
            if errors_:
                errors.extend(errors_)
            else:
                values[field.name] = v_

        return values, errors


def query_params_init(obj: datastructures.QueryParams, *args, **kwargs) -> None:
    value = args[0] if args else []

    if isinstance(value, bytes):
        super(datastructures.QueryParams, obj).__init__(
            parse_qsl(value, keep_blank_values=True), **kwargs
        )
    elif isinstance(value, str):
        super(datastructures.QueryParams, obj).__init__(
            parse_qsl(value.encode("latin-1"), keep_blank_values=True), **kwargs
        )
    else:
        super(datastructures.QueryParams, obj).__init__(*args, **kwargs)  # type: ignore[arg-type]
        obj._list = [(str(k), str(v)) for k, v in obj._list]
        obj._dict = {str(k): str(v) for k, v in obj._dict.items()}


def _get_prefix_regex(self):
    _id = id(self)
    if _id not in _PREFIX_MAP:
        prefix = (
            self.include_context.prefix + self.original_router.prefix + "{path:path}"
        )
        _PREFIX_MAP[_id] = compile_path(prefix)[0]
    return _PREFIX_MAP[_id]


def patched_included_match(self, scope):
    if not self.original_router.routes:
        return Match.NONE, {}, None, None
    prefix_regex = _get_prefix_regex(self)
    route_path = get_route_path(scope)
    match = prefix_regex.match(route_path)
    if match:
        return _original_included_match(self, scope)
    return Match.NONE, {}, None, None
