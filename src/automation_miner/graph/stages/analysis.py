"""Analysis stages: ingest, input preflight, domain map, five layer analyses."""

from __future__ import annotations

import time
from html import escape
from pathlib import Path

from langgraph.types import Send

from automation_miner import ingest as ing
from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.workspace import write_json
from automation_miner.context import layer_query, render_chunks
from automation_miner.graph.stages.base import StageBase, Update, layout_of
from automation_miner.graph.state import MinerState
from automation_miner.prompts import (
    DOMAIN_MAP_SYSTEM,
    INPUT_ASSESSMENT_SYSTEM,
    LAYER_ANALYST_SYSTEM,
    domain_map_prompt,
    input_assessment_prompt,
    layer_analysis_prompt,
)
from automation_miner.readers import build_registry
from automation_miner.schemas import (
    LAYER_ORDER,
    AnalysisMode,
    ContextPacket,
    DomainMap,
    InputAssessment,
    Layer,
    LayerAnalysis,
)


class AnalysisStages(StageBase):
    def _read_input(self, state: MinerState) -> ContextPacket:
        kind, value = state["input_kind"], state["input_value"]
        if kind == "idea":
            return ing.ingest_idea(
                value, state["constraints"], self.budget, preflight_callback=self.preflight_callback
            )
        reader = ing.ingest_file if kind == "file" else ing.ingest_kb
        return reader(
            Path(value), state["constraints"], self.model, self.budget,
            build_registry(self.model.config.readers), self.workspace.cache_dir,
            self.preflight_callback,
        )

    def ingest(self, state: MinerState) -> Update:
        self._mark_stage("ingest")
        started = time.time()
        run_dir = Path(state["run_dir"])
        packet = self._reuse(state, RunLayout(run_dir).context, ContextPacket)
        if packet is None:
            packet = self._read_input(state).model_copy(
                update={
                    "constraint_params": state.get("constraint_params", {}),
                    "raw_constraints": state.get("policy_constraints", ""),
                }
            )
            write_json(RunLayout(run_dir).context, packet)
        return {
            "context": packet.model_dump(mode="json"),
            "run_dir": str(run_dir),
            "run_id": run_dir.name,
            "stage_seconds": self._timed(state, "ingest", started),
        }

    def assess_input(self, state: MinerState) -> Update:
        self._mark_stage("input_assessment")
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        result = self._reuse(state, layout_of(state).input_assessment, InputAssessment)
        if result is None:
            result = self.model.call_json(
                "mapper",
                INPUT_ASSESSMENT_SYSTEM,
                input_assessment_prompt(ctx.overview, state.get("requested_mode", "auto")),
                InputAssessment,
            )
            write_json(layout_of(state).input_assessment, result)
        return {
            "input_assessment": result.model_dump(mode="json"),
            "stage_seconds": self._timed(state, "input_assessment", started),
        }

    def domain_map(self, state: MinerState) -> Update:
        self._mark_stage("domain_map")
        started = time.time()
        ctx = ContextPacket.model_validate(state["context"])
        assessment = InputAssessment.model_validate(state["input_assessment"])
        requested = AnalysisMode(state.get("requested_mode", AnalysisMode.AUTO))
        auto = requested is AnalysisMode.AUTO
        mode = AnalysisMode(assessment.recommended_mode) if auto else requested
        prompt = domain_map_prompt(
            ctx.domain, ctx.constraints, ctx.overview, mode.value,
            assessment.model_dump_json(indent=2),
        )
        cached = self._reuse(state, layout_of(state).domain_map, DomainMap)
        result = cached or self.model.call_json("mapper", DOMAIN_MAP_SYSTEM, prompt, DomainMap)
        result = result.model_copy(update={"analysis_mode": mode.value})
        write_json(layout_of(state).domain_map, result)
        return {
            "domain_map": result.model_dump(mode="json"),
            "analysis_mode": mode.value,
            "stage_seconds": self._timed(state, "domain_map", started),
        }

    @staticmethod
    def fanout_layers(state: MinerState) -> list[Send]:
        shared = {
            "context": state["context"],
            "domain_map": state["domain_map"],
            "run_dir": state["run_dir"],
            "constraints": state["constraints"],
            "analysis_mode": state["analysis_mode"],
            "resume": state.get("resume", False),
        }
        return [Send("analyze_layer", {**shared, "layer": layer.value}) for layer in LAYER_ORDER]

    def _layer_evidence(self, state: MinerState, layer: Layer) -> str:
        """The chunks most relevant to this layer, headed by the fenced domain map."""
        ctx = ContextPacket.model_validate(state["context"])
        domain_map = DomainMap.model_validate(state["domain_map"])
        selected = self._index(state).select(
            layer_query(layer, ctx.domain, domain_map.manual_friction), self.budget.layer_tokens
        )
        fenced = escape(domain_map.model_dump_json(indent=2), quote=False)
        header = f"Domain map:\n<untrusted-artifact>\n{fenced}\n</untrusted-artifact>"
        return render_chunks(selected, header=header)

    def analyze_layer(self, state: MinerState) -> Update:
        self._mark_stage("layer_analysis")
        started = time.time()
        layer = Layer(state["layer"])
        cached = self._reuse(state, layout_of(state).layer(layer.value), LayerAnalysis)
        if cached is not None:
            return {"layer_analyses": [cached.model_dump(mode="json")]}
        ctx = ContextPacket.model_validate(state["context"])
        prompt = layer_analysis_prompt(
            layer.value, ctx.domain, ctx.constraints, self._layer_evidence(state, layer),
            state["analysis_mode"],
        )
        result = self.model.call_json("layer_analyst", LAYER_ANALYST_SYSTEM, prompt, LayerAnalysis)
        result = result.model_copy(update={"layer": layer})
        write_json(layout_of(state).layer(layer.value), result)
        self._record_worker("layer_analysis", started)
        return {"layer_analyses": [result.model_dump(mode="json")]}
