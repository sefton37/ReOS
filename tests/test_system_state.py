"""Tests for system state and certainty modules."""

import pytest
from datetime import datetime

from reos.system_state import (
    SteadyState,
    SteadyStateCollector,
    DiskInfo,
    NetworkInterface,
    UserInfo,
)
from trcore.certainty import (
    CertaintyWrapper,
    CertainResponse,
    Evidence,
    EvidenceType,
    Fact,
    Uncertainty,
    UncertaintyReason,
    create_certainty_prompt_addition,
)


class TestSteadyState:
    """Tests for SteadyState dataclass."""

    def test_steady_state_creation(self):
        """Test creating a SteadyState instance."""
        state = SteadyState(
            collected_at=datetime.now(),
            collection_duration_ms=100,
            hostname="testhost",
            domain=None,
            machine_id="abc123",
            os_name="Ubuntu",
            os_version="24.04",
            os_codename="noble",
            os_pretty_name="Ubuntu 24.04 LTS",
            kernel_version="6.8.0",
            arch="x86_64",
            cpu_model="Test CPU",
            cpu_cores=4,
            cpu_threads=8,
            memory_total_gb=16.0,
            package_manager="apt",
            installed_packages_count=1000,
        )
        assert state.hostname == "testhost"
        assert state.os_name == "Ubuntu"
        assert state.cpu_cores == 4

    def test_steady_state_to_dict(self):
        """Test serialization to dictionary."""
        state = SteadyState(
            collected_at=datetime(2024, 1, 15, 10, 30),
            collection_duration_ms=100,
            hostname="testhost",
            domain="local",
            machine_id="abc123",
            os_name="Ubuntu",
            os_version="24.04",
            os_codename="noble",
            os_pretty_name="Ubuntu 24.04 LTS",
            kernel_version="6.8.0",
            arch="x86_64",
            cpu_model="Test CPU",
            cpu_cores=4,
            cpu_threads=8,
            memory_total_gb=16.0,
            package_manager="apt",
            installed_packages_count=1000,
        )
        d = state.to_dict()
        assert d["hostname"] == "testhost"
        assert d["os_name"] == "Ubuntu"
        assert d["domain"] == "local"

    def test_steady_state_to_context_string(self):
        """Test formatting for LLM context."""
        state = SteadyState(
            collected_at=datetime(2024, 1, 15, 10, 30),
            collection_duration_ms=100,
            hostname="testhost",
            domain=None,
            machine_id="abc123",
            os_name="Ubuntu",
            os_version="24.04",
            os_codename="noble",
            os_pretty_name="Ubuntu 24.04 LTS",
            kernel_version="6.8.0",
            arch="x86_64",
            cpu_model="Test CPU",
            cpu_cores=4,
            cpu_threads=8,
            memory_total_gb=16.0,
            package_manager="apt",
            installed_packages_count=1000,
            docker_installed=True,
            docker_version="24.0.7",
        )
        context = state.to_context_string()
        assert "SYSTEM STATE" in context
        assert "testhost" in context
        assert "Ubuntu 24.04 LTS" in context
        assert "Docker: installed" in context


class TestSteadyStateCollector:
    """Tests for SteadyStateCollector."""

    def test_collector_collects_data(self):
        """Test that collector gathers system information."""
        collector = SteadyStateCollector()
        state = collector.collect()

        assert state is not None
        assert state.hostname != ""
        assert state.os_name != ""
        assert state.kernel_version != ""
        assert state.cpu_cores > 0
        assert state.memory_total_gb > 0

    def test_collector_caches_state(self):
        """Test that collector caches the state."""
        collector = SteadyStateCollector()
        state1 = collector.current
        state2 = collector.current

        # Should be the same object (cached)
        assert state1 is state2

    def test_collector_refresh_if_stale(self):
        """Test stale refresh logic."""
        collector = SteadyStateCollector()
        state1 = collector.collect()

        # Immediate refresh should return cached
        state2 = collector.refresh_if_stale(max_age_seconds=3600)
        assert state1 is state2


