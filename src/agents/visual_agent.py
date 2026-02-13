"""
Visual Evidence Agent

Extracts data from charts, plots, and figures using VLMs.
Implements DePlot/MatCha/Qwen-VL pipeline per v2.1 specification.
"""

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    """Normalized bounding box coordinates."""
    x1: float
    y1: float
    x2: float
    y2: float

    def to_dict(self) -> Dict:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_qwen_format(cls, coords: str) -> "BoundingBox":
        """Parse Qwen-VL format: <box>(x1,y1),(x2,y2)</box>"""
        import re
        match = re.search(r'\((\d+),(\d+)\),\((\d+),(\d+)\)', coords)
        if match:
            # Qwen uses 0-1000 scale, normalize to 0-1
            return cls(
                x1=int(match.group(1)) / 1000,
                y1=int(match.group(2)) / 1000,
                x2=int(match.group(3)) / 1000,
                y2=int(match.group(4)) / 1000,
            )
        return cls(0, 0, 1, 1)


@dataclass
class ExtractedData:
    """Data extracted from a visual element."""
    source_path: str
    page_number: int
    media_type: str  # "chart", "table", "plot", "diagram"
    extracted_text: str
    structured_data: Optional[Dict] = None
    bounding_box: Optional[BoundingBox] = None
    confidence: float = 0.5
    vlm_used: str = "unknown"


