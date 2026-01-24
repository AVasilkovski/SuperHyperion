# SuperHyperion

**Multi-Agent Self-Reflecting Scientific Intelligence System**

A system that ingests scientific papers, extracts knowledge into a TypeDB Hypergraph, and uses CodeAct agents to perform Socratic verification of claims.

## Core Philosophy
> Glass-Box Reasoning over Black-Box Generation

## Tech Stack (Free Tier)

| Component | Service |
|-----------|---------|
| Knowledge Graph | TypeDB Cloud (free tier) |
| Vector Store | Azure Cosmos DB MongoDB vCore |
| LLM | Ollama (local) |
| Orchestration | LangGraph + CodeAct |
| Backend | FastAPI |
| Frontend | Streamlit |

## Agent Roles

- **IngestionAgent** - Parses PDFs, extracts claims, pushes to TypeDB
- **SocraticCritic** - Challenges claims using Dialectical Entropy
- **BeliefMaintenanceAgent** - Runs Bayesian updates on the graph

## Getting Started

```bash
# Prerequisites: Docker, Python 3.12, Ollama

# Start local stack
docker-compose up -d

# Install dependencies
pip install -r requirements.txt

# Run the application
python -m uvicorn app.main:app --reload
```

## Project Structure

```
SuperHyperion/
├── architecture_manifest.xml  # System design blueprint
├── docker-compose.yml         # Local development stack
├── src/                       # Source code
│   ├── agents/               # CodeAct agents
│   ├── graph/                # TypeDB integration
│   └── api/                  # FastAPI backend
└── frontend/                 # Streamlit app
```

## License

MIT
