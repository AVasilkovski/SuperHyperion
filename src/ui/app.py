"""
SuperHyperion Streamlit Dashboard

Interactive UI for the scientific reasoning system.
Features:
- Query input and submission
- Glass Box: Live execution trace
- Graph Explorer: TypeDB visualization
- HITL: Human-in-the-loop approval
"""

import streamlit as st
import httpx
import json
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import os

# Configuration
API_HOST = os.getenv("API_HOST", "localhost")
API_PORT = os.getenv("API_PORT", "8000")
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"

# Page config
st.set_page_config(
    page_title="SuperHyperion",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .glass-box {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
        backdrop-filter: blur(10px);
    }
    .thought-bubble {
        background: linear-gradient(135deg, #1e3a5f 0%, #0d1b2a 100%);
        border-left: 3px solid #4a9eff;
        padding: 10px;
        margin: 5px 0;
        border-radius: 0 8px 8px 0;
    }
    .code-block {
        background: #0d1117;
        border-left: 3px solid #2ea043;
        padding: 10px;
        font-family: 'Fira Code', monospace;
        margin: 5px 0;
        border-radius: 0 8px 8px 0;
    }
    .result-block {
        background: #0d1117;
        border-left: 3px solid #f0883e;
        padding: 10px;
        margin: 5px 0;
        border-radius: 0 8px 8px 0;
    }
    .debate-block {
        background: linear-gradient(135deg, #3d1a4e 0%, #1a0d1f 100%);
        border-left: 3px solid #a855f7;
        padding: 10px;
        margin: 5px 0;
        border-radius: 0 8px 8px 0;
    }
    .entropy-high {
        color: #ef4444;
        font-weight: bold;
    }
    .entropy-medium {
        color: #f59e0b;
    }
    .entropy-low {
        color: #22c55e;
    }
    .stButton > button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)


# ============================================
# Session State Initialization
# ============================================

if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_job_id" not in st.session_state:
    st.session_state.current_job_id = None
if "execution_trace" not in st.session_state:
    st.session_state.execution_trace = []
if "pending_hypotheses" not in st.session_state:
    st.session_state.pending_hypotheses = []


# ============================================
# API Helper Functions
# ============================================

def submit_query(query: str) -> Optional[str]:
    """Submit a query to the API and return job_id."""
    try:
        response = httpx.post(
            f"{API_BASE_URL}/query",
            json={"query": query},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("job_id")
    except Exception as e:
        st.error(f"Failed to submit query: {e}")
        return None


def get_job_status(job_id: str) -> Optional[Dict]:
    """Get status of a job."""
    try:
        response = httpx.get(
            f"{API_BASE_URL}/status/{job_id}",
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to get job status: {e}")
        return None


def get_recent_jobs() -> List[Dict]:
    """Get list of recent jobs."""
    try:
        response = httpx.get(
            f"{API_BASE_URL}/jobs",
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except:
        return []


# ============================================
# UI Components
# ============================================

def render_glass_box():
    """Render the Glass Box execution trace in sidebar."""
    st.sidebar.markdown("## 🔍 Glass Box")
    st.sidebar.markdown("*Live execution trace*")
    
    if not st.session_state.execution_trace:
        st.sidebar.info("Submit a query to see the reasoning trace")
        return
    
    for i, trace in enumerate(st.session_state.execution_trace):
        trace_type = trace.get("type", "thought")
        content = trace.get("content", "")
        
        if trace_type == "thought":
            with st.sidebar.expander(f"💭 Thought {i+1}", expanded=i >= len(st.session_state.execution_trace) - 2):
                st.markdown(content[:500])
        elif trace_type == "code":
            with st.sidebar.expander(f"🐍 Code {i+1}", expanded=False):
                st.code(content, language="python")
        elif trace_type == "result":
            with st.sidebar.expander(f"📊 Result {i+1}", expanded=True):
                st.text(content[:300])
        elif trace_type == "critique":
            with st.sidebar.expander(f"⚖️ Critique", expanded=True):
                st.markdown(content[:400])
        elif trace_type == "debate":
            with st.sidebar.expander(f"🗣️ Debate", expanded=True):
                st.markdown(content[:500])


def render_entropy_gauge(entropy: float):
    """Render dialectical entropy gauge."""
    if entropy > 0.6:
        css_class = "entropy-high"
        label = "High Uncertainty"
    elif entropy > 0.4:
        css_class = "entropy-medium"
        label = "Moderate Uncertainty"
    else:
        css_class = "entropy-low"
        label = "Low Uncertainty"
    
    st.markdown(f"""
    <div style="margin: 10px 0;">
        <strong>Dialectical Entropy:</strong> 
        <span class="{css_class}">{entropy:.3f}</span>
        <span style="color: #888;">({label})</span>
    </div>
    """, unsafe_allow_html=True)
    
    st.progress(min(entropy, 1.0))


def render_hitl_panel():
    """Render Human-in-the-Loop approval panel."""
    st.markdown("### ✋ Pending Approvals")
    
    if not st.session_state.pending_hypotheses:
        st.info("No hypotheses pending approval")
        return
    
    for i, hyp in enumerate(st.session_state.pending_hypotheses):
        with st.container():
            st.markdown(f"""
            <div class="glass-box">
                <strong>Hypothesis:</strong> {hyp.get('claim', 'Unknown')}
                <br>
                <strong>Confidence:</strong> {hyp.get('confidence', 0):.2%}
                <br>
                <strong>Evidence:</strong> {hyp.get('evidence', 'None provided')}
            </div>
            """, unsafe_allow_html=True)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("✅ Approve", key=f"approve_{i}"):
                    st.success("Hypothesis approved and committed to graph")
                    st.session_state.pending_hypotheses.pop(i)
                    st.rerun()
            with col2:
                if st.button("❌ Reject", key=f"reject_{i}"):
                    st.error("Hypothesis rejected")
                    st.session_state.pending_hypotheses.pop(i)
                    st.rerun()
            with col3:
                if st.button("🔄 Debate", key=f"debate_{i}"):
                    st.warning("Sending to Socratic debate...")


def render_graph_explorer():
    """Render the knowledge graph explorer."""
    st.markdown("### 🕸️ Graph Explorer")
    
    # Placeholder for graph visualization
    # In production, use streamlit-agraph or pyvis
    
    st.info("Graph visualization requires TypeDB connection")
    
    # Sample visualization placeholder
    st.markdown("""
    ```mermaid
    graph LR
        A[Paper: Smith 2024] --> B[Claim: Sleep affects memory]
        B --> C[Concept: Sleep]
        B --> D[Concept: Memory]
        B --> E{Hypothesis}
        E --> F[Verified: 0.85]
    ```
    """)


def render_chat_message(role: str, content: str):
    """Render a chat message."""
    if role == "user":
        st.markdown(f"""
        <div style="background: #1e3a5f; padding: 15px; border-radius: 10px; margin: 10px 0;">
            <strong>🧑‍🔬 You:</strong><br>{content}
        </div>
        """, unsafe_allow_html=True)
    elif role == "assistant":
        st.markdown(f"""
        <div style="background: #0d1b2a; padding: 15px; border-radius: 10px; margin: 10px 0; border-left: 3px solid #4a9eff;">
            <strong>🤖 SuperHyperion:</strong><br>{content}
        </div>
        """, unsafe_allow_html=True)
    elif role == "code":
        st.code(content, language="python")
    elif role == "result":
        st.markdown(f"""
        <div class="result-block">
            <strong>📊 Result:</strong><br><pre>{content}</pre>
        </div>
        """, unsafe_allow_html=True)


# ============================================
# Main App Layout
# ============================================

def main():
    # Header
    st.title("🔬 SuperHyperion")
    st.markdown("*Multi-Agent Self-Reflecting Scientific Intelligence*")
    
    # Sidebar
    with st.sidebar:
        st.markdown("# ⚙️ Controls")
        
        # API Status
        try:
            response = httpx.get(f"{API_BASE_URL}/health", timeout=2.0)
            if response.status_code == 200:
                st.success("🟢 API Connected")
            else:
                st.error("🔴 API Error")
        except:
            st.warning("🟡 API Offline - Start with `uvicorn src.api.main:app`")
        
        st.divider()
        
        # Glass Box
        render_glass_box()
    
    # Main content - tabs
    tab1, tab2, tab3 = st.tabs(["💬 Query", "🕸️ Graph", "✋ HITL"])
    
    with tab1:
        # Chat history
        for msg in st.session_state.messages:
            render_chat_message(msg["role"], msg["content"])
        
        # Query input
        with st.form("query_form", clear_on_submit=True):
            query = st.text_area(
                "Ask a scientific question or submit a claim to verify:",
                placeholder="e.g., What is the relationship between sleep deprivation and cognitive performance?",
                height=100,
            )
            
            col1, col2 = st.columns([3, 1])
            with col1:
                submitted = st.form_submit_button("🔍 Investigate", use_container_width=True)
            with col2:
                clear = st.form_submit_button("🗑️ Clear", use_container_width=True)
        
        if clear:
            st.session_state.messages = []
            st.session_state.execution_trace = []
            st.rerun()
        
        if submitted and query:
            # Add user message
            st.session_state.messages.append({"role": "user", "content": query})
            
            # Submit to API
            with st.spinner("Submitting query..."):
                job_id = submit_query(query)
            
            if job_id:
                st.session_state.current_job_id = job_id
                
                # Poll for results
                progress = st.progress(0)
                status_text = st.empty()
                
                for i in range(60):  # Max 60 seconds
                    status = get_job_status(job_id)
                    if status:
                        status_text.text(f"Status: {status['status']}")
                        progress.progress((i + 1) / 60)
                        
                        if status["status"] == "completed":
                            result = status.get("result", {})
                            
                            # Add response
                            response_text = result.get("response", "No response generated")
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": response_text,
                            })
                            
                            # Update execution trace
                            for msg in result.get("messages", []):
                                st.session_state.execution_trace.append({
                                    "type": msg.get("role", "thought"),
                                    "content": msg.get("content", ""),
                                })
                            
                            # Show entropy
                            entropy = result.get("dialectical_entropy", 0)
                            render_entropy_gauge(entropy)
                            
                            progress.empty()
                            status_text.empty()
                            st.rerun()
                            break
                        
                        elif status["status"] == "failed":
                            st.error(f"Query failed: {status.get('error')}")
                            break
                    
                    time.sleep(1)
                else:
                    st.warning("Query timed out. Check /jobs for status.")
    
    with tab2:
        render_graph_explorer()
    
    with tab3:
        render_hitl_panel()
    
    # Footer
    st.divider()
    st.markdown("""
    <div style="text-align: center; color: #666; font-size: 12px;">
        SuperHyperion v0.1.0 | 
        Glass-Box Reasoning over Black-Box Generation |
        <a href="https://github.com/AVasilkovski/SuperHyperion">GitHub</a>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