class TestCertaintyWrapper:
    """Tests for CertaintyWrapper."""

    def test_wrap_response_basic(self):
        """Test basic response wrapping."""
        wrapper = CertaintyWrapper()
        response = wrapper.wrap_response(
            response="The system is running Ubuntu.",
            system_state=None,
            tool_outputs=[],
            user_input="What OS am I running?",
        )
        assert isinstance(response, CertainResponse)
        assert response.answer == "The system is running Ubuntu."

    def test_wrap_response_with_system_state(self):
        """Test response wrapping with system state evidence."""
        wrapper = CertaintyWrapper()

        # Create mock system state
        class MockState:
            hostname = "testhost"
            os_name = "ubuntu"
            os_pretty_name = "Ubuntu 24.04"
            kernel_version = "6.8.0"
            docker_installed = True
            docker_version = "24.0.7"
            memory_total_gb = 16.0
            collected_at = datetime.now()

        response = wrapper.wrap_response(
            response="The hostname is testhost and Docker is installed.",
            system_state=MockState(),
            tool_outputs=[],
            user_input="What is my hostname?",
        )
        assert response.overall_confidence > 0

    def test_wrap_response_with_tool_output(self):
        """Test response wrapping with tool output evidence."""
        wrapper = CertaintyWrapper()

        tool_outputs = [
            {
                "tool": "linux_containers",
                "result": {
                    "all": [
                        {"name": "nginx", "status": "running"},
                    ]
                },
                "timestamp": datetime.now().isoformat(),
            }
        ]

        response = wrapper.wrap_response(
            response="The nginx container is running.",
            system_state=None,
            tool_outputs=tool_outputs,
            user_input="Is nginx running?",
        )
        assert response.overall_confidence > 0


class TestEvidence:
    """Tests for Evidence dataclass."""

    def test_evidence_creation(self):
        """Test creating evidence."""
        evidence = Evidence(
            evidence_type=EvidenceType.SYSTEM_STATE,
            source="SteadyState.hostname",
            value="testhost",
            timestamp=datetime.now(),
            confidence=0.95,
        )
        assert evidence.evidence_type == EvidenceType.SYSTEM_STATE
        assert evidence.source == "SteadyState.hostname"

    def test_evidence_to_dict(self):
        """Test evidence serialization."""
        evidence = Evidence(
            evidence_type=EvidenceType.TOOL_OUTPUT,
            source="linux_containers",
            value={"name": "nginx"},
        )
        d = evidence.to_dict()
        assert d["type"] == "tool_output"
        assert d["source"] == "linux_containers"


class TestCertaintyPrompt:
    """Tests for certainty prompt generation."""

    def test_create_certainty_prompt(self):
        """Test certainty prompt creation."""
        context = "Hostname: testhost\nOS: Ubuntu"
        prompt = create_certainty_prompt_addition(context)

        assert "CERTAINTY RULES" in prompt
        assert "Hostname: testhost" in prompt
        assert "NEVER guess" in prompt


class TestUncertainty:
    """Tests for Uncertainty handling."""

    def test_uncertainty_creation(self):
        """Test creating uncertainty."""
        uncertainty = Uncertainty(
            claim="The service is running",
            reason=UncertaintyReason.NO_DATA,
            suggestion="Run linux_service_status to verify",
            confidence=0.3,
        )
        assert uncertainty.reason == UncertaintyReason.NO_DATA
        assert uncertainty.suggestion is not None

    def test_certain_response_has_uncertainties(self):
        """Test uncertainty detection in response."""
        response = CertainResponse(
            answer="The service might be running",
            facts=[],
            uncertainties=[
                Uncertainty(
                    claim="service is running",
                    reason=UncertaintyReason.NO_DATA,
                )
            ],
        )
        assert response.has_uncertainties() is True

    def test_certain_response_no_uncertainties(self):
        """Test response without uncertainties."""
        response = CertainResponse(
            answer="The hostname is testhost",
            facts=[
                Fact(
                    claim="hostname is testhost",
                    evidence=Evidence(
                        evidence_type=EvidenceType.SYSTEM_STATE,
                        source="SteadyState.hostname",
                        value="testhost",
                    ),
                )
            ],
            uncertainties=[],
        )
        assert response.has_uncertainties() is False
