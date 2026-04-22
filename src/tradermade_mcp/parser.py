"""Parse TraderMade API documentation from markdown format."""

import re
from typing import Optional, List, Dict


class ParsedEndpoint(object):
    """Intermediate format for parsed endpoints."""

    def __init__(
        self,
        name,  # type: str
        path_pattern,  # type: str
        description,  # type: str
        market="market-data",  # type: str
        tags=None,  # type: Optional[List[str]]
        docs_url="https://tradermade.com/docs/restful-api",  # type: str
        params=None,  # type: Optional[List[Dict]]
        examples=None,  # type: Optional[List[str]]
        notes=None,  # type: Optional[List[str]]
    ):  # type: (...) -> None
        """Initialize ParsedEndpoint."""
        self.name = name
        self.path_pattern = path_pattern
        self.description = description
        self.market = market
        self.tags = tags if tags is not None else []
        self.docs_url = docs_url
        self.params = params if params is not None else []
        self.examples = examples if examples is not None else []
        self.notes = notes if notes is not None else []


def parse_tradermade_docs(text: str) -> List[ParsedEndpoint]:
    """Parse tradermade-full.txt markdown into structured endpoints.

    Args:
        text: Raw markdown text from tradermade-full.txt

    Returns:
        List of ParsedEndpoint objects
    """
    endpoints: list[ParsedEndpoint] = []

    # Split by top-level headers (### Endpoint Name)
    endpoint_sections = re.split(r'\n### ([a-z_]+)\n', text)

    # Skip header and process pairs (name, content)
    for i in range(1, len(endpoint_sections), 2):
        if i + 1 < len(endpoint_sections):
            name = endpoint_sections[i].strip()
            content = endpoint_sections[i + 1]

            try:
                endpoint = _parse_endpoint_section(name, content)
                if endpoint:
                    endpoints.append(endpoint)
            except Exception as e:
                print(f"Warning: Failed to parse endpoint '{name}': {e}")
                continue

    return endpoints


def _parse_endpoint_section(name: str, content: str) -> Optional[ParsedEndpoint]:
    """Parse a single endpoint section (between ### headers)."""

    # Extract Description
    description_match = re.search(r'\*\*Description\*\*:\s*([^\n]+)', content)
    description = description_match.group(1).strip() if description_match else ""

    # Extract Path
    path_match = re.search(r'\*\*Path\*\*:\s*`([^`]+)`', content)
    path = path_match.group(1).strip() if path_match else f"/{name}"

    # Extract Market
    market_match = re.search(r'\*\*Market\*\*:\s*([^\n]+)', content)
    market = market_match.group(1).strip() if market_match else "market-data"

    # Extract Docs URL
    docs_url_match = re.search(r'\*\*Docs URL\*\*:\s*([^\n]+)', content)
    docs_url = docs_url_match.group(1).strip() if docs_url_match else "https://tradermade.com/docs/restful-api"

    # Extract Tags
    tags = []
    tags_match = re.search(r'\*\*Tags\*\*:\s*([^\n]+)', content)
    if tags_match:
        tag_text = tags_match.group(1).strip()
        tags = [t.strip() for t in tag_text.split(',')]

    # Extract Examples - try multiple patterns
    examples = []

    # Try: Query Examples: ```\n...```
    examples_match = re.search(r'Query Examples?:\s*```[^\n]*\n((?:[^\n`]*\n)*?)\s*```', content, re.IGNORECASE)

    if examples_match:
        examples_text = examples_match.group(1).strip()
        # Clean up GET/POST prefixes
        for line in examples_text.split('\n'):
            if line.strip():
                # Remove "GET " or "POST " prefix if present
                line = re.sub(r'^(?:GET|POST)\s+', '', line).strip()
                if line and not line.startswith('{'):  # Exclude JSON responses
                    examples.append(line)

    # Fallback: Look for inline examples with GET/POST
    if not examples:
        inline_examples = re.findall(r'(?:GET|POST)\s+(/[^\s\n]+)', content)
        examples.extend(inline_examples)

    # Extract Notes
    notes = []
    notes_section = re.search(r'Notes?:\s*((?:\n-[^\n]+)*)', content, re.IGNORECASE)
    if notes_section:
        for match in re.finditer(r'\n-\s*([^\n]+)', notes_section.group(1)):
            notes.append(match.group(1).strip())

    # Extract Parameters from table
    params = _extract_parameters(content)

    return ParsedEndpoint(
        name=name,
        path_pattern=path,
        description=description,
        market=market,
        tags=tags,
        docs_url=docs_url,
        params=params,
        examples=examples,
        notes=notes,
    )


def _extract_parameters(content: str) -> List[Dict]:
    """Extract parameters from markdown table format."""
    params = []

    # Look for parameter table: | Name | Location | Type | ... |
    table_match = re.search(
        r'\| Name \| Location \| Type \| Required \| Example \| Description \|((?:\n\|[^\n]*\|)*)',
        content,
        re.IGNORECASE
    )

    if table_match:
        table_body = table_match.group(1)
        for line in table_body.strip().split('\n'):
            if not line.strip() or line.strip().startswith('-') or all(c in '-|: ' for c in line):
                continue

            # Parse table row
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 7:
                name = parts[1]
                location = parts[2]
                type_ = parts[3]
                required = parts[4].lower() in ('yes', 'true', 'required')
                example = parts[5] if parts[5] and parts[5] != '' else None
                description = parts[6] if len(parts) > 6 else ""

                # Skip if name looks like a table separator (all dashes)
                if name and not all(c == '-' for c in name):
                    params.append({
                        "name": name,
                        "location": location,
                        "required": required,
                        "type": type_,
                        "description": description,
                        "example": example,
                    })

    # Also check for inline parameter lists with **Parameters**: format
    param_pattern = r'\n-\s+`([^`]+)`\s+\[([^\]]+),\s*([^\]]+),\s*([^\]]+)\]:\s*([^\n]+)'
    for match in re.finditer(param_pattern, content):
        name = match.group(1)
        location = match.group(2).strip()
        requirement = match.group(3).strip()
        type_ = match.group(4).strip()
        description = match.group(5).strip()

        params.append({
            "name": name,
            "location": location,
            "required": requirement.lower() == "required",
            "type": type_,
            "description": description,
            "example": None,
        })

    return params


def convert_parsed_to_json_format(endpoint: ParsedEndpoint) -> Dict:
    """Convert ParsedEndpoint to JSON format compatible with endpoint_catalog.json."""
    return {
        "name": endpoint.name,
        "docs_id": f"tm://{endpoint.name}",
        "market": endpoint.market,
        "path_pattern": endpoint.path_pattern,
        "description": endpoint.description,
        "tags": endpoint.tags or [],
        "docs_url": endpoint.docs_url,
        "source": "dynamic_markdown_docs",
        "params": endpoint.params or [],
        "response_hint": "generic",
        "examples": endpoint.examples or [],
        "notes": endpoint.notes or [],
    }
