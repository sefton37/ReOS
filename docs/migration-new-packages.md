# Migration Guide: New Top-Level Packages

## Why Migrate?

ReOS 0.6.0 introduces top-level packages (`llm`, `agents`, `classification`, `routing`, `verification`, `search`) that provide cleaner, more focused interfaces for the core LLM-first architecture. These packages:

- **Reduce cognitive load** — `from llm import OllamaInference` vs `from reos.providers.ollama import OllamaProvider`
- **Surface new capabilities** — Higher-level abstractions like `OllamaInference`, `BaseAgent`, `RequestRouter`
- **Align with mission** — Packages named by *what they do* (classify, route, verify) not implementation details

The old `reos.*` imports still work and have **no runtime deprecation warnings**. Migrate at your own pace.

---

## Package Mapping

### Core LLM Interface (`llm`)

| Old Import | New Import |
|------------|-----------|
| `from reos.providers import LLMProvider, OllamaProvider` | `from llm import LLMProvider, OllamaProvider` |
| `from reos.providers.factory import get_provider, get_provider_or_none` | `from llm import get_provider, get_provider_or_none` |
| `from reos.providers.factory import check_provider_health` | `from llm import check_provider_health` |
| `from reos.providers.base import LLMError, ModelInfo, ProviderHealth` | `from llm import LLMError, ModelInfo, ProviderHealth` |

### Agents (`agents`)

| Old Import | New Import |
|------------|-----------|
| `from reos.agent import ChatAgent` | `from agents import ChatAgent` |
| `from reos.cairn.intent_engine import CairnIntentEngine` | `from agents import CairnIntentEngine` |

### Classification (`classification`)

| Old Import | New Import |
|------------|-----------|
| `from reos.atomic_ops.classifier import AtomicClassifier` | `from classification import LLMClassifier` |
| `from reos.atomic_ops.models import Classification, DestinationType, ConsumerType, ExecutionSemantics` | `from classification import Classification, DestinationType, ConsumerType, ExecutionSemantics` |

### Routing (`routing`)

| Old Import | New Import |
|------------|-----------|
| `from reos.atomic_ops.processor import AtomicOpsProcessor` | `from routing import AtomicOpsProcessor` |

### Verification (`verification`)

| Old Import | New Import |
|------------|-----------|
| `from reos.atomic_ops.verifiers import VerificationPipeline, BaseVerifier` | `from verification import VerificationPipeline, BaseVerifier` |
| `from reos.atomic_ops.verifiers import SyntaxVerifier, SemanticVerifier, BehavioralVerifier, SafetyVerifier, IntentVerifier` | `from verification import SyntaxVerifier, SemanticVerifier, BehavioralVerifier, SafetyVerifier, IntentVerifier` |
| `from reos.atomic_ops.verifiers.pipeline import VerificationMode, PipelineResult` | `from verification import VerificationMode, PipelineResult` |

### Semantic Search (`search`)

| Old Import | New Import |
|------------|-----------|
| `from reos.memory.embeddings import EmbeddingService` | `from search import EmbeddingService` |

---

## New Code: Classes Only in New Packages

These are **not available** via `reos.*` imports — they exist only in the new packages:

### `llm.OllamaInference`
Higher-level inference wrapper with semantic methods:
```python
from llm import OllamaInference

inference = OllamaInference(provider)
result = inference.generate("Explain quantum computing", max_tokens=150)
category = inference.classify("Show me system logs", ["SYSTEM", "CALENDAR", "PLAY"])
```

### `agents.BaseAgent` / `agents.CAIRNAgent` / `agents.ReOSAgent`
New agent abstractions with standardized interfaces:
```python
from agents import CAIRNAgent, AgentContext

agent = CAIRNAgent()
context = AgentContext(user_id="alice", session_id="s123")
response = await agent.handle("What's next today?", context)
```

### `routing.RequestRouter`
New classify-and-dispatch router:
```python
from routing import RequestRouter

router = RequestRouter(classifier, agents)
result = await router.route("Install nginx")  # RoutingResult with agent, confidence
```

### `verification.LLMIntentVerifier`
LLM-as-judge verifier (experimental):
```python
from verification import LLMIntentVerifier

verifier = LLMIntentVerifier(inference)
judgment = await verifier.verify(user_input, command, context)
```

### `classification.ClassificationResult`
New result type with `raw_response` field for debugging:
```python
from classification import LLMClassifier

result = classifier.classify("Show calendar")
print(result.classification)  # Classification(dest=STREAM, consumer=HUMAN, ...)
print(result.raw_response)    # Raw LLM output for debugging
```

---

## What NOT to Migrate (Yet)

Provider **management functions** remain in `reos.providers` and are **not in the `llm` facade**:

```python
# Still use reos.providers for these:
from reos.providers import (
    set_provider_type,           # Change active provider
    get_current_provider_type,   # Get active provider name
    list_providers,              # List available providers
    get_provider_info,           # Get provider metadata
    ProviderInfo,                # Provider info dataclass
    AVAILABLE_PROVIDERS,         # Dict of all providers
)

from reos.providers.secrets import (
    store_api_key,               # Keyring storage
    get_api_key,                 # Keyring retrieval
    delete_api_key,              # Keyring deletion
    has_api_key,                 # Check if key exists
    check_keyring_available,     # Check keyring backend
    get_keyring_backend_name,    # Get backend name
    list_stored_providers,       # List providers with stored keys
)

from reos.providers.ollama import (
    check_ollama_installed,      # Ollama availability check
    get_ollama_install_command,  # Platform-specific install command
)
```

---

## Timeline & Deprecation

- **Now (0.6.0):** Both old and new imports work. No runtime warnings.
- **Future (0.7.0+):** Old imports may log deprecation warnings.
- **Long-term:** Old imports may redirect to new packages (no code change needed).

The old `reos.*` structure will remain functional indefinitely for backward compatibility.

---

## Migration Example

**Before:**
```python
from reos.providers import get_provider, OllamaProvider
from reos.atomic_ops.classifier import AtomicClassifier
from reos.atomic_ops.processor import AtomicOpsProcessor
from reos.atomic_ops.verifiers import VerificationPipeline
from reos.agent import ChatAgent

provider = get_provider(db)
classifier = AtomicClassifier(provider)
processor = AtomicOpsProcessor(classifier, db)
verifier = VerificationPipeline([...])
agent = ChatAgent(processor)
```

**After:**
```python
from llm import get_provider, OllamaInference
from classification import LLMClassifier
from routing import RequestRouter
from verification import VerificationPipeline
from agents import ChatAgent

provider = get_provider(db)
inference = OllamaInference(provider)  # New high-level API
classifier = LLMClassifier(inference)
router = RequestRouter(classifier, agents={...})  # New router
verifier = VerificationPipeline([...])
agent = ChatAgent(processor)
```

---

## Questions?

See [ARCHITECTURE.md](../src/reos/architecture/ARCHITECTURE.md) for system overview or ask in GitHub Discussions.
