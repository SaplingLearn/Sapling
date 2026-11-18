"""Per-run observation of the actual SDK model dispatch/response boundary."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import config
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.wrapper import WrapperModel

from services import checklist_budget


def _reserved(model: Model, reservation: checklist_budget.Reservation) -> bool:
    """A real model on a provider a checklist bill can come from (Gemini's
    Developer API or Anthropic's first-party API), named in the reservation."""
    if isinstance(model, GoogleModel):
        native = model.system in {"google", "google-gla"}
    elif isinstance(model, AnthropicModel):
        native = model.system == "anthropic"
    else:
        return False
    return native and checklist_budget.billing_label(model.model_name) in reservation.models


@dataclass
class ChecklistDispatches(AbstractCapability[dict]):
    reservation: checklist_budget.Reservation
    responses: list[ModelResponse] = field(default_factory=list)
    dispatched: int = 0
    nonbillable_test: bool = False

    async def wrap_model_request(self, ctx, *, request_context, handler):
        model = request_context.model
        while isinstance(model, WrapperModel):
            model = model.wrapped
        nonbillable = isinstance(model, FunctionModel) and config.IS_LOCAL
        if nonbillable:
            # Explicit local FunctionModel seam. Never infer "free" from a zero
            # counter, a provider error or absent metadata on a real response.
            pass
        elif not _reserved(model, self.reservation):
            raise ValueError("Checklist model is outside the reserved price policy")
        if self.dispatched and nonbillable != self.nonbillable_test:
            raise ValueError("Checklist run cannot mix billable and test model requests")
        self.nonbillable_test = nonbillable
        if self.dispatched == 0 and not self.nonbillable_test:
            self.reservation = await asyncio.to_thread(checklist_budget.start, self.reservation)
        # Count immediately before handler(), independently of SDK RunUsage.
        # A raised/timeout call stays counted even when no response is returned.
        self.dispatched += 1
        response = await handler(request_context)
        self.responses.append(response)
        return response
