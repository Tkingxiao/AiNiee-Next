"""Render-side planning helpers for MangaCore."""

__all__ = ["BubbleAssignment", "assign_bubbles", "plan_text_blocks"]


def __getattr__(name: str):
    if name in {"BubbleAssignment", "assign_bubbles"}:
        from .bubbleAssign import BubbleAssignment, assign_bubbles

        return {"BubbleAssignment": BubbleAssignment, "assign_bubbles": assign_bubbles}[name]
    if name == "plan_text_blocks":
        from .planner import plan_text_blocks

        return plan_text_blocks
    raise AttributeError(name)
