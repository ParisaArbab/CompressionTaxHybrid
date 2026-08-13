"""
WP1 - the localization agent under test.

Combines the two attached methods:
  - FlexFL's pipeline shape: task assignment -> ReAct-style function-calling
    loop over the repo -> summarization into a ranked list, working from
    whatever bug-related text is available (here: problem_statement +
    either raw or rtk-compressed terminal output).
  - GraphLocator's structure: a lightweight Repository Dependency Fractal
    Structure (RDFS) built with `ast` (dir/file/class/function vertices,
    UsedBy call edges), a symptom-vertex search phase, and a priority-driven
    Causal Issue Graph (CIG) expansion phase that asks the LLM to reason
    about which neighboring vertices plausibly cause the symptom.

This is a genuine, runnable implementation (needs ANTHROPIC_API_KEY to
actually call the model) -- not a mock. It is deliberately simplified
relative to the full papers (no fuzzy/edit-distance search tool, no MBFL/
SBFL space-reduction stage) since WP1's job is only to measure the raw-vs-
compressed gap, not to reproduce either paper's full benchmark numbers.
"""
import ast
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = os.environ.get("WP1_MODEL", "claude-sonnet-4-6")
MAX_SR_TURNS = 6
MAX_CIG_TURNS = 8
TOP_K = 5


# --------------------------------------------------------------------------
# Lightweight RDFS: file -> class/function vertices, with UsedBy call edges
# --------------------------------------------------------------------------
@dataclass
class Vertex:
    vid: str          # "path/to/file.py::func_or_class[.method]"
    kind: str         # "function" | "method" | "class"
    file: str
    lineno: int
    source: str


@dataclass
class RDFS:
    vertices: dict = field(default_factory=dict)      # vid -> Vertex
    calls: dict = field(default_factory=dict)          # vid -> set(vid) (UsedBy, best-effort)

    def build(self, repo_root: Path, include_globs=("**/*.py",)):
        py_files = []
        for g in include_globs:
            py_files.extend(repo_root.glob(g))
        for f in py_files:
            if any(p in str(f) for p in ("/tests/", "/test_", "/.git/")):
                continue
            try:
                src = f.read_text(errors="ignore")
                tree = ast.parse(src)
            except Exception:
                continue
            rel = str(f.relative_to(repo_root))
            lines = src.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    vid = f"{rel}::{node.name}"
                    end = getattr(node, "end_lineno", node.lineno + 20)
                    snippet = "\n".join(lines[node.lineno - 1: min(end, node.lineno + 40)])
                    self.vertices[vid] = Vertex(vid, kind, rel, node.lineno, snippet)
                    calls = set()
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Call) and isinstance(sub.func, (ast.Name, ast.Attribute)):
                            name = sub.func.id if isinstance(sub.func, ast.Name) else sub.func.attr
                            calls.add(name)
                    self.calls[vid] = calls

    def search_by_name(self, name: str, k: int = 8):
        name = name.strip().lstrip("_")
        scored = []
        for vid, v in self.vertices.items():
            fname = vid.split("::")[-1]
            if name.lower() in fname.lower() or fname.lower() in name.lower():
                scored.append(vid)
        return scored[:k]

    def neighbors(self, vid: str, k: int = 10):
        """Best-effort 'UsedBy' neighbors: vertices whose body calls this
        vertex's short name, or that this vertex calls."""
        if vid not in self.vertices:
            return []
        short = vid.split("::")[-1]
        out = []
        for other_vid, called_names in self.calls.items():
            if other_vid == vid:
                continue
            if short in called_names:
                out.append(other_vid)
        for called_name in self.calls.get(vid, []):
            hits = self.search_by_name(called_name, k=2)
            out.extend(hits)
        seen, dedup = set(), []
        for x in out:
            if x not in seen:
                seen.add(x)
                dedup.append(x)
        return dedup[:k]


# --------------------------------------------------------------------------
# LLM client wrapper
# --------------------------------------------------------------------------
class LLM:
    def __init__(self, model=MODEL):
        if anthropic is None:
            raise RuntimeError("pip install anthropic to run the live agent")
        self.client = anthropic.Anthropic()
        self.model = model

    def ask(self, system, user, max_tokens=1024):
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")


