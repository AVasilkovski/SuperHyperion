# SuperHyperion

**Multi-Agent Self-Reflecting Scientific Intelligence System**

A system that ingests scientific papers, extracts knowledge into a TypeDB Hypergraph, and uses CodeAct agents to perform Socratic verification of claims.

## Core Philosophy
> **Glass-Box Reasoning over Black-Box Generation**
> 
> SuperHyperion enacts a **Dual-Lane Epistemic Architecture**:
> 1. **Grounded Lane**: Validated facts, strict schema, immune to hallucination.
> 2. **Speculative Lane**: Creative hypothesis generation, isolated by an **Epistemic Firewall**.

## Tech Stack
| Component | Service |
|-----------|---------|
| Knowledge Graph | **TypeDB** (Polymorphic Epistemic Store) |
| Vector Store | Azure Cosmos DB MongoDB vCore |
| LLM | Ollama (local) |
| Orchestration | **LangGraph** (State Machine) |
| Verification | **Monte Carlo Methods** (Bootstrap/Sensitivity Analysis) |

## Agent Roles
- **OntologySteward** - Use-Case Authority & Epistemic Gatekeeper. Mints `WriteCap` tokens.
- **VerifyAgent** - Performs "Feynman Checks" (Unit Consistency, Diagnostics, Sensitivity).
- **SpeculativeAgent** - Generates hypotheses in the isolated lane.
- **SocraticCritic** - Challenges claims using Scientific Uncertainty metrics.
- **IngestionAgent** - Parses PDFs, extracts claims, pushes to TypeDB.

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
