from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ProcedureSelection(BaseModel):
    procedure_ids: list[uuid.UUID] | None = None
    issuing_agency: str | None = None
    domain: str | None = None
    implementing_agency: str | None = None

    def filters(self) -> dict[str, str]:
        values = {
            "issuing_agency": self.issuing_agency,
            "domain": self.domain,
            "implementing_agency": self.implementing_agency,
        }
        return {key: value for key, value in values.items() if value is not None}


class ProcessDraftsRequest(ProcedureSelection):
    pass


class PublishProceduresRequest(ProcedureSelection):
    batch_size: int = Field(default=64, ge=1)
