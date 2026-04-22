import json
import re
import os
from functools import lru_cache
from typing import Any, Iterable, Optional, List, Dict, Tuple, Pattern


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_+.-]+")
_TICK_TOKENS = {"tick", "ticks", "bid", "ask", "bidask", "microstructure", "execution", "slippage", "tca"}
_MINUTE_TOKENS = {"minute", "minutes", "1m", "intraday"}


class ParameterDoc(object):
    """Parameter documentation."""
    __slots__ = ('name', 'location', 'required', 'type', 'description', 'example')

    def __init__(self, name, location, required, type, description, example=None):
        self.name = name
        self.location = location
        self.required = required
        self.type = type
        self.description = description
        self.example = example


class EndpointDoc(object):
    """Endpoint documentation."""

    def __init__(
        self,
        name,  # type: str
        docs_id,  # type: str
        market,  # type: str
        path_pattern,  # type: str
        description,  # type: str
        tags=None,  # type: Optional[Tuple[str, ...]]
        docs_url=None,  # type: Optional[str]
        source=None,  # type: Optional[str]
        params=None,  # type: Optional[Tuple[ParameterDoc, ...]]
        response_hint=None,  # type: Optional[str]
        examples=None,  # type: Optional[Tuple[str, ...]]
        notes=None,  # type: Optional[Tuple[str, ...]]
    ):  # type: (...) -> None
        """Initialize EndpointDoc."""
        self.name = name
        self.docs_id = docs_id
        self.market = market
        self.path_pattern = path_pattern
        self.description = description
        self.tags = tags if tags is not None else ()
        self.docs_url = docs_url if docs_url else "https://tradermade.com/docs/restful-api"
        self.source = source if source else "official_docs"
        self.params = params if params is not None else ()
        self.response_hint = response_hint if response_hint else "generic"
        self.examples = examples if examples is not None else ()
        self.notes = notes if notes is not None else ()

        # Compile regex for path matching
        pattern = re.escape(self.path_pattern)
        pattern = re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", pattern)
        self._compiled_regex = re.compile(r"^%s$" % pattern)

    @property
    def search_text(self):  # type: () -> str
        parts = [self.name, self.market, self.path_pattern, self.description, *self.tags]
        for param in self.params:
            parts.extend([param.name, param.location, param.type, param.description])
        parts.extend(self.examples)
        parts.extend(self.notes)
        return " ".join(parts).lower()

    def matches_path(self, path):  # type: (str) -> bool
        return bool(self._compiled_regex.match(path))


class EndpointIndex:
    def __init__(self, endpoints):  # type: (Iterable[EndpointDoc]) -> None
        self._endpoints = list(endpoints)
        self._by_name = {endpoint.name.lower(): endpoint for endpoint in self._endpoints}
        self._by_docs_id = {endpoint.docs_id.lower(): endpoint for endpoint in self._endpoints}
        self._by_path = {endpoint.path_pattern.lower(): endpoint for endpoint in self._endpoints}

    @property
    def endpoints(self):  # type: () -> List[EndpointDoc]
        return list(self._endpoints)

    def resolve(self, identifier):  # type: (str) -> Optional[EndpointDoc]
        key = identifier.strip().lower()
        if not key:
            return None
        if key in self._by_docs_id:
            return self._by_docs_id[key]
        if key in self._by_name:
            return self._by_name[key]
        if key in self._by_path:
            return self._by_path[key]
        for endpoint in self._endpoints:
            if endpoint.docs_url.lower() == key:
                return endpoint
        return None

    def is_path_allowed(self, path):  # type: (str) -> bool
        return any(endpoint.matches_path(path) for endpoint in self._endpoints)

    def search(self, query, top_k=7):  # type: (str, int) -> List[EndpointDoc]
        tokens = _tokenize(query)
        scored: list[tuple[float, EndpointDoc]] = []
        q = query.strip().lower()
        for endpoint in self._endpoints:
            score = _score_endpoint(endpoint, q, tokens)
            if score > 0:
                scored.append((score, endpoint))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [endpoint for _, endpoint in scored[:top_k]]


