from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx/5xx responses."""

    success: bool = Field(False, description="Always false for error responses")
    error_code: str = Field(..., description="Internal error code (e.g. ERR_INVALID_SCHEMA)")
    error_message: str = Field(..., description="Human-readable error detail")
    correlation_id: str | None = Field(None, description="Trace ID if available")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": False,
                "error_code": "ERR_INVALID_SCHEMA",
                "error_message": "Field 'data_source_type' is required.",
                "correlation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
            }
        }
    }
