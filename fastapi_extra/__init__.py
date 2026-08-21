__version__ = "0.9.0"


from fastapi import FastAPI
from fastapi import routing as origin_routing
from fastapi.dependencies import utils as origin_utils
from fastapi.routing import _IncludedRouter


def setup(app: FastAPI) -> None:
    try:
        from fastapi_extra import _patch

        origin_routing.solve_dependencies.__globals__[  # type: ignore
            "field_annotation_is_sequence"
        ] = _patch.is_sequence_field
        origin_routing.solve_dependencies.__globals__["request_params_to_args"] = (  # type: ignore
            _patch.request_params_to_args
        )
        origin_utils.QueryParams.__init__ = _patch.query_params_init  # type: ignore
        _IncludedRouter._match = _patch.patched_included_match  # type: ignore
    except ImportError:  # pragma: nocover
        pass