@lru_cache(maxsize=1)
def load_index():  # type: () -> EndpointIndex
    # Load endpoint_catalog.json from the same directory as this module
    module_dir = os.path.dirname(os.path.abspath(__file__))
    catalog_path = os.path.join(module_dir, "endpoint_catalog.json")

    with open(catalog_path, 'r', encoding='utf-8') as f:
        payload = f.read()

    raw = json.loads(payload)
    endpoints = []
    for item in raw:
        params = tuple(
            ParameterDoc(
                name=param["name"],
                location=param["location"],
                required=bool(param.get("required", False)),
                type=param.get("type", "string"),
                description=param.get("description", ""),
                example=param.get("example"),
            )
            for param in item.get("params", [])
        )
        endpoints.append(
            EndpointDoc(
                name=item["name"],
                docs_id=item["docs_id"],
                market=item.get("market", "market-data"),
                path_pattern=item["path_pattern"],
                description=item.get("description", ""),
                tags=tuple(item.get("tags", [])),
                docs_url=item.get("docs_url", "https://tradermade.com/docs/restful-api"),
                source=item.get("source", "official_docs"),
                params=params,
                response_hint=item.get("response_hint", "generic"),
                examples=tuple(item.get("examples", [])),
                notes=tuple(item.get("notes", [])),
            )
        )
    return EndpointIndex(endpoints)


def format_search_result(endpoint, rank):  # type: (EndpointDoc, int) -> str
    source = _source_label(endpoint.source)
    return (
        f"{rank}. {endpoint.name} [{endpoint.market}]\n"
        f"   Path: {endpoint.path_pattern}\n"
        f"   {endpoint.description}\n"
        f"   Docs ID: {endpoint.docs_id}\n"
        f"   Docs URL: {endpoint.docs_url}\n"
        f"   Source: {source}"
    )


def format_endpoint_docs(endpoint):  # type: (EndpointDoc) -> str
    lines = [
        f"Name: {endpoint.name}",
        f"Market: {endpoint.market}",
        f"Path Pattern: {endpoint.path_pattern}",
        f"Docs ID: {endpoint.docs_id}",
        f"Docs URL: {endpoint.docs_url}",
        f"Source: {_source_label(endpoint.source)}",
        "",
        endpoint.description,
    ]

    if endpoint.params:
        lines.extend(["", "Parameters:"])
        for param in endpoint.params:
            requirement = "required" if param.required else "optional"
            example = f" Example: {param.example}" if param.example else ""
            lines.append(
                f"- {param.name} [{param.location}, {requirement}, {param.type}]: "
                f"{param.description}{example}"
            )
    else:
        lines.extend(["", "Parameters:", "- None"])

    if endpoint.examples:
        lines.extend(["", "Examples:"])
        for example in endpoint.examples:
            lines.append(f"- {example}")

    if endpoint.notes:
        lines.extend(["", "Notes:"])
        for note in endpoint.notes:
            lines.append(f"- {note}")

    return "\n".join(lines)


def normalize_path(path):  # type: (str) -> str
    cleaned = path.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        match = re.match(r"https?://[^/]+(?P<path>/.*)?", cleaned)
        cleaned = match.group("path") if match and match.group("path") else "/"
    if cleaned.startswith("/api/v1/"):
        cleaned = cleaned[len("/api/v1") :]
    elif cleaned == "/api/v1":
        cleaned = "/"
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return cleaned


def _tokenize(text):  # type: (str) -> List[str]
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _score_endpoint(endpoint, query, tokens):  # type: (EndpointDoc, str, List[str]) -> float
    haystack = endpoint.search_text
    score = 0.0
    token_set = set(tokens)

    if query == endpoint.name.lower():
        score += 50.0
    if query == endpoint.path_pattern.lower():
        score += 45.0
    if endpoint.name.lower() in query:
        score += 18.0
    if endpoint.path_pattern.lower() in query:
        score += 16.0

    for token in tokens:
        if token == endpoint.name.lower():
            score += 12.0
        if token in endpoint.path_pattern.lower():
            score += 8.0
        if token in endpoint.market.lower():
            score += 5.0
        if token in haystack:
            score += 2.0
        if any(token == tag.lower() for tag in endpoint.tags):
            score += 5.0

    if token_set:
        overlap = sum(1 for token in token_set if token in haystack)
        score += overlap * 1.5

    endpoint_name = endpoint.name.lower()
    endpoint_market = endpoint.market.lower()
    if token_set & _TICK_TOKENS:
        if endpoint_market == "tick-data" or "tick" in endpoint_name or any(tag.lower().startswith("tick") for tag in endpoint.tags):
            score += 30.0
        elif endpoint_name in {"minute_historical", "timeseries"}:
            score += 8.0
        else:
            score -= 6.0

    if token_set & _MINUTE_TOKENS and endpoint_name in {"minute_historical", "timeseries"}:
        score += 10.0

    return score


def _source_label(source):  # type: (str) -> str
    mapping = {
        "official_docs": "TraderMade REST docs",
        "node_sdk": "TraderMade Node.js SDK / public pages",
    }
    return mapping.get(source, source)
