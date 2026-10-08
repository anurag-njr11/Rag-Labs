"""Compute slot: route numeric questions to sanctioned, attested computations (FR-3.21).

The IO lives in engine/compute.py; the computations themselves are project data (Data tab), not
pipeline config, so editing one never creates a version.
"""

from __future__ import annotations

from typing import Literal

from ..core.node import Node, NodeConfig, register, ui_field


class NoComputeConfig(NodeConfig):
    pass


@register("compute", "none", title="Off", description="Answer every question from the documents.")
class NoCompute(Node):
    Config = NoComputeConfig


class AttestedConfig(NodeConfig):
    on_fail: Literal["documents", "refuse"] = ui_field(
        "documents", title="If the result fails attestation",
        description="documents: answer from the documents instead, with a warning that their numbers may be "
                    "out of date. refuse: say the value couldn't be verified.",
        json_schema_extra={"enum_labels": {"documents": "Answer from the documents (with a warning)",
                                           "refuse": "Say it couldn't be verified"}})


@register("compute", "attested", title="Attested computations",
          description="Before retrieving, the Generate model checks whether a computation on the Data tab answers "
                      "the question and fills in its parameters (it can't write queries). The query runs "
                      "read-only, its result must pass the computation's checks, and the number is shown exactly "
                      "as computed, with a receipt. One extra LLM call per question.")
class AttestedCompute(Node):
    Config = AttestedConfig
