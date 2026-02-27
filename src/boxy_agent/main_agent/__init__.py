"""Built-in internal main-agent orchestration package."""

from .agent import handle
from .config import MainAgentConfig, load_main_agent_config
from .orchestration import (
    ActionCall,
    ActionSelection,
    CompletionGateDecision,
    CompletionGateInput,
    CompletionStatus,
    TodoItem,
    TodoStatus,
    ToolCandidate,
    ToolCategory,
    evaluate_completion_gate,
    pick_single_action_call,
    should_replan,
    to_openai_tool_name,
    top_k_tools,
)

__all__ = [
    "handle",
    "MainAgentConfig",
    "load_main_agent_config",
    "ActionCall",
    "ActionSelection",
    "CompletionGateDecision",
    "CompletionGateInput",
    "CompletionStatus",
    "TodoItem",
    "TodoStatus",
    "ToolCandidate",
    "ToolCategory",
    "evaluate_completion_gate",
    "pick_single_action_call",
    "should_replan",
    "to_openai_tool_name",
    "top_k_tools",
]
