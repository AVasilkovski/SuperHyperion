"""
FastAPI Gateway

Main API for SuperHyperion scientific reasoning system.
Provides endpoints for queries, streaming, and file uploads.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.config import config
from src.graph import run_query

logger = logging.getLogger(__name__)

# ============================================
# App Setup
# ============================================

app = FastAPI(
    title="SuperHyperion API",
    description="Multi-Agent Self-Reflecting Scientific Intelligence System",
    version="0.1.0",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job storage (replace with Redis for production)
jobs: Dict[str, Dict[str, Any]] = {}


# ============================================
# Request/Response Models
# ============================================

class QueryRequest(BaseModel):
    """Request model for query endpoint."""
    query: str = Field(..., description="Natural language query or claim to investigate")
    thread_id: Optional[str] = Field(None, description="Thread ID for conversation continuity")


class QueryResponse(BaseModel):
    """Response model for query endpoint."""
    job_id: str
    status: str
    message: str


class JobStatus(BaseModel):
    """Status of a background job."""
    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class UploadResponse(BaseModel):
    """Response model for file upload."""
    filename: str
    status: str
    message: str


# ============================================
# Background Task Handlers
# ============================================

async def process_query(job_id: str, query: str, thread_id: str):
    """Process a query in the background."""
    jobs[job_id]["status"] = "running"

    try:
        result = await run_query(query, thread_id)

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
        jobs[job_id]["result"] = {
            "response": result.get("response"),
            "dialectical_entropy": result.get("dialectical_entropy"),
            "iterations": result.get("iteration"),
            "in_debate": result.get("in_debate"),
            "messages": result.get("messages", [])[-5:],  # Last 5 messages
            "code_executions": len(result.get("code_executions", [])),
        }

    except Exception as e:
        logger.error(f"Query processing failed: {e}")
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()


# ============================================
# Endpoints
# ============================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "SuperHyperion API",
        "status": "healthy",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "jobs_in_memory": len(jobs),
    }


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest, background_tasks: BackgroundTasks):
    """
    Submit a natural language query for investigation.
    
    Returns a job_id that can be used to check status via /status/{job_id}
    or stream results via /stream/{job_id}.
    """
    job_id = str(uuid.uuid4())
    thread_id = request.thread_id or job_id

    jobs[job_id] = {
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "query": request.query,
        "thread_id": thread_id,
    }

    background_tasks.add_task(process_query, job_id, request.query, thread_id)

    return QueryResponse(
        job_id=job_id,
        status="pending",
        message="Query submitted. Use /status/{job_id} to check progress.",
    )


@app.get("/status/{job_id}", response_model=JobStatus)
async def get_status(job_id: str):
    """Get the status of a submitted query job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        created_at=job["created_at"],
        completed_at=job.get("completed_at"),
        result=job.get("result"),
        error=job.get("error"),
    )


@app.get("/stream/{job_id}")
async def stream_job(job_id: str):
    """
    Server-Sent Events endpoint for streaming job updates.
    
    Streams events with types:
    - thought: Agent reasoning
    - code: Code being executed
    - result: Code execution result
    - graph_update: Knowledge graph changes
    - complete: Final response
    - error: Error occurred
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        last_status = None
        last_message_count = 0

        while True:
            if job_id not in jobs:
                yield {"event": "error", "data": "Job not found"}
                break

            job = jobs[job_id]
            status = job["status"]

            # Status change
            if status != last_status:
                yield {
                    "event": "status",
                    "data": f'{{"status": "{status}", "job_id": "{job_id}"}}',
                }
                last_status = status

            # Stream messages as they arrive
            if "result" in job and job["result"]:
                messages = job["result"].get("messages", [])
                for i, msg in enumerate(messages[last_message_count:], start=last_message_count):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")[:500]  # Truncate for streaming

                    event_type = {
                        "assistant": "thought",
                        "code": "code",
                        "result": "result",
                        "critique": "critique",
                        "debate": "debate",
                    }.get(role, "thought")

                    yield {
                        "event": event_type,
                        "data": content.replace("\n", "\\n"),
                    }
                last_message_count = len(messages)

            # Check for completion
            if status == "completed":
                result = job.get("result", {})
                yield {
                    "event": "complete",
                    "data": f'{{"response": "{result.get("response", "")[:1000]}", "entropy": {result.get("dialectical_entropy", 0):.3f}}}',
                }
                break

            if status == "failed":
                yield {
                    "event": "error",
                    "data": job.get("error", "Unknown error"),
                }
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a PDF file for ingestion.
    
    The file will be processed asynchronously by the IngestionAgent.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported"
        )

    # Save file (in production, use cloud storage)
    import os
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    content = await file.read()

    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"File uploaded: {file.filename}")

    # TODO: Trigger IngestionAgent

    return UploadResponse(
        filename=file.filename,
        status="uploaded",
        message="File uploaded. Ingestion will be processed asynchronously.",
    )


@app.get("/jobs")
async def list_jobs(limit: int = 10):
    """List recent jobs."""
    sorted_jobs = sorted(
        jobs.items(),
        key=lambda x: x[1].get("created_at", ""),
        reverse=True,
    )[:limit]

    return [
        {
            "job_id": job_id,
            "status": job["status"],
            "query": job.get("query", "")[:100],
            "created_at": job["created_at"],
        }
        for job_id, job in sorted_jobs
    ]


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job from memory."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    del jobs[job_id]
    return {"status": "deleted", "job_id": job_id}


# ============================================
# Run Server
# ============================================

if __name__ == "__main__":
    from src.utils.logging_setup import setup_logging
    setup_logging()
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=config.api.host,
        port=config.api.port,
        reload=config.api.debug,
    )
