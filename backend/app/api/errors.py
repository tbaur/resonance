# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""API errors and helpers."""

from __future__ import annotations

from fastapi import HTTPException

from app.logging import request_id_var
from app.models import ErrorBody


class AppError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(
            status_code=status_code,
            detail=ErrorBody(
                error=code,
                message=message,
                code=code,
                request_id=request_id_var.get("-"),
            ).model_dump(),
        )
