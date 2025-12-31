# ReOS

**ReOS** is a Git-first companion intelligence system that helps you maintain alignment with your project's charter and roadmap while managing attention and context.

## Overview

ReOS observes your local Git repository and provides gentle, reflective checkpoints when your changes appear to drift from your project's goals or when you're juggling too many parallel threads. It's designed to protect your attention by observing with clarity, reflecting with compassion, and returning agency to you.

### Core Philosophy

- **Attention is sacred**: ReOS protects it through quiet observation and thoughtful reflection
- **Local-first**: All data stays on your machine (SQLite + local storage)
- **Metadata-first**: Only captures file paths and stats by default; diffs require explicit opt-in
- **Non-judgmental**: Reports signals about scope and breadth, not productivity scores
- **Transparent**: Every AI insight includes its full reasoning trail

## Key Features

- **Git Observation**: Polls local repo metadata (status, diffstat, numstat)
- **Alignment Analysis**: Compares changes against your charter and tech roadmap
- **"The Play" Model**: Organize work into Acts, Scenes, and Beats with integrated knowledge base
- **Local LLM Integration**: Uses Ollama for on-device AI reasoning
- **Desktop UI**: Three-pane Tauri app (navigation, chat, inspection)
- **Attention Metrics**: Tracks context switching and change scope signals
- **Commit Review**: Optional background analysis of committed changes

## Prerequisites

### Required

- **Python 3.11+** (3.12+ recommended)
- **Node.js 18+** and npm
- **Rust** (for building Tauri app)
- **Ollama** running locally
- **Git** repository to observe

### Platform-Specific Requirements

**Linux:**
```bash
# Ubuntu/Debian
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev

# Arch
sudo pacman -S webkit2gtk-4.1 base-devel curl wget file libappindicator-gtk3 librsvg

# Fedora
sudo dnf install webkit2gtk4.1-devel openssl-devel curl wget file libappindicator-gtk3-devel librsvg2-devel
sudo dnf group install "C Development Tools and Libraries"
```

**macOS:**
```bash
# Install Xcode Command Line Tools
xcode-select --install
```

## Installation

### 1. Install Ollama

```bash
# Linux/macOS
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama and pull a model
ollama serve &
ollama pull llama3.2:3b  # or your preferred model
```

### 2. Install ReOS Python Backend

```bash
# Clone the repository
git clone https://github.com/yourusername/ReOS.git
cd ReOS

# Install Python dependencies
pip install -e ".[dev]"
```

### 3. Build Tauri Desktop App

```bash
# Navigate to Tauri app directory
cd apps/reos-tauri

# Install Node dependencies
npm install

# Build the app (or run in dev mode)
npm run tauri build  # Production build
# OR
npm run tauri dev    # Development mode
```

## Quick Start

### 1. Configure Environment

Create a `.env` file in the project root (or set environment variables):

```bash
# Required
REOS_OLLAMA_MODEL=llama3.2:3b           # Your Ollama model
REOS_REPO_PATH=/path/to/your/repo      # Git repo to observe

# Optional (with defaults shown)
REOS_OLLAMA_URL=http://127.0.0.1:11434 # Ollama API endpoint
REOS_DATA_DIR=.reos-data               # Local data directory
REOS_DB_PATH=.reos-data/reos.db        # SQLite database path
REOS_LOG_LEVEL=INFO                    # Logging level
REOS_POLL_INTERVAL_SECONDS=30          # Git polling frequency
```

### 2. Start the Python Kernel

```bash
# From project root
python -m reos.app

# The FastAPI server will start on http://localhost:8010
# You should see: "ReOS kernel started"
```

### 3. Launch the Desktop App

```bash
# In another terminal
cd apps/reos-tauri
npm run tauri dev

# The Tauri app will launch and connect to the Python kernel
```

### 4. Start Using ReOS

1. **Navigate The Play**: Use the left pane to create Acts, Scenes, and Beats
2. **Chat**: Ask questions or request alignment reviews in the center pane
3. **Edit Knowledge Base**: Document your charter, roadmap, and constraints
4. **Inspect**: Right pane shows full reasoning trails and JSON responses