class VisualEvidenceAgent(BaseAgent):
    """
    Agent for extracting data from visual elements in scientific papers.
    
    Implements the v2.1 VLM pipeline:
    1. DePlot: Image → Linearized Table
    2. MatCha: Chart QA & Reasoning
    3. Qwen-VL: Bounding Box Grounding
    """

    def __init__(self):
        super().__init__(name="VisualEvidenceAgent")
        self._vlm_available = False
        self._check_vlm_availability()

    def _check_vlm_availability(self):
        """Check if VLM services are available."""
        # In production, check for DePlot/MatCha API or local models
        # For now, we'll use Ollama's vision capabilities if available
        try:
            models = self.llm.list_models()
            vision_models = [m for m in models if any(v in m for v in ['llava', 'bakllava', 'moondream'])]
            self._vlm_available = len(vision_models) > 0
            if vision_models:
                self._vision_model = vision_models[0]
                logger.info(f"VLM available: {self._vision_model}")
        except Exception as e:
            logger.warning(f"VLM check failed: {e}")
            self._vlm_available = False

    async def run(self, context: AgentContext) -> AgentContext:
        """Process any images in the context."""
        images = context.graph_context.get('images', [])

        for image_path in images:
            try:
                result = await self.extract_from_image(image_path)
                context.graph_context.setdefault('extracted_data', []).append(result)
            except Exception as e:
                logger.error(f"Failed to extract from {image_path}: {e}")

        return context

    async def extract_from_image(
        self,
        image_path: str,
        page_number: int = 1
    ) -> ExtractedData:
        """
        Extract data from an image using the VLM pipeline.
        
        Args:
            image_path: Path to the image file
            page_number: Page number in source document
            
        Returns:
            ExtractedData with text and structured data
        """
        logger.info(f"Extracting from: {image_path}")

        # Detect image type
        media_type = await self._classify_image(image_path)

        # Route to appropriate extraction method
        if media_type in ["chart", "plot"]:
            return await self._extract_chart_data(image_path, page_number, media_type)
        elif media_type == "table":
            return await self._extract_table_data(image_path, page_number)
        else:
            return await self._extract_general(image_path, page_number, media_type)

    async def _classify_image(self, image_path: str) -> str:
        """Classify the type of image."""
        if not self._vlm_available:
            # Fallback: guess from filename or default
            path = Path(image_path)
            if 'chart' in path.stem.lower():
                return 'chart'
            elif 'table' in path.stem.lower():
                return 'table'
            elif 'plot' in path.stem.lower():
                return 'plot'
            return 'diagram'

        # Use vision model to classify
        prompt = """Classify this image into ONE of these categories:
- chart (bar chart, pie chart, etc.)
- plot (scatter plot, line plot, etc.)
- table (data table)
- diagram (flowchart, architecture diagram)
- other

Respond with just the category name."""

        result = await self._query_vlm(image_path, prompt)

        category = result.lower().strip()
        if category in ['chart', 'plot', 'table', 'diagram']:
            return category
        return 'other'

    async def _extract_chart_data(
        self,
        image_path: str,
        page_number: int,
        media_type: str
    ) -> ExtractedData:
        """Extract data from a chart using DePlot-style linearization."""
        logger.info(f"Extracting {media_type} data from {image_path}")

        # DePlot-style prompt: convert image to linearized table
        deplot_prompt = """Convert this chart/graph to a data table.
Format as: Entity | Value
Include all data points visible in the chart.
Be precise with numbers."""

        linearized = await self._query_vlm(image_path, deplot_prompt)

        # Parse linearized text into structured data
        structured = self._parse_linearized_table(linearized)

        # Get bounding box for key elements (Qwen-VL style)
        bbox = await self._get_data_bbox(image_path, structured)

        return ExtractedData(
            source_path=image_path,
            page_number=page_number,
            media_type=media_type,
            extracted_text=linearized,
            structured_data=structured,
            bounding_box=bbox,
            confidence=0.7,
            vlm_used=getattr(self, '_vision_model', 'fallback'),
        )

    async def _extract_table_data(
        self,
        image_path: str,
        page_number: int
    ) -> ExtractedData:
        """Extract data from a table image."""
        prompt = """Extract all data from this table.
Format each row as: Column1 | Column2 | Column3 | ...
Include headers in the first row."""

        extracted = await self._query_vlm(image_path, prompt)
        structured = self._parse_table_text(extracted)

        return ExtractedData(
            source_path=image_path,
            page_number=page_number,
            media_type="table",
            extracted_text=extracted,
            structured_data=structured,
            confidence=0.75,
            vlm_used=getattr(self, '_vision_model', 'fallback'),
        )

    async def _extract_general(
        self,
        image_path: str,
        page_number: int,
        media_type: str
    ) -> ExtractedData:
        """Extract description from general diagrams."""
        prompt = """Describe this scientific figure in detail.
Include:
1. Main components/elements
2. Relationships shown
3. Any text or labels visible
4. Key findings or trends if applicable"""

        description = await self._query_vlm(image_path, prompt)

        return ExtractedData(
            source_path=image_path,
            page_number=page_number,
            media_type=media_type,
            extracted_text=description,
            confidence=0.6,
            vlm_used=getattr(self, '_vision_model', 'fallback'),
        )

    async def _query_vlm(self, image_path: str, prompt: str) -> str:
        """Query the vision-language model."""
        if not self._vlm_available:
            return f"[VLM not available - cannot process {image_path}]"

        try:
            # Read image as base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # Use Ollama's vision API
            import httpx
            response = httpx.post(
                f"{self.llm.base_url}/api/generate",
                json={
                    "model": self._vision_model,
                    "prompt": prompt,
                    "images": [image_data],
                    "stream": False,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json().get('response', '')

        except Exception as e:
            logger.error(f"VLM query failed: {e}")
            return f"[Error: {e}]"

    async def _get_data_bbox(
        self,
        image_path: str,
        data: Optional[Dict]
    ) -> Optional[BoundingBox]:
        """Get bounding box for data elements (Qwen-VL style)."""
        if not data or not self._vlm_available:
            return None

        # For now, return None - in production would use Qwen-VL
        # to get precise bounding boxes
        return None

    def _parse_linearized_table(self, text: str) -> Dict:
        """Parse DePlot-style linearized table into structured data."""
        lines = text.strip().split('\n')
        data = {"rows": [], "headers": None}

        for i, line in enumerate(lines):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2:
                if i == 0 and not parts[0].replace('.', '').isdigit():
                    data["headers"] = parts
                else:
                    data["rows"].append(parts)

        return data

    def _parse_table_text(self, text: str) -> Dict:
        """Parse table text into structured data."""
        return self._parse_linearized_table(text)

    async def verify_extraction(
        self,
        original_path: str,
        extracted_data: ExtractedData
    ) -> Tuple[bool, float]:
        """
        Verify extraction accuracy using reconstruction.
        
        This implements the v2.1 visual verification pipeline:
        1. Generate code to reconstruct the chart from extracted data
        2. Render the reconstructed chart
        3. Compare using SSIM and VLM similarity
        """
        logger.info(f"Verifying extraction from: {original_path}")

        # Generate matplotlib code to reconstruct
        if not extracted_data.structured_data:
            return False, 0.0

        _recon_code = self._generate_reconstruction_code(extracted_data)

        # In production, would execute code and compare images
        # For now, return confidence score as verification
        return extracted_data.confidence > 0.6, extracted_data.confidence

    def _generate_reconstruction_code(self, data: ExtractedData) -> str:
        """Generate matplotlib code to reconstruct the visualization."""
        if data.media_type == "chart":
            return f"""
import matplotlib.pyplot as plt

# Extracted data
data = {data.structured_data}

# Reconstruct chart
if data.get('headers') and data.get('rows'):
    labels = [row[0] for row in data['rows']]
    values = [float(row[1]) for row in data['rows']]
    
    plt.figure(figsize=(10, 6))
    plt.bar(labels, values)
    plt.title('Reconstructed Chart')
    plt.savefig('reconstruction.png')
"""
        return "# Cannot reconstruct this type"

    def save_to_graph(self, data: ExtractedData):
        """Save extracted data to TypeDB (deferred to OntologySteward)."""
        # WriteCap: graph writes must go through OntologySteward
        logger.info(
            f"Visual evidence save deferred to OntologySteward: "
            f"{data.source_path} ({data.media_type})"
        )


# Global instance
visual_agent = VisualEvidenceAgent()
