"""CAIRN Integration with Atomic Operations.

This module integrates CAIRN (the Attention Minder) with the V2 atomic
operations architecture. Every CAIRN request flows through:

1. Classification - Request classified by 3x2x3 taxonomy
2. Verification - 5-layer verification pipeline
3. Execution - Safe execution with state capture
4. Feedback - RLHF feedback collection

CAIRN generates atomic operations that are primarily:
- Destination: stream (display info) or file (Play operations)
- Consumer: human (CAIRN serves the user directly)
- Semantics: read (queries) or execute (Play CRUD)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

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
from .feedback import FeedbackCollector

if TYPE_CHECKING:
    from reos.cairn.intent_engine import CairnIntentEngine, IntentResult


@dataclass
class CairnOperationResult:
    """Result of processing a CAIRN operation through atomic ops pipeline."""
    operation: AtomicOperation
    verification: PipelineResult
    intent_result: Optional[Any] = None  # IntentResult from CAIRN
    response: str = ""
    approved: bool = False
    needs_approval: bool = False
    warnings: list[str] = field(default_factory=list)


# Mapping from CAIRN intent categories to atomic operation classification
INTENT_TO_CLASSIFICATION = {
    # Calendar operations - read from stream
    "CALENDAR": Classification(
        destination=DestinationType.STREAM,
        consumer=ConsumerType.HUMAN,
        semantics=ExecutionSemantics.READ,
        confidence=0.9,
    ),
    # Contact operations - read from stream
    "CONTACTS": Classification(
        destination=DestinationType.STREAM,
        consumer=ConsumerType.HUMAN,
        semantics=ExecutionSemantics.READ,
        confidence=0.9,
    ),
    # System operations - may execute processes
    "SYSTEM": Classification(
        destination=DestinationType.PROCESS,
        consumer=ConsumerType.MACHINE,
        semantics=ExecutionSemantics.EXECUTE,
        confidence=0.85,
    ),
    # Tasks - read/execute on files
    "TASKS": Classification(
        destination=DestinationType.FILE,
        consumer=ConsumerType.HUMAN,
        semantics=ExecutionSemantics.READ,
        confidence=0.85,
    ),
    # Knowledge queries - read from files
    "KNOWLEDGE": Classification(
        destination=DestinationType.FILE,
        consumer=ConsumerType.HUMAN,
        semantics=ExecutionSemantics.READ,
        confidence=0.85,
    ),
    # Personal questions - interpret from knowledge
    "PERSONAL": Classification(
        destination=DestinationType.STREAM,
        consumer=ConsumerType.HUMAN,
        semantics=ExecutionSemantics.INTERPRET,
        confidence=0.9,
    ),
    # Play operations - file-based CRUD
    "PLAY": Classification(
        destination=DestinationType.FILE,
        consumer=ConsumerType.HUMAN,
        semantics=ExecutionSemantics.EXECUTE,
        confidence=0.85,
    ),
    # Undo operations - execute reversal
    "UNDO": Classification(
        destination=DestinationType.FILE,
        consumer=ConsumerType.HUMAN,
        semantics=ExecutionSemantics.EXECUTE,
        confidence=0.9,
    ),
}

# Refinements based on action
ACTION_REFINEMENTS = {
    # VIEW actions are reads
    "VIEW": ExecutionSemantics.READ,
    "SEARCH": ExecutionSemantics.READ,
    "STATUS": ExecutionSemantics.READ,
    # Mutations are executes
    "CREATE": ExecutionSemantics.EXECUTE,
    "UPDATE": ExecutionSemantics.EXECUTE,
    "DELETE": ExecutionSemantics.EXECUTE,
}


class CairnAtomicBridge:
    """Bridge between CAIRN and the atomic operations pipeline.

    This class wraps CAIRN's intent engine and routes all operations
    through the atomic ops classification, verification, and feedback
    systems.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        intent_engine: Optional["CairnIntentEngine"] = None,
        verification_mode: VerificationMode = VerificationMode.STANDARD,
        auto_approve_low_risk: bool = True,
    ):
        """Initialize the CAIRN atomic bridge.

        Args:
            conn: Database connection for atomic ops storage.
            intent_engine: Optional CAIRN intent engine instance.
            verification_mode: Verification pipeline mode.
            auto_approve_low_risk: Auto-approve read-only operations.
        """
        # Extract LLM from intent engine for semantic decomposition
        llm = intent_engine.llm if intent_engine else None

        self.processor = AtomicOpsProcessor(conn, auto_init_embeddings=True, llm=llm)
        self.verifier = VerificationPipeline(mode=verification_mode)
        self.feedback = FeedbackCollector(self.processor.store)
        self.intent_engine = intent_engine
        self.auto_approve_low_risk = auto_approve_low_risk

        # Track last operation for undo
        self._last_operation_id: Optional[str] = None

    def set_intent_engine(self, engine: "CairnIntentEngine"):
        """Set the CAIRN intent engine."""
        self.intent_engine = engine

    def process_request(
        self,
        user_input: str,
        user_id: str,
        execute_tool: Optional[Callable] = None,
        persona_context: str = "",
        safety_level: str = "standard",
        conversation_context: str = "",
    ) -> CairnOperationResult:
        """Process a user request through the full atomic ops pipeline.

        This is the main entry point for CAIRN operations. It:
        1. Creates an atomic operation from the request
        2. Decomposes if needed ("X and Y" → two operations)
        3. Classifies using CAIRN's intent engine + atomic ops classifier
        4. Verifies through the 5-layer pipeline
        5. Executes if approved (or auto-approved for low-risk)
        6. Collects feedback

        Args:
            user_input: User's natural language request.
            user_id: User identifier.
            execute_tool: Function to execute MCP tools.
            persona_context: Context about the user (from THE_PLAY).
            safety_level: Safety level (permissive, standard, strict).
            conversation_context: Recent conversation for context (helps "fix that").

        Returns:
            CairnOperationResult with operation, verification, and response.
        """
        import sys

        # Step 1: Process through atomic ops pipeline (includes decomposition)
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
        decomp_result = self.processor.decomposer.decompose(
            request=user_input,
            user_id=user_id,
            source_agent="cairn",
        )
        if decomp_result.needs_clarification and decomp_result.clarification_prompt:
            # Return clarification request instead of proceeding with uncertain decomposition
            return CairnOperationResult(
                operation=AtomicOperation(user_request=user_input, user_id=user_id),
                verification=PipelineResult(
                    passed=True,  # Not failed, just needs clarification
                    status=OperationStatus.AWAITING_APPROVAL,
                    results={},
                    warnings=["Clarification needed"],
                ),
                response=decomp_result.clarification_prompt,
                needs_approval=True,
            )

        # Check if request was decomposed into multiple operations
        primary_op = proc_result.operations[0]
        if primary_op.is_decomposed and primary_op.child_ids:
            print(f"[ATOMIC] Decomposed into {len(primary_op.child_ids)} operations", file=sys.stderr)
            # Process each child operation and combine results
            return self._process_decomposed(
                parent_op=primary_op,
                child_ops=[op for op in proc_result.operations[1:] if op.id in primary_op.child_ids],
                user_id=user_id,
                execute_tool=execute_tool,
                persona_context=persona_context,
                safety_level=safety_level,
                conversation_context=conversation_context,
            )

        # Single operation - process normally
        operation = primary_op

        # Step 2: Enhance classification with CAIRN intent if available
        # Pass conversation context so intent engine understands "fix that", etc.
        if self.intent_engine:
            operation = self._enhance_with_intent(
                operation, user_input, conversation_context=conversation_context
            )

        # Step 3: Build verification context with conversation history
        context = VerificationContext(
            user_id=user_id,
            source_agent="cairn",
            safety_level=safety_level,
            llm_available=self.intent_engine is not None,
            additional_context=conversation_context if conversation_context else None,
        )

        # Step 4: Run verification pipeline
        verification = self.verifier.verify(operation, context)

        # Step 5: Determine if approval needed
        needs_approval = self._needs_user_approval(operation, verification)

        # Auto-approve low-risk operations if enabled
        auto_approved = False
        if not needs_approval and self.auto_approve_low_risk:
            auto_approved = True

        # Step 6: Execute if approved
        response = ""
        intent_result = None

        if verification.passed and (auto_approved or not needs_approval):
            # Execute through CAIRN intent engine
            if self.intent_engine and execute_tool:
                intent_result = self.intent_engine.process(
                    user_input=operation.user_request,  # Use operation's request (may be sub-request)
                    execute_tool=execute_tool,
                    persona_context=persona_context,
                )
                response = intent_result.response

                # Update operation with execution result
                operation.execution_result = ExecutionResult(
                    success=True,
                    stdout=response,
                )
                operation.status = OperationStatus.COMPLETE

                # Store execution
                self.processor.update_status(operation.id, OperationStatus.COMPLETE)
            else:
                response = "Operation approved but no execution engine available."
                operation.status = OperationStatus.AWAITING_APPROVAL

        elif not verification.passed:
            # Verification failed
            response = self._generate_verification_failure_response(verification)
            operation.status = OperationStatus.FAILED
            self.processor.update_status(operation.id, OperationStatus.FAILED)

        else:
            # Needs approval
            response = self._generate_approval_request(operation, verification)
            operation.status = OperationStatus.AWAITING_APPROVAL
            self.processor.update_status(operation.id, OperationStatus.AWAITING_APPROVAL)

        # Step 7: Start feedback session
        self.feedback.start_session(operation)
        if needs_approval:
            self.feedback.present_for_approval(operation.id)

        # Track for undo
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

    def approve_operation(
        self,
        operation_id: str,
        modified: bool = False,
        execute_tool: Optional[Callable] = None,
        persona_context: str = "",
    ) -> CairnOperationResult:
        """Approve a pending operation and execute it.

        Args:
            operation_id: ID of operation to approve.
            modified: Whether user modified the operation.
            execute_tool: Function to execute MCP tools.
            persona_context: Context about the user.

        Returns:
            CairnOperationResult with execution result.
        """
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

        # Collect approval feedback
        self.feedback.collect_approval(
            operation=operation,
            approved=True,
            modified=modified,
        )

        # Execute
        response = ""
        if self.intent_engine and execute_tool:
            intent_result = self.intent_engine.process(
                user_input=operation.user_request,
                execute_tool=execute_tool,
                persona_context=persona_context,
            )
            response = intent_result.response
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
        """Reject a pending operation.

        Args:
            operation_id: ID of operation to reject.
            reason: Optional rejection reason.

        Returns:
            True if rejection recorded.
        """
        operation = self.processor.get_operation(operation_id)
        if not operation:
            return False

        # Collect rejection feedback
        self.feedback.collect_approval(
            operation=operation,
            approved=False,
        )

        operation.status = OperationStatus.FAILED
        self.processor.update_status(operation.id, OperationStatus.FAILED)

        return True

    def record_user_rating(
        self,
        operation_id: str,
        rating: int,
        comment: Optional[str] = None,
    ) -> bool:
        """Record user rating for an operation.

        Args:
            operation_id: ID of operation to rate.
            rating: Rating 1-5.
            comment: Optional comment.

        Returns:
            True if rating recorded.
        """
        operation = self.processor.get_operation(operation_id)
        if not operation:
            return False

        self.feedback.collect_rating(
            operation=operation,
            rating=rating,
            comment=comment,
        )

        return True

    def record_user_correction(
        self,
        operation_id: str,
        corrected_destination: Optional[DestinationType] = None,
        corrected_consumer: Optional[ConsumerType] = None,
        corrected_semantics: Optional[ExecutionSemantics] = None,
        reasoning: Optional[str] = None,
    ) -> bool:
        """Record user correction for classification.

        Args:
            operation_id: ID of operation to correct.
            corrected_*: Corrected classification values.
            reasoning: User's reasoning.

        Returns:
            True if correction recorded.
        """
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

    def get_last_operation_id(self) -> Optional[str]:
        """Get the ID of the last completed operation."""
        return self._last_operation_id

    def _process_decomposed(
        self,
        parent_op: AtomicOperation,
        child_ops: list[AtomicOperation],
        user_id: str,
        execute_tool: Optional[Callable],
        persona_context: str,
        safety_level: str,
        conversation_context: str,
    ) -> CairnOperationResult:
        """Process decomposed operations (e.g., "X and Y scenes").

        Each child operation is processed through the full pipeline
        and results are combined.
        """
        import sys

        all_responses = []
        all_intent_results = []
        any_failed = False

        for child_op in child_ops:
            print(f"[ATOMIC] Processing child: {child_op.user_request[:50]!r}", file=sys.stderr)

            # Enhance with CAIRN intent
            if self.intent_engine:
                child_op = self._enhance_with_intent(
                    child_op, child_op.user_request, conversation_context=conversation_context
                )

            # Build verification context
            context = VerificationContext(
                user_id=user_id,
                source_agent="cairn",
                safety_level=safety_level,
                llm_available=self.intent_engine is not None,
                additional_context=conversation_context,
            )

            # Verify
            verification = self.verifier.verify(child_op, context)

            if verification.passed and self.intent_engine and execute_tool:
                # Execute this sub-operation
                intent_result = self.intent_engine.process(
                    user_input=child_op.user_request,
                    execute_tool=execute_tool,
                    persona_context=persona_context,
                )
                all_responses.append(intent_result.response)
                all_intent_results.append(intent_result)
                child_op.status = OperationStatus.COMPLETE
            else:
                any_failed = True
                all_responses.append(f"Could not process: {child_op.user_request}")

        # Combine responses
        combined_response = "\n\n".join(all_responses) if all_responses else "No operations completed."

        # Use first intent result as primary (for compatibility)
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

    def _enhance_with_intent(
        self,
        operation: AtomicOperation,
        user_input: str,
        conversation_context: str = "",
    ) -> AtomicOperation:
        """Enhance operation classification with CAIRN intent extraction.

        Uses conversation context to understand contextual references like "fix that".
        """
        if not self.intent_engine:
            return operation

        # Use LLM to extract intent with context (not just pattern matching)
        from reos.cairn.intent_engine import INTENT_PATTERNS

        user_lower = user_input.lower()
        detected_category = None
        detected_action = None

        # For contextual references ("fix that", "do it"), use LLM with conversation context
        contextual_refs = ["that", "it", "this", "those", "them"]
        has_contextual_ref = any(ref in user_lower.split() for ref in contextual_refs)

        if has_contextual_ref and conversation_context and self.intent_engine.llm:
            # Use LLM to resolve contextual reference
            resolved = self._resolve_contextual_reference(
                user_input, conversation_context, self.intent_engine.llm
            )
            if resolved:
                detected_category = resolved.get("category")
                detected_action = resolved.get("action")

        # Fall back to pattern matching if LLM didn't resolve
        if not detected_category:
            for category_name, patterns in INTENT_PATTERNS.items():
                for pattern in patterns:
                    if pattern in user_lower:
                        detected_category = category_name.name
                        break
                if detected_category:
                    break

        # Detect action
        if not detected_action:
            if any(w in user_lower for w in ["create", "add", "new", "make"]):
                detected_action = "CREATE"
            elif any(w in user_lower for w in ["find", "search", "look for"]):
                detected_action = "SEARCH"
            elif any(w in user_lower for w in ["update", "change", "modify", "move", "fix"]):
                detected_action = "UPDATE"
            elif any(w in user_lower for w in ["delete", "remove"]):
                detected_action = "DELETE"
            else:
                detected_action = "VIEW"

        # Get base classification from category
        if detected_category and detected_category in INTENT_TO_CLASSIFICATION:
            base_class = INTENT_TO_CLASSIFICATION[detected_category]

            # Refine semantics based on action
            semantics = base_class.semantics
            if detected_action in ACTION_REFINEMENTS:
                semantics = ACTION_REFINEMENTS[detected_action]

            # Create refined classification
            refined = Classification(
                destination=base_class.destination,
                consumer=base_class.consumer,
                semantics=semantics,
                confidence=base_class.confidence,
                reasoning={
                    "category": detected_category,
                    "action": detected_action,
                    "source": "cairn_intent",
                },
            )

            operation.classification = refined

        return operation

    def _resolve_contextual_reference(
        self,
        user_input: str,
        conversation_context: str,
        llm: Any,
    ) -> dict[str, str] | None:
        """Use LLM to resolve contextual references like "fix that".

        Given conversation context, determines what "that/it/this" refers to
        and extracts the appropriate intent category and action.
        """
        import json
        import sys

        if not conversation_context:
            return None

        system = """You are an INTENT RESOLVER. The user said something with a contextual reference
like "fix that", "do it", "show me that". Given the conversation context, determine:

1. What does "that/it/this" refer to?
2. What category of operation is this? (CALENDAR, PLAY, SYSTEM, PERSONAL, TASKS, CONTACTS)
3. What action? (VIEW, CREATE, UPDATE, DELETE, SEARCH)

IMPORTANT: If the conversation was about scenes, acts, beats, or "The Play" → category is PLAY.
If "fix" or "move" or similar action word → action is UPDATE.

Return ONLY a JSON object:
{"category": "PLAY", "action": "UPDATE", "resolved_subject": "what the user is referring to"}

If you can't determine, return: {"category": null, "action": null}"""

        user = f"""RECENT CONVERSATION:
{conversation_context[-2000:]}

USER NOW SAYS: {user_input}

What is the user referring to and what do they want to do?"""

        try:
            raw = llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)
            if data.get("category"):
                print(f"[ATOMIC] Resolved contextual ref: {data}", file=sys.stderr)
                return data
        except Exception as e:
            print(f"[ATOMIC] Failed to resolve contextual ref: {e}", file=sys.stderr)

        return None

    def _needs_user_approval(
        self,
        operation: AtomicOperation,
        verification: PipelineResult,
    ) -> bool:
        """Determine if operation needs explicit user approval."""
        # Always approve if verification failed
        if not verification.passed:
            return False  # Will be rejected, not approved

        # Check for warnings that require approval
        if verification.warnings:
            return True

        # Check classification - execute operations need approval
        if operation.classification:
            if operation.classification.semantics == ExecutionSemantics.EXECUTE:
                # File/process execute operations need approval
                if operation.classification.destination in (
                    DestinationType.FILE,
                    DestinationType.PROCESS,
                ):
                    return True

        # Low confidence needs approval
        if operation.classification and operation.classification.confidence < 0.7:
            return True

        return False

    def _generate_verification_failure_response(
        self,
        verification: PipelineResult,
    ) -> str:
        """Generate response explaining verification failure."""
        if verification.blocking_layer:
            return f"I can't perform that operation. {verification.blocking_layer} verification failed."

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
    intent_engine: Optional["CairnIntentEngine"] = None,
) -> CairnAtomicBridge:
    """Create a CAIRN atomic bridge with default configuration."""
    return CairnAtomicBridge(
        conn=conn,
        intent_engine=intent_engine,
        verification_mode=VerificationMode.STANDARD,
        auto_approve_low_risk=True,
    )