## Configuration

### Ollama Models

ReOS works with any Ollama model. Recommended options:

- **llama3.2:3b** - Fast, good for quick checks (3GB)
- **llama3.2:1b** - Very fast, lower quality (1GB)
- **qwen2.5:7b** - Better reasoning, slower (4.7GB)
- **mistral:7b** - Balanced performance (4.1GB)

Install with: `ollama pull <model-name>`

### Git Polling

Configure polling behavior via environment variables:

```bash
REOS_POLL_INTERVAL_SECONDS=30    # How often to check git status
REOS_INCLUDE_DIFFS=false         # Enable diff text (opt-in for privacy)
REOS_COMMIT_REVIEW_ENABLED=false # Background commit analysis
```

### Agent Personas

Create custom personas in the database or use the default "helpful assistant" persona. Settings UI for persona management is coming soon.

## Development

### Running Tests

```bash
# Python tests
pytest                    # Run all tests
pytest tests/test_api.py  # Run specific test file
pytest -v                 # Verbose output

# Type checking
mypy src/reos

# Linting & formatting
ruff check src tests
ruff format src tests
```

### Project Structure

```
ReOS/
├── src/reos/              # Python backend
│   ├── app.py            # FastAPI application
│   ├── db.py             # SQLite database
│   ├── git_poll.py       # Git observation
│   ├── alignment.py      # Charter/roadmap analysis
│   ├── agent.py          # LLM agent with tools
│   ├── ui_rpc_server.py  # Tauri ↔ Python RPC
│   └── ...
├── apps/reos-tauri/       # TypeScript/Tauri frontend
│   ├── src/main.ts       # UI implementation
│   ├── src-tauri/        # Rust desktop shell
│   └── ...
├── tests/                 # Python tests
├── docs/                  # Architecture & workflow docs
└── pyproject.toml         # Python project config
```

### Architecture Overview

ReOS uses a **bifocal architecture**:

1. **Git Observer** - Polls local repo, stores metadata events
2. **Attention Kernel** - FastAPI service with alignment analysis
3. **Desktop UI** - Tauri app with three-pane layout
4. **SQLite Core** - Local-only event store and audit log
5. **LLM Layer** - Ollama integration for reasoning

See [docs/M1B_ARCHITECTURE.md](docs/M1B_ARCHITECTURE.md) for details.

## Documentation

- [Architecture Overview](docs/M1B_ARCHITECTURE.md) - Core system design
- [Workflow Example](docs/WORKFLOW_EXAMPLE.md) - How ReOS works in practice
- [Tech Roadmap](docs/tech-roadmap.md) - Development milestones
- [Testing Strategy](docs/testing-strategy.md) - Testing approach
- [UI Migration Guide](docs/ui-migration-typescript.md) - PySide6 → Tauri migration

## Troubleshooting

### "No module named pytest"

```bash
pip install -e ".[dev]"
```

### "Ollama connection refused"

```bash
# Make sure Ollama is running
ollama serve

# Check the service
curl http://localhost:11434/api/version
```

### "Python version mismatch"

Ensure you have Python 3.11 or later:
```bash
python3 --version
```

### Database locked errors

Only one instance of ReOS should run per repository. Check for other running instances.

## Roadmap

- **M1** (Current): SQLite migration, desktop app, "The Play" model
- **M2** (Next): Real-time alignment checkpoints, settings UI
- **M3**: Full reasoning trails, inspection pane enhancements
- **M4**: Classification system (revolution/evolution, coherence/fragmentation)
- **M5**: Life expansion (email, browser, OS integration)

See [docs/tech-roadmap.md](docs/tech-roadmap.md) for complete roadmap.

## Contributing

ReOS is in active development. Contributions welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run `pytest` and `ruff check`
5. Submit a pull request

## License

[Add your license here]

## Acknowledgments

ReOS is built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Python web framework
- [Tauri](https://tauri.app/) - Desktop app framework
- [Ollama](https://ollama.com/) - Local LLM runtime
- [SQLite](https://www.sqlite.org/) - Local database
