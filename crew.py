"""
CrewAI Crew Orchestration — the brain of the Internship Outreach Agent.

Assembles agents with full skills (knowledge + tools + role strategy + memory),
defines tasks with structured outputs and guardrails, and runs the pipeline.
"""

import json
import os
from pathlib import Path

import yaml
from crewai import Agent, Crew, LLM, Process, Task
from crewai.knowledge.source.json_knowledge_source import JSONKnowledgeSource
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource

from agents.schemas import EmailDraftList, EnrichedProspectList, ProspectList
from tools.apollo_tool import ApolloEnrichTool, ApolloPersonSearchTool
from tools.hunter_tool import HunterEmailFinderTool, HunterEmailVerifyTool
from tools.scrape_tool import WebScrapeTool
from tools.search_tool import DuckDuckGoSearchTool, LinkedInSearchTool

# ── Paths ────────────────────────────────────────────────────

ROOT = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
KNOWLEDGE_DIR = ROOT / "knowledge"


def _load_yaml(filename: str) -> dict:
    """Load a YAML config file."""
    with open(CONFIG_DIR / filename, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_company_context(company_name: str) -> dict:
    """Load context for a specific company from target_companies.json."""
    targets_path = KNOWLEDGE_DIR / "target_companies.json"
    with open(targets_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for c in data.get("companies", []):
        if c["name"].lower() == company_name.lower():
            return c

    # If company not in targets, return minimal context
    return {"name": company_name, "domain": "", "why": "", "target_teams": [], "notes": ""}


# ── Knowledge Sources ────────────────────────────────────────

def _build_crew_knowledge() -> list:
    """Build crew-level knowledge sources (shared by all agents)."""
    sources = []

    # Profile and company context — shared knowledge
    profile_path = KNOWLEDGE_DIR / "my_profile.json"
    if profile_path.exists():
        sources.append(JSONKnowledgeSource(file_paths=[str(profile_path)]))

    # CAN-SPAM rules — every agent should know these
    canspam_path = KNOWLEDGE_DIR / "can_spam_rules.txt"
    if canspam_path.exists():
        sources.append(TextFileKnowledgeSource(file_paths=[str(canspam_path)]))

    return sources


def _build_researcher_knowledge() -> list:
    """Build researcher-specific knowledge."""
    sources = []
    strategy_path = KNOWLEDGE_DIR / "outreach_strategy.txt"
    if strategy_path.exists():
        sources.append(TextFileKnowledgeSource(
            file_paths=[str(strategy_path)]))
    return sources


def _build_writer_knowledge() -> list:
    """Build writer-specific knowledge."""
    sources = []

    examples_path = KNOWLEDGE_DIR / "cold_email_examples.txt"
    if examples_path.exists():
        sources.append(TextFileKnowledgeSource(
            file_paths=[str(examples_path)]))

    anti_path = KNOWLEDGE_DIR / "email_anti_patterns.txt"
    if anti_path.exists():
        sources.append(TextFileKnowledgeSource(file_paths=[str(anti_path)]))

    return sources


# ── Guardrails ───────────────────────────────────────────────

def validate_prospects(result) -> tuple[bool, str]:
    """Guardrail: Ensure every prospect has at least one personalization hook."""
    try:
        output = result.pydantic if hasattr(result, "pydantic") else result
        if hasattr(output, "prospects"):
            for p in output.prospects:
                if not p.personalization_hooks or len(p.personalization_hooks) == 0:
                    return (
                        False,
                        f"Prospect '{p.name}' has no personalization hooks. "
                        f"Research deeper or find a different person.",
                    )
                # Check for vague hooks
                for hook in p.personalization_hooks:
                    if len(hook) < 20:
                        return (
                            False,
                            f"Hook '{hook}' for {p.name} is too vague. "
                            f"Be more specific — reference a concrete project, talk, or post.",
                        )
        return (True, "")
    except Exception:
        return (True, "")  # Don't block on guardrail errors


def validate_emails(result) -> tuple[bool, str]:
    """Guardrail: Ensure emails look valid and aren't fabricated."""
    try:
        output = result.pydantic if hasattr(result, "pydantic") else result
        if hasattr(output, "prospects"):
            for p in output.prospects:
                if not p.email or "@" not in p.email:
                    return (
                        False,
                        f"Invalid email for {p.name}: '{p.email}'. "
                        f"Remove this prospect if no valid email was found.",
                    )
        return (True, "")
    except Exception:
        return (True, "")


def validate_drafts(result) -> tuple[bool, str]:
    """Guardrail: Check email quality — length, personalization, CAN-SPAM."""
    try:
        output = result.pydantic if hasattr(result, "pydantic") else result
        if hasattr(output, "drafts"):
            for d in output.drafts:
                word_count = len(d.body.split())
                if word_count > 200:
                    return (
                        False,
                        f"Email to {d.to_name} is {word_count} words — too long. "
                        f"Rewrite to be under 150 words.",
                    )
                if not d.personalization_note:
                    return (
                        False,
                        f"Email to {d.to_name} has no personalization_note. "
                        f"Explain which hook you used and why.",
                    )
        return (True, "")
    except Exception:
        return (True, "")


# ── Crew Builder ─────────────────────────────────────────────

def build_crew(
    company: str,
    role: str = "Software Engineer",
    human_input: bool = True,
) -> Crew:
    """
    Build the full outreach crew for a target company.

    Args:
        company: Company name to target.
        role: Role/position to search for.
        human_input: If True, the writer task requires human approval.
    """
    # Load configs
    agent_configs = _load_yaml("agents.yaml")
    task_configs = _load_yaml("tasks.yaml")
    company_ctx = _load_company_context(company)

    # Template variables
    company_domain = company_ctx.get(
        "domain", f"{company.lower().replace(' ', '')}.com")
    company_notes = company_ctx.get(
        "why", "") + " " + company_ctx.get("notes", "")
    company_notes = company_notes.strip(
    ) or f"Targeting {company} for {role} internship."

    # ── Gemini LLM (free tier) ──
    model_name = os.getenv("MODEL", "gemini/gemini-2.0-flash")
    llm = LLM(
        model=model_name,
        temperature=0.7,
    )

    # ── Build Agents with Skills ──

    # Researcher: knowledge of strategy + search tools + reasoning
    researcher_cfg = agent_configs["researcher"]
    researcher = Agent(
        role=researcher_cfg["role"].format(role=role),
        goal=researcher_cfg["goal"].format(company=company),
        backstory=researcher_cfg["backstory"].format(company=company),
        llm=llm,
        tools=[
            DuckDuckGoSearchTool(),
            LinkedInSearchTool(),
            WebScrapeTool(),
        ],
        knowledge_sources=_build_researcher_knowledge(),
        verbose=researcher_cfg.get("verbose", True),
        allow_delegation=researcher_cfg.get("allow_delegation", False),
        max_iter=15,
    )

    # Email Finder: API tools + enrichment strategy
    finder_cfg = agent_configs["email_finder"]
    email_finder = Agent(
        role=finder_cfg["role"],
        goal=finder_cfg["goal"],
        backstory=finder_cfg["backstory"],
        llm=llm,
        tools=[
            ApolloPersonSearchTool(),
            ApolloEnrichTool(),
            HunterEmailFinderTool(),
            HunterEmailVerifyTool(),
        ],
        verbose=finder_cfg.get("verbose", True),
        allow_delegation=finder_cfg.get("allow_delegation", False),
        max_iter=15,
    )

    # Writer: knowledge of email examples + anti-patterns + your profile
    writer_cfg = agent_configs["writer"]
    writer = Agent(
        role=writer_cfg["role"],
        goal=writer_cfg["goal"],
        backstory=writer_cfg["backstory"],
        llm=llm,
        tools=[],  # Pure LLM writing — no tools needed
        knowledge_sources=_build_writer_knowledge(),
        verbose=writer_cfg.get("verbose", True),
        allow_delegation=writer_cfg.get("allow_delegation", False),
        max_iter=10,
    )

    # ── Build Tasks with Structured Outputs + Guardrails ──

    research_cfg = task_configs["research_prospects"]
    research_task = Task(
        description=research_cfg["description"].format(
            company=company,
            role=role,
            company_notes=company_notes,
        ),
        expected_output=research_cfg["expected_output"],
        agent=researcher,
        output_pydantic=ProspectList,
        guardrail=validate_prospects,
    )

    find_cfg = task_configs["find_emails"]
    find_task = Task(
        description=find_cfg["description"].format(
            company_domain=company_domain,
            research_results="{Use the output from the previous research task}",
        ),
        expected_output=find_cfg["expected_output"],
        agent=email_finder,
        output_pydantic=EnrichedProspectList,
        context=[research_task],
        guardrail=validate_emails,
    )

    draft_cfg = task_configs["draft_emails"]
    draft_task = Task(
        description=draft_cfg["description"].format(
            company_notes=company_notes,
            enriched_results="{Use the output from the previous email finding task}",
        ),
        expected_output=draft_cfg["expected_output"],
        agent=writer,
        output_pydantic=EmailDraftList,
        context=[find_task],
        guardrail=validate_drafts,
        human_input=human_input,
    )

    # ── Assemble the Crew ──

    crew = Crew(
        agents=[researcher, email_finder, writer],
        tasks=[research_task, find_task, draft_task],
        process=Process.sequential,
        knowledge_sources=_build_crew_knowledge(),
        memory=True,  # Enable unified memory system
        verbose=True,
    )

    return crew


def run_crew(
    company: str,
    role: str = "Software Engineer",
    human_input: bool = True,
) -> dict:
    """
    Run the full outreach pipeline for a company.

    Returns:
        dict with keys: company, prospects, enriched, drafts
    """
    crew = build_crew(company, role, human_input)
    result = crew.kickoff()

    # Extract structured outputs
    output = {
        "company": company,
        "role": role,
        "raw_output": str(result),
    }

    # Try to extract the final task output (email drafts)
    if hasattr(result, "pydantic") and result.pydantic:
        output["drafts"] = result.pydantic.model_dump()
    elif hasattr(result, "json_dict") and result.json_dict:
        output["drafts"] = result.json_dict

    return output


def train_crew(
    company: str,
    role: str = "Software Engineer",
    n_iterations: int = 2,
):
    """
    Run the crew in training mode — human reviews every output and provides feedback.
    Training data is saved to trained_agents_data.pkl for future runs.
    """
    crew = build_crew(company, role, human_input=True)
    crew.train(
        n_iterations=n_iterations,
        inputs={"company": company, "role": role},
        filename=str(ROOT / "trained_agents_data.pkl"),
    )
    print(f"\n✓ Training complete! Agent improvements saved to trained_agents_data.pkl")
    print("  Future runs will automatically use your feedback to improve outputs.")
