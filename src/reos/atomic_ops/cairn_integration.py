"""CAIRN Integration with Atomic Operations.

This module integrates CAIRN (the Attention Minder) with the V2 atomic
operations architecture. Every CAIRN request flows through:

1. Classification - Request classified by 3x2x3 taxonomy + domain + action_hint
2. Behavior Mode - Classification mapped to execution strategy
3. Verification - Verification pipeline (FAST or STANDARD per mode)
4. Execution - Tool call + response generation via behavior mode
5. Feedback - RLHF feedback collection

The behavior mode registry replaces the old regex-based intent engine.
One LLM classification produces everything the system needs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .feedback import FeedbackCollector
from .models import (
    AtomicOperation,
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionResult,
    ExecutionSemantics,
    OperationStatus,
)
from .processor import AtomicOpsProcessor
from .verifiers import VerificationContext, VerificationPipeline
from .verifiers.pipeline import PipelineResult, VerificationMode

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from reos.cairn.intent_engine import CairnIntentEngine


@dataclass
class CairnOperationResult:
    """Result of processing a CAIRN operation through atomic ops pipeline."""

    operation: AtomicOperation
    verification: PipelineResult
    intent_result: Any | None = None  # IntentResult for agent.py compat
    response: str = ""
    approved: bool = False
    needs_approval: bool = False
    warnings: list[str] = field(default_factory=list)


# Domain → IntentCategory name mapping for backward compat with agent.py
_DOMAIN_TO_INTENT_CATEGORY = {
    "calendar": "CALENDAR",
    "contacts": "CONTACTS",
    "system": "SYSTEM",
    "play": "PLAY",
    "tasks": "TASKS",
    "knowledge": "KNOWLEDGE",
    "personal": "PERSONAL",
    "undo": "UNDO",
    "feedback": "FEEDBACK",
    "conversation": "CONVERSATION",
}

# Action hint → IntentAction name mapping
_ACTION_TO_INTENT_ACTION = {
    "view": "VIEW",
    "search": "SEARCH",
    "create": "CREATE",
    "update": "UPDATE",
    "delete": "DELETE",
    "status": "STATUS",
}


class CairnAtomicBridge:
    """Bridge between CAIRN and the atomic operations pipeline.

    Routes requests through: classification → behavior mode → verification → execution.
    The behavior mode registry replaces pattern-matching intent extraction.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        intent_engine: CairnIntentEngine | None = None,
        verification_mode: VerificationMode = VerificationMode.STANDARD,
        auto_approve_low_risk: bool = True,
    ):
        """Initialize the CAIRN atomic bridge.

        Args:
            conn: Database connection for atomic ops storage.
            intent_engine: CAIRN intent engine (provides LLM + play_data + response gen).
            verification_mode: Verification pipeline mode.
            auto_approve_low_risk: Auto-approve read-only operations.
        """
        # Extract LLM from intent engine for classification and decomposition
        llm = intent_engine.llm if intent_engine else None

        self.processor = AtomicOpsProcessor(conn, llm=llm)
        self.verifier = VerificationPipeline(mode=verification_mode)
        self.feedback = FeedbackCollector(self.processor.store)
        self.intent_engine = intent_engine
        self.auto_approve_low_risk = auto_approve_low_risk

        # Create behavior mode registry
        from reos.cairn.behavior_modes import create_default_registry

        self._behavior_registry = create_default_registry()

        # Create response generator
        from reos.cairn.response_generator import ResponseGenerator

        self._response_gen = ResponseGenerator(llm=llm)

        # Track last operation for undo
        self._last_operation_id: str | None = None

    def set_intent_engine(self, engine: CairnIntentEngine):
        """Set the CAIRN intent engine."""
        self.intent_engine = engine

    def process_request(
        self,
        user_input: str,
        user_id: str,
        execute_tool: Callable | None = None,
        persona_context: str = "",
        safety_level: str = "standard",
        conversation_context: str = "",
    ) -> CairnOperationResult:
        """Process a user request through the full atomic ops pipeline.

        Flow: classify → behavior mode → verify → execute → respond.

        Args:
            user_input: User's natural language request.
            user_id: User identifier.
            execute_tool: Function to execute MCP tools.
            persona_context: Context about the user (from THE_PLAY).
            safety_level: Safety level (permissive, standard, strict).
            conversation_context: Recent conversation for context.

        Returns:
            CairnOperationResult with operation, verification, and response.
        """
        # Step 1: Process through atomic ops pipeline (classification + decomposition)
        proc_result = self.processor.process_request(
            request=user_input,
            user_id=user_id,
            source_agent="cairn",
        )

        if not proc_result.success or not proc_result.operations:
            return CairnOperationResult(
                operation=AtomicOperation(user_request=user_input, user_id=user_id),
                verification=PipelineResult(
                    passed=False,
                    status=OperationStatus.FAILED,
                    results={},
                    warnings=["Failed to process request"],
                ),
                response="I couldn't process that request.",
            )

        # Check if decomposition needs clarification
        if proc_result.needs_clarification and proc_result.clarification_prompt:
            return CairnOperationResult(
                operation=AtomicOperation(user_request=user_input, user_id=user_id),
                verification=PipelineResult(
                    passed=True,
                    status=OperationStatus.AWAITING_APPROVAL,
                    results={},
                    warnings=["Clarification needed"],
                ),
                response=proc_result.clarification_prompt,
                needs_approval=True,
            )

        # Check if request was decomposed into multiple operations
        primary_op = proc_result.operations[0]
        if primary_op.is_decomposed and primary_op.child_ids:
            logger.debug("Decomposed into %d operations", len(primary_op.child_ids))
            return self._process_decomposed(
                parent_op=primary_op,
                child_ops=[
                    op for op in proc_result.operations[1:] if op.id in primary_op.child_ids
                ],
                user_id=user_id,
                execute_tool=execute_tool,
                persona_context=persona_context,
                safety_level=safety_level,
                conversation_context=conversation_context,
            )

        # Single operation - process through behavior mode pipeline
        operation = primary_op

        # Step 2: Resolve contextual references ("fix that", "do it")
        if operation.classification and self.intent_engine:
            contextual_refs = {"that", "it", "this", "those", "them"}
            words = set(user_input.lower().split())
            if words & contextual_refs and conversation_context:
                self._resolve_contextual_reference_into_classification(
                    operation, user_input, conversation_context
                )

        # Step 3: Get behavior mode from classification
        from reos.cairn.behavior_modes import BehaviorModeContext

        classification = operation.classification or Classification(
            destination=DestinationType.STREAM,
            consumer=ConsumerType.HUMAN,
            semantics=ExecutionSemantics.INTERPRET,
            confident=False,
            reasoning="no classification available",
        )
        mode = self._behavior_registry.get_mode(classification)
        logger.debug(
            "Behavior mode: %s (domain=%s, action=%s)",
            mode.name,
            classification.domain,
            classification.action_hint,
        )

        # Step 4: Set verification mode from behavior mode
        if mode.verification_mode == "FAST":
            self.verifier.set_mode(VerificationMode.FAST)
        else:
            self.verifier.set_mode(VerificationMode.STANDARD)

        # Step 5: Build verification context
        context = VerificationContext(
            user_id=user_id,
            source_agent="cairn",
            safety_level=safety_level,
            llm_available=self.intent_engine is not None,
            additional_context=conversation_context if conversation_context else None,
        )

        verification = self.verifier.verify(operation, context)

        # Step 6: Determine if approval needed
        needs_approval = self._needs_user_approval(operation, verification)

        auto_approved = False
        if not needs_approval and self.auto_approve_low_risk:
            auto_approved = True

        # Step 7: Execute through behavior mode if approved
        response = ""
        intent_result = None

        logger.debug(
            "CAIRN request: %.50s... mode=%s verification.passed=%s auto_approved=%s "
            "needs_approval=%s",
            user_input,
            mode.name,
            verification.passed,
            auto_approved,
            needs_approval,
        )

        if verification.passed and (auto_approved or not needs_approval):
            if execute_tool or not mode.needs_tool:
                # Build behavior mode context
                mode_ctx = BehaviorModeContext(
                    user_input=operation.user_request,
                    classification=classification,
                    play_data=self.intent_engine.play_data if self.intent_engine else {},
                    persona_context=persona_context,
                    conversation_context=conversation_context,
                    llm=self.intent_engine.llm if self.intent_engine else None,
                    execute_tool=execute_tool,
                )

                # Execute through behavior mode
                response, intent_result = self._execute_behavior_mode(mode, mode_ctx, operation)

                operation.execution_result = ExecutionResult(
                    success=True,
                    stdout=response,
                )
                operation.status = OperationStatus.COMPLETE
                self.processor.update_status(operation.id, OperationStatus.COMPLETE)
            else:
                response = "Operation approved but no execution engine available."
                operation.status = OperationStatus.AWAITING_APPROVAL

        elif not verification.passed:
            response = self._generate_verification_failure_response(verification)
            operation.status = OperationStatus.FAILED
            self.processor.update_status(operation.id, OperationStatus.FAILED)

        else:
            response = self._generate_approval_request(operation, verification)
            operation.status = OperationStatus.AWAITING_APPROVAL
            self.processor.update_status(operation.id, OperationStatus.AWAITING_APPROVAL)

        # Step 8: Feedback session
        self.feedback.start_session(operation)
        if needs_approval:
            self.feedback.present_for_approval(operation.id)

        if operation.status == OperationStatus.COMPLETE:
            self._last_operation_id = operation.id

        return CairnOperationResult(
            operation=operation,
            verification=verification,
            intent_result=intent_result,
            response=response,
            approved=auto_approved or (verification.passed and not needs_approval),
            needs_approval=needs_approval,
            warnings=verification.warnings,
        )

    def _execute_behavior_mode(
        self,
        mode: Any,  # BehaviorMode
        ctx: Any,  # BehaviorModeContext
        operation: AtomicOperation,
    ) -> tuple[str, Any]:
        """Execute a behavior mode: tool selection → execution → response generation.

        Returns (response_text, IntentResult_for_compat).
        """
        from reos.cairn.consciousness_stream import ConsciousnessEventType, ConsciousnessObserver
        from reos.cairn.intent_engine import (
            ExtractedIntent,
            IntentAction,
            IntentCategory,
            IntentResult,
            VerifiedIntent,
        )

        observer = ConsciousnessObserver.get_instance()
        classification = ctx.classification

        # Map domain → IntentCategory for backward compat
        cat_name = _DOMAIN_TO_INTENT_CATEGORY.get(classification.domain or "", "UNKNOWN")
        try:
            category = IntentCategory[cat_name]
        except KeyError:
            category = IntentCategory.UNKNOWN

        act_name = _ACTION_TO_INTENT_ACTION.get(classification.action_hint or "", "UNKNOWN")
        try:
            action = IntentAction[act_name]
        except KeyError:
            action = IntentAction.UNKNOWN

        # Stage 1: Emit intent extraction event
        observer.emit(
            ConsciousnessEventType.INTENT_EXTRACTED,
            f"Intent: {cat_name} → {act_name}",
            f"Domain: {classification.domain}\n"
            f"Action: {classification.action_hint}\n"
            f"Mode: {mode.name}",
            category=cat_name,
            action=act_name,
            confidence=0.9 if classification.confident else 0.5,
        )

        # Stage 2: Select tool
        tool_name = None
        tool_args: dict[str, Any] = {}
        tool_result = None

        if mode.needs_tool and ctx.execute_tool:
            tool_name = mode.tool_selector(ctx)
            if tool_name:
                tool_args = mode.arg_extractor(ctx)

                observer.emit(
                    ConsciousnessEventType.INTENT_VERIFIED,
                    f"Tool: {tool_name}",
                    f"Tool: {tool_name}\nArgs: {json.dumps(tool_args, indent=2, default=str)}",
                    verified=True,
                    tool=tool_name,
                )

                # Stage 3: Execute tool
                observer.emit(
                    ConsciousnessEventType.TOOL_CALL_START,
                    f"Calling: {tool_name}",
                    f"Tool: {tool_name}\nArgs: {json.dumps(tool_args, indent=2, default=str)}",
                    tool=tool_name,
                )
                try:
                    tool_result = ctx.execute_tool(tool_name, tool_args)
                    observer.emit(
                        ConsciousnessEventType.TOOL_CALL_COMPLETE,
                        f"Tool Result: {tool_name}",
                        json.dumps(tool_result, indent=2, default=str)[:2000],
                        tool=tool_name,
                        success=not (tool_result or {}).get("error"),
                    )

                    # Recovery on tool error
                    if tool_result and tool_result.get("error"):
                        recovery = self._attempt_tool_recovery(
                            tool_name,
                            tool_result.get("error", ""),
                            ctx,
                            category,
                        )
                        if recovery:
                            tool_result = recovery
                except Exception as e:
                    logger.warning("Tool execution error: %s", e)
                    tool_result = {"error": str(e)}

        # Stage 4: Generate response
        observer.emit(
            ConsciousnessEventType.PHASE_START,
            "Response Generation",
            "Generating response from data...",
        )

        response = self._generate_mode_response(
            mode,
            ctx,
            category,
            action,
            tool_result,
            tool_name,
        )

        observer.emit(
            ConsciousnessEventType.RESPONSE_READY,
            "Response Ready",
            f"Response ({len(response)} chars)",
            response_length=len(response),
        )

        # Build IntentResult for backward compat with agent.py
        extracted = ExtractedIntent(
            category=category,
            action=action,
            target=classification.domain or "",
            raw_input=ctx.user_input,
            confidence=0.9 if classification.confident else 0.5,
            reasoning=classification.reasoning,
        )
        verified = VerifiedIntent(
            intent=extracted,
            verified=True,
            tool_name=tool_name,
            tool_args=tool_args,
            reason=f"Behavior mode: {mode.name}",
        )
        intent_result = IntentResult(
            verified_intent=verified,
            tool_result=tool_result,
            response=response,
        )

        return response, intent_result

    def _generate_mode_response(
        self,
        mode: Any,
        ctx: Any,
        category: Any,
        action: Any,
        tool_result: dict[str, Any] | None,
        tool_name: str | None,
    ) -> str:
        """Generate response using the ResponseGenerator."""
        from reos.cairn.intent_engine import IntentCategory

        rg = self._response_gen

        if not rg.llm:
            if tool_result and not tool_result.get("error"):
                return json.dumps(tool_result, indent=2, default=str)
            return "I processed your request."

        # Handle FEEDBACK domain
        if category == IntentCategory.FEEDBACK:
            return rg.handle_feedback(ctx.user_input)

        # Handle CONVERSATION domain
        if category == IntentCategory.CONVERSATION:
            return rg.handle_conversation(
                ctx.user_input, ctx.persona_context, ctx.conversation_context
            )

        # Handle PERSONAL domain
        if category == IntentCategory.PERSONAL:
            response = rg.generate_personal_response(
                ctx.user_input,
                ctx.persona_context,
                mode.system_prompt_template,
            )
            return response

        # Handle tool-based responses
        if tool_result is not None:
            response = rg.generate_from_tool_result(
                user_input=ctx.user_input,
                tool_result=tool_result,
                system_prompt=mode.system_prompt_template,
                conversation_context=ctx.conversation_context,
            )

            # Hallucination check
            if mode.needs_hallucination_check:
                is_valid, reason = rg.verify_no_hallucination(
                    response=response,
                    tool_result=tool_result,
                    domain=ctx.classification.domain or "",
                )
                if not is_valid:
                    logger.warning("Hallucination detected: %s", reason)
                    domain = ctx.classification.domain or ""
                    action_hint = ctx.classification.action_hint or "view"

                    if category == IntentCategory.PLAY and ctx.execute_tool:
                        recovery = rg.recover_with_clarification(
                            user_input=ctx.user_input,
                            domain=domain,
                            action=action_hint,
                            rejection_reason=reason,
                            execute_tool=ctx.execute_tool,
                        )
                        if recovery:
                            return recovery

                    return rg.ask_for_clarification(
                        user_input=ctx.user_input,
                        domain=domain,
                        action=action_hint,
                        rejection_reason=reason,
                    )

            # Repetition check
            if rg.is_response_repetitive(response):
                response = (
                    "I realize I may be covering similar ground. "
                    "Is there something specific you'd like me to focus on?"
                )

            rg.track_response(response)
            return response

        # No tool result and no special domain
        return "I'm not sure how to help with that. Could you rephrase?"

    def _attempt_tool_recovery(
        self,
        tool_name: str,
        error: str,
        ctx: Any,
        category: Any,
    ) -> dict[str, Any] | None:
        """Attempt to recover from a tool failure."""

        if tool_name == "cairn_move_beat_to_act" and "not found" in error.lower():
            try:
                beats_result = ctx.execute_tool("cairn_list_beats", {})
                if beats_result and not beats_result.get("error"):
                    return {
                        "recovery": True,
                        "action": "search_beats",
                        "beats": beats_result,
                        "original_error": error,
                    }
            except Exception as e:
                logger.warning("Recovery failed: %s", e)
        return None

    def approve_operation(
        self,
        operation_id: str,
        modified: bool = False,
        execute_tool: Callable | None = None,
        persona_context: str = "",
    ) -> CairnOperationResult:
        """Approve a pending operation and execute it."""
        operation = self.processor.get_operation(operation_id)
        if not operation:
            return CairnOperationResult(
                operation=AtomicOperation(),
                verification=PipelineResult(
                    passed=False,
                    status=OperationStatus.FAILED,
                    results={},
                ),
                response="Operation not found.",
            )

        self.feedback.collect_approval(
            operation=operation,
            approved=True,
            modified=modified,
        )

        response = ""
        if self.intent_engine and execute_tool:
            # Use behavior mode for approved operations too
            from reos.cairn.behavior_modes import BehaviorModeContext

            classification = operation.classification or Classification(
                destination=DestinationType.STREAM,
                consumer=ConsumerType.HUMAN,
                semantics=ExecutionSemantics.INTERPRET,
            )
            mode = self._behavior_registry.get_mode(classification)
            mode_ctx = BehaviorModeContext(
                user_input=operation.user_request,
                classification=classification,
                play_data=self.intent_engine.play_data if self.intent_engine else {},
                persona_context=persona_context,
                llm=self.intent_engine.llm if self.intent_engine else None,
                execute_tool=execute_tool,
            )
            response, _ = self._execute_behavior_mode(mode, mode_ctx, operation)
            operation.status = OperationStatus.COMPLETE
        else:
            response = "Approved but execution not available."

        self.processor.update_status(operation.id, operation.status)
        self._last_operation_id = operation.id

        return CairnOperationResult(
            operation=operation,
            verification=PipelineResult(
                passed=True,
                status=OperationStatus.COMPLETE,
                results={},
            ),
            response=response,
            approved=True,
        )

    def reject_operation(self, operation_id: str, reason: str = "") -> bool:
        """Reject a pending operation."""
        operation = self.processor.get_operation(operation_id)
        if not operation:
            return False

        self.feedback.collect_approval(operation=operation, approved=False)
        operation.status = OperationStatus.FAILED
        self.processor.update_status(operation.id, OperationStatus.FAILED)
        return True

    def record_user_correction(
        self,
        operation_id: str,
        corrected_destination: DestinationType | None = None,
        corrected_consumer: ConsumerType | None = None,
        corrected_semantics: ExecutionSemantics | None = None,
        reasoning: str | None = None,
    ) -> bool:
        """Record user correction for classification."""
        operation = self.processor.get_operation(operation_id)
        if not operation:
            return False

        self.feedback.collect_correction(
            operation=operation,
            corrected_destination=corrected_destination,
            corrected_consumer=corrected_consumer,
            corrected_semantics=corrected_semantics,
            reasoning=reasoning,
        )
        return True

    def get_last_operation_id(self) -> str | None:
        """Get the ID of the last completed operation."""
        return self._last_operation_id

    def _process_decomposed(
        self,
        parent_op: AtomicOperation,
        child_ops: list[AtomicOperation],
        user_id: str,
        execute_tool: Callable | None,
        persona_context: str,
        safety_level: str,
        conversation_context: str,
    ) -> CairnOperationResult:
        """Process decomposed operations (e.g., "X and Y scenes")."""
        from reos.cairn.behavior_modes import BehaviorModeContext

        all_responses = []
        all_intent_results = []
        any_failed = False

        for child_op in child_ops:
            logger.debug("Processing child: %.50s", child_op.user_request)

            classification = child_op.classification or Classification(
                destination=DestinationType.STREAM,
                consumer=ConsumerType.HUMAN,
                semantics=ExecutionSemantics.INTERPRET,
            )
            mode = self._behavior_registry.get_mode(classification)

            context = VerificationContext(
                user_id=user_id,
                source_agent="cairn",
                safety_level=safety_level,
                llm_available=self.intent_engine is not None,
                additional_context=conversation_context,
            )

            verification = self.verifier.verify(child_op, context)

            if verification.passed and (execute_tool or not mode.needs_tool):
                mode_ctx = BehaviorModeContext(
                    user_input=child_op.user_request,
                    classification=classification,
                    play_data=self.intent_engine.play_data if self.intent_engine else {},
                    persona_context=persona_context,
                    conversation_context=conversation_context,
                    llm=self.intent_engine.llm if self.intent_engine else None,
                    execute_tool=execute_tool,
                )
                resp, ir = self._execute_behavior_mode(mode, mode_ctx, child_op)
                all_responses.append(resp)
                all_intent_results.append(ir)
                child_op.status = OperationStatus.COMPLETE
            else:
                any_failed = True
                all_responses.append(f"Could not process: {child_op.user_request}")

        combined_response = (
            "\n\n".join(all_responses) if all_responses else "No operations completed."
        )
        primary_intent = all_intent_results[0] if all_intent_results else None

        return CairnOperationResult(
            operation=parent_op,
            verification=PipelineResult(
                passed=not any_failed,
                status=OperationStatus.COMPLETE if not any_failed else OperationStatus.FAILED,
                results={},
                warnings=[],
            ),
            intent_result=primary_intent,
            response=combined_response,
            approved=True,
            needs_approval=False,
        )

    def _resolve_contextual_reference_into_classification(
        self,
        operation: AtomicOperation,
        user_input: str,
        conversation_context: str,
    ) -> None:
        """Resolve contextual references ("fix that") into classification domain/action."""
        if not self.intent_engine or not self.intent_engine.llm:
            return

        system = """You are an INTENT RESOLVER. The user said something with a contextual reference
like "fix that", "do it", "show me that". Given the conversation context, determine:

1. What does "that/it/this" refer to?
2. What domain? (calendar, play, system, personal, tasks, contacts)
3. What action? (view, create, update, delete, search)

Return ONLY a JSON object:
{"domain": "play", "action_hint": "update", "resolved_subject": "what the user is referring to"}

If you can't determine, return: {"domain": null, "action_hint": null}"""

        user = f"""RECENT CONVERSATION:
{conversation_context[-2000:]}

USER NOW SAYS: {user_input}

What is the user referring to and what do they want to do?"""

        try:
            raw = self.intent_engine.llm.chat_json(
                system=system, user=user, temperature=0.1, top_p=0.9
            )
            data = json.loads(raw)
            if data.get("domain") and operation.classification:
                operation.classification.domain = data["domain"]
                if data.get("action_hint"):
                    operation.classification.action_hint = data["action_hint"]
                logger.debug(
                    "Resolved contextual ref: domain=%s, action=%s",
                    data.get("domain"),
                    data.get("action_hint"),
                )
        except Exception as e:
            logger.debug("Failed to resolve contextual ref: %s", e)

    def _needs_user_approval(
        self,
        operation: AtomicOperation,
        verification: PipelineResult,
    ) -> bool:
        """Determine if operation needs explicit user approval."""
        if not verification.passed:
            return False

        if operation.classification:
            semantics = operation.classification.semantics
            destination = operation.classification.destination
            consumer = operation.classification.consumer
            confident = operation.classification.confident

            is_low_risk = (
                semantics in (ExecutionSemantics.READ, ExecutionSemantics.INTERPRET)
                and destination == DestinationType.STREAM
                and consumer == ConsumerType.HUMAN
            )

            if is_low_risk:
                return not confident

            if semantics == ExecutionSemantics.EXECUTE:
                if destination in (DestinationType.FILE, DestinationType.PROCESS):
                    return True

            if verification.warnings:
                safety_keywords = [
                    "destructive",
                    "dangerous",
                    "safety",
                    "security",
                    "execute",
                    "delete",
                    "remove",
                    "kill",
                    "process",
                ]
                for warning in verification.warnings:
                    if any(kw in warning.lower() for kw in safety_keywords):
                        return True

            if not confident:
                return True

        return False

    def _generate_verification_failure_response(
        self,
        verification: PipelineResult,
    ) -> str:
        """Generate response explaining verification failure."""
        if verification.blocking_layer:
            layer = verification.blocking_layer
            return f"I can't perform that operation. {layer} verification failed."
        if verification.warnings:
            return "I can't perform that operation: " + "; ".join(verification.warnings[:3])
        return "I can't perform that operation due to safety checks."

    def _generate_approval_request(
        self,
        operation: AtomicOperation,
        verification: PipelineResult,
    ) -> str:
        """Generate message requesting user approval."""
        parts = ["I'd like to confirm before proceeding:"]
        parts.append(f"\nRequest: {operation.user_request}")

        if operation.classification:
            action_type = operation.classification.semantics.value
            target_type = operation.classification.destination.value
            parts.append(f"This will {action_type} data ({target_type}).")

        if verification.warnings:
            parts.append("\nNotes:")
            for w in verification.warnings[:3]:
                parts.append(f"  - {w}")

        parts.append("\nShall I proceed? (yes/no)")
        return "\n".join(parts)


def create_cairn_bridge(
    conn: sqlite3.Connection,
    intent_engine: CairnIntentEngine | None = None,
) -> CairnAtomicBridge:
    """Create a CAIRN atomic bridge with default configuration."""
    return CairnAtomicBridge(
        conn=conn,
        intent_engine=intent_engine,
        verification_mode=VerificationMode.STANDARD,
        auto_approve_low_risk=True,
    )
