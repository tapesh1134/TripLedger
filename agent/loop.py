"""Bounded native function-calling loop over discovered MCP tools."""

import asyncio
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import Any, Protocol

from mcp import ClientSession, types
from pydantic import AnyUrl

from agent.contracts import function_schema
from agent.memory import context_size
from agent.prompts import SYSTEM
from app.assembler import validate_candidate
from app.intake import redact
from integrations.model_client import ModelResponse, ProviderError
from mcp_server.schemas import Decision, ExpenseReport


class ChatModel(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ModelResponse: ...


async def review(
    report: ExpenseReport,
    session: ClientSession,
    model: ChatModel,
    model_name: str,
    max_steps: int = 12,
    queue: bool = False,
) -> dict[str, Any]:
    if not 1 <= max_steps <= 12:
        raise ValueError("max_steps must be 1..12")
    started = time.perf_counter()
    trace: dict[str, Any] = {
        "report": report.model_dump(mode="json"),
        "resources": {},
        "steps": [],
        "tools": [],
        "status": "running",
    }
    events: list[dict[str, Any]] = trace["tools"]
    steps = 0
    input_tokens, output_tokens = 0, 0
    usage_complete = True

    def partial(reason: str) -> dict[str, Any]:
        trace["status"] = "incomplete"
        trace["reason"] = reason
        return {
            "status": "incomplete",
            "decision": {
                "report_id": report.report_id,
                "decision": "manager_review",
                "confidence": 0.0,
                "reimbursable_total": None,
                "disallowed_total": None,
                "reason": reason,
            },
            "queued": False,
            "trace": trace,
        }

    try:
        discovered = await session.list_tools()
        definitions: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description or "",
                    "parameters": function_schema(item.inputSchema),
                },
            }
            for item in discovered.tools
            if item.name != "save_decision"
        ]
        allowed = {item["function"]["name"] for item in definitions}
        for uri in (
            "tripledger://policy/expense-policy",
            "tripledger://policy/per-diem",
            "tripledger://reference/mcc-codes",
        ):
            resource_response = await session.read_resource(AnyUrl(uri))
            text = "\n".join(
                x.text
                for x in resource_response.contents
                if isinstance(x, types.TextResourceContents)
            )
            trace["resources"][uri] = redact(text)
        policy_text = trace["resources"]["tripledger://policy/expense-policy"]
        policy = {}
        for key in ("version", "auto_approval_ceiling", "minimum_auto_approval_confidence"):
            match = re.search(r"^" + key + r":\s*(\S+)", policy_text, re.M)
            if not match:
                return partial("POLICY_METADATA_MISSING")
            policy[key] = match.group(1)
        schema = Decision.model_json_schema()
        schema["properties"].pop("meta")
        schema["required"].remove("meta")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM + "\nFINAL_SCHEMA:\n" + json.dumps(schema)},
            {
                "role": "user",
                "content": "POLICY_RESOURCES:\n"
                + json.dumps(trace["resources"])
                + "\nUNTRUSTED_REPORT_JSON:\n"
                + report.model_dump_json(),
            },
        ]
        trace["initial_messages"] = messages.copy()
        prompt_hash = "sha256:" + hashlib.sha256(messages[0]["content"].encode()).hexdigest()
        seen: dict[str, int] = {}
        for steps in range(1, max_steps + 1):
            if context_size(messages) > 150000:
                return partial("CONTEXT_LIMIT")
            try:
                response = await asyncio.to_thread(model.complete, messages, definitions)
            except ProviderError as error:
                trace["provider_error"] = str(error)
                return partial("MODEL_API_ERROR")
            for key in ("tokens_in", "tokens_out"):
                value = response.usage.get(key)
                if not isinstance(value, int):
                    usage_complete = False
                elif key == "tokens_in":
                    input_tokens += value
                else:
                    output_tokens += value
            message = {
                key: response.message[key]
                for key in ("content", "tool_calls")
                if key in response.message
            }
            message["role"] = "assistant"
            message = redact(message)
            trace["steps"].append({"step": steps, "response": message, "usage": response.usage})
            messages.append(message)
            calls = message.get("tool_calls")
            if calls:
                if not isinstance(calls, list) or len(calls) > 12:
                    return partial("INVALID_OR_EXCESSIVE_TOOL_CALLS")
                for call in calls:
                    if len(events) >= 48:
                        return partial("TOOL_CALL_LIMIT")
                    if not isinstance(call, dict) or not isinstance(call.get("id"), str):
                        return partial("MALFORMED_TOOL_CALL")
                    function = call.get("function", {})
                    name = function.get("name", "")
                    args: dict[str, Any] = {}
                    try:
                        args = json.loads(function.get("arguments", "{}"))
                        if not isinstance(args, dict):
                            raise ValueError
                        signature = json.dumps([name, args], sort_keys=True)
                        seen[signature] = seen.get(signature, 0) + 1
                        if name not in allowed:
                            code = "TOOL_NOT_AVAILABLE"
                        elif seen[signature] > 2:
                            code = "REPEATED_TOOL_CALL"
                        elif (
                            "employee_id" in args
                            and args["employee_id"] != report.employee_id
                            or name == "get_trip"
                            and args.get("trip_id") != report.trip_id
                            or name == "read_receipt"
                            and args.get("file_path")
                            not in {x.receipt_file for x in report.line_items if x.receipt_file}
                        ):
                            code = "OUTSIDE_REPORT_SCOPE"
                        else:
                            code = ""
                        if code:
                            result = {
                                "ok": False,
                                "error": {
                                    "code": code,
                                    "hint": "Use existing evidence or correct the arguments.",
                                },
                            }
                        else:
                            output = await session.call_tool(name, args)
                            result = output.structuredContent or {
                                "ok": False,
                                "error": {"code": "MCP_TOOL_ERROR"},
                            }
                    except (ValueError, TypeError):
                        result = {"ok": False, "error": {"code": "INVALID_TOOL_ARGUMENT_JSON"}}
                    result = redact(result)
                    events.append(
                        {"step": steps, "name": name, "args": redact(args), "result": result}
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}
                    )
                continue
            text = (message.get("content") or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
            try:
                candidate = json.loads(text)
                if not isinstance(candidate, dict):
                    raise ValueError
            except (ValueError, TypeError):
                messages.append(
                    {
                        "role": "user",
                        "content": "Return one valid final JSON object, or call a tool.",
                    }
                )
                continue
            meta = {
                "model": model_name,
                "policy_version": policy["version"],
                "prompt_hash": prompt_hash,
                "tokens_in": input_tokens if usage_complete else None,
                "tokens_out": output_tokens if usage_complete else None,
                "steps": steps,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "created_at": datetime.now(UTC).isoformat(),
            }
            decision, problems = validate_candidate(candidate, report, events, meta, policy)
            if problems:
                trace["steps"][-1]["validation_feedback"] = problems
                messages.append(
                    {
                        "role": "user",
                        "content": "Validation failed: "
                        + json.dumps(problems)
                        + ". Correct these issues using tools if needed.",
                    }
                )
                continue
            assert decision is not None
            final = decision.model_dump(mode="json")
            queue_result: dict[str, Any] | None = None
            if queue:
                saved = await session.call_tool("save_decision", final)
                queue_result = saved.structuredContent
            trace["status"] = "complete"
            trace["decision"] = final
            trace["queue_result"] = queue_result
            trace["messages"] = messages
            return {
                "status": "complete",
                "decision": final,
                "queued": bool(
                    queue_result and queue_result.get("ok") and queue_result["data"].get("queued")
                ),
                "queue_result": queue_result,
                "trace": trace,
            }
        return partial("STEP_BUDGET_EXHAUSTED")
    except Exception as error:
        # Exception type only: provider/transport messages can include credentials/URLs.
        trace["exception_type"] = type(error).__name__
        return partial("MCP_OR_LOCAL_FAILURE")