# --------------------------------------------------------------------------
# Stage I (FlexFL Agent4SR / GraphLocator symptom-vertices-locating):
# find symptom vertices from the bug text + terminal output
# --------------------------------------------------------------------------
def locate_symptom_vertices(llm: LLM, rdfs: RDFS, problem_statement: str, terminal_output: str):
    system = (
        "You are a debugging assistant. You will be given an issue description "
        "and terminal/test output. Identify up to 5 function or class NAMES "
        "(short identifiers, not full paths) that are most likely directly "
        "related to the reported symptom -- i.e. functions explicitly named in "
        "the text, or named in a stack trace / assertion. "
        "Reply with ONLY a JSON list of strings, nothing else."
    )
    user = (
        f"ISSUE DESCRIPTION:\n{problem_statement}\n\n"
        f"TERMINAL OUTPUT:\n{terminal_output}\n\n"
        "Return the JSON list of candidate function/class names now."
    )
    raw = llm.ask(system, user, max_tokens=256)
    try:
        names = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
    except Exception:
        names = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", raw)[:5]
    symptom_vertices = []
    for n in names:
        symptom_vertices.extend(rdfs.search_by_name(n, k=2))
    seen, dedup = set(), []
    for v in symptom_vertices:
        if v not in seen:
            seen.add(v)
            dedup.append(v)
    return dedup[:TOP_K]


# --------------------------------------------------------------------------
# Stage II (FlexFL Agent4LR / GraphLocator dynamic-CIG-discovering):
# priority-driven abductive expansion over RDFS neighbors
# --------------------------------------------------------------------------
def expand_causal_graph(llm: LLM, rdfs: RDFS, problem_statement: str, terminal_output: str,
                         symptom_vertices: list, max_turns: int = MAX_CIG_TURNS):
    visited = set(symptom_vertices)
    frontier = list(symptom_vertices)
    cig_edges = []  # (from, to, prob)
    ranked = list(symptom_vertices)

    for _ in range(max_turns):
        if not frontier:
            break
        x = frontier.pop(0)
        neighbors = [n for n in rdfs.neighbors(x, k=6) if n not in visited]
        if not neighbors:
            continue
        system = (
            "You are performing graph-guided abductive reasoning for bug "
            "localization (GraphLocator-style). Given the issue, the terminal "
            "output, the current suspicious code vertex, and its neighboring "
            "code vertices in the repository's dependency graph, decide which "
            "neighbors are PLAUSIBLE intermediate causes or root causes of the "
            "bug. Reply ONLY as JSON: a list of {\"vertex\": <name>, \"prob\": <0-1 float>}."
        )
        neighbor_code = "\n\n".join(
            f"### {n}\n{rdfs.vertices[n].source[:600]}" for n in neighbors if n in rdfs.vertices
        )
        user = (
            f"ISSUE:\n{problem_statement}\n\nTERMINAL OUTPUT:\n{terminal_output}\n\n"
            f"CURRENT VERTEX: {x}\n{rdfs.vertices.get(x).source[:600] if x in rdfs.vertices else ''}\n\n"
            f"NEIGHBOR CANDIDATES:\n{neighbor_code}\n\nJSON list now."
        )
        raw = llm.ask(system, user, max_tokens=400)
        try:
            picks = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        except Exception:
            picks = []
        picks.sort(key=lambda p: -float(p.get("prob", 0)))
        for p in picks:
            v = p.get("vertex")
            if v in rdfs.vertices and v not in visited:
                visited.add(v)
                frontier.append(v)
                ranked.append(v)
                cig_edges.append((x, v, float(p.get("prob", 0))))
    return ranked[:TOP_K], cig_edges


def localize(llm: LLM, rdfs: RDFS, problem_statement: str, terminal_output: str):
    symptoms = locate_symptom_vertices(llm, rdfs, problem_statement, terminal_output)
    ranked, cig_edges = expand_causal_graph(llm, rdfs, problem_statement, terminal_output, symptoms)
    return {"ranked_functions": ranked, "cig_edges": cig_edges, "symptom_vertices": symptoms}
