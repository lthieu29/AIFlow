"""Version 1 wire formats shared by manual imports and remote generation."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Brief(StrictModel):
    language: Literal["en", "vi"] = "en"
    title: str = Field(min_length=1, max_length=200)
    idea: str = Field(min_length=1, max_length=10000)
    series_bible: str = Field(max_length=20000)
    target_seconds: int = Field(ge=4, le=360)
    audience: str = Field(default="Adults who enjoy original short mysteries", max_length=1000)
    tone: str = Field(default="Suspenseful, grounded, non-graphic", max_length=1000)
    viewer_promise: str = Field(default="", max_length=2000)
    constraints: str = Field(default="", max_length=3000)
    narration_wpm: int = Field(default=135, ge=100, le=300,
                               description="Planning pace: Vietnamese space-delimited syllables/minute (100-300), English words/minute (100-180). Not TTS speed.")

    @model_validator(mode="after")
    def language_pace(self):
        if self.language == "en" and self.narration_wpm > 180:
            raise ValueError("English narration planning pace must be 100-180 words/minute.")
        return self


class Outline(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    beats: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(min_length=3, max_length=60)
    continuity_notes: str = Field(max_length=10000)
    logline: str = Field(default="", max_length=1000)
    opening_hook: str = Field(default="", max_length=1500)
    ending_payoff: str = Field(default="", max_length=2000)
    clue_ledger: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=12)


class ScriptScene(StrictModel):
    visual_prompt: str = Field(min_length=1, max_length=3000)
    narration: str = Field(max_length=1000, description="Spoken narration in the brief's language; empty for an intentional silent shot.")
    duration: float = Field(ge=4, le=8)
    location_hint: Literal["indoor", "outdoor", "transition", "unspecified"]
    story_beat: Literal["hook", "setup", "escalation", "reveal", "payoff", "unspecified"] = "unspecified"
    purpose: str = Field(default="", max_length=1000, description="What changes in this shot and why the story needs it.")


class Script(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    scenes: list[ScriptScene] = Field(min_length=1, max_length=60)
    continuity_notes: str = Field(max_length=10000)


Criterion = Literal["hook", "causality", "continuity", "payoff", "speakability", "visual_feasibility", "originality"]
CRITERIA = {"hook", "causality", "continuity", "payoff", "speakability", "visual_feasibility", "originality"}


class ReviewFinding(StrictModel):
    criterion: Criterion
    verdict: Literal["pass", "revise", "uncertain"]
    scene_numbers: list[int] = Field(max_length=60)
    evidence: str = Field(min_length=1, max_length=2000)
    suggested_fix: str = Field(max_length=2000)


class Review(StrictModel):
    summary: str = Field(min_length=1, max_length=10000)
    issues: list[str] = Field(max_length=30)
    recommendation: Literal["approve", "revise"]
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def complete_rubric(self):
        if self.findings and (len(self.findings) != 7 or {item.criterion for item in self.findings} != CRITERIA):
            raise ValueError("Review must cover each of the seven criteria exactly once")
        if self.recommendation == "approve" and any(item.verdict == "revise" for item in self.findings):
            raise ValueError("A review with required revisions cannot recommend approval")
        return self


def strict_schema(schema: type[BaseModel]) -> dict:
    """Require every output field remotely while accepting legacy defaults on import."""
    result = schema.model_json_schema()
    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(result)
    return result


SCHEMAS = {"brief": Brief, "outline": Outline, "script": Script, "revise": Script,
           "manual": Script, "review": Review}
