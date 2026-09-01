"""
JASPA agent engine.

Builds the multi-agent intelligence team (Agno) and exposes analysis functions
that produce evidence-based, streamable reports for a given company.
"""
import os
from textwrap import dedent
from typing import Iterator

from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat
from agno.tools.firecrawl import FirecrawlTools
from agno.run.team import (
    RunContentCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
)

TOOLS = lambda: FirecrawlTools(enable_search=True, enable_crawl=True, poll_interval=10)

MODEL = "gpt-4o"

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def _competitor_agent() -> Agent:
    return Agent(
        name="Startup / Competitor Analysis Agent",
        description=dedent("""
            You are a senior startup and competitor analysis strategist who evaluates
            business positioning, product launches, and venture strategy with a critical,
            evidence-driven lens.
            Your objective is to uncover:
            - How a startup or product is positioned in the market
            - Which strategies and launch tactics drove success (strengths)
            - Where execution fell short (weaknesses)
            - Actionable competitive advantages and learnings for founders and investors
            Always cite observable signals (messaging, pricing actions, channel mix, timing,
            engagement metrics). Maintain a crisp, executive tone and focus on strategic value.
            IMPORTANT: Conclude your report with a 'Sources:' section listing all URLs you
            crawled or searched.
        """),
        model=OpenAIChat(id=MODEL),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _sentiment_agent() -> Agent:
    return Agent(
        name="Market Sentiment Analysis Agent",
        description=dedent("""
            You are a market research expert specializing in sentiment analysis and consumer
            perception tracking. Your expertise includes:
            - Analyzing social media sentiment and customer feedback
            - Identifying positive and negative sentiment drivers
            - Tracking brand perception trends across platforms
            - Monitoring customer satisfaction and review patterns
            - Providing actionable insights on market reception
            Focus on extracting sentiment signals from social platforms, review sites, forums,
            and customer feedback channels.
            IMPORTANT: Conclude your report with a 'Sources:' section listing all URLs you
            crawled or searched.
        """),
        model=OpenAIChat(id=MODEL),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _metrics_agent() -> Agent:
    return Agent(
        name="Performance Metrics Agent",
        description=dedent("""
            You are a product and startup performance analyst who specializes in tracking and
            analyzing growth KPIs. Your focus areas include:
            - User adoption and engagement metrics
            - Revenue and business performance indicators
            - Market penetration and growth rates
            - Press coverage and media attention analysis
            - Social media traction and viral coefficient tracking
            - Competitive market share analysis
            Always provide quantitative insights with context and benchmark against industry
            standards when possible.
            IMPORTANT: Conclude your report with a 'Sources:' section listing all URLs you
            crawled or searched.
        """),
        model=OpenAIChat(id=MODEL),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
_team: Team | None = None
_team_error: str | None = None


def build_team() -> Team:
    """Build (or return a cached) JASPA intelligence team."""
    global _team, _team_error
    if _team is not None:
        return _team
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("FIRECRAWL_API_KEY"):
        _team_error = "Missing API keys. Configure OPENAI_API_KEY and FIRECRAWL_API_KEY in .env"
        raise RuntimeError(_team_error)

    _team = Team(
        name="JASPA Intelligence Team",
        model=OpenAIChat(id=MODEL),
        members=[_competitor_agent(), _sentiment_agent(), _metrics_agent()],
        instructions=[
            "Coordinate the analysis based on the user's request type:",
            "1. For competitor / startup analysis: use the Startup / Competitor Analysis Agent",
            "2. For market sentiment: use the Market Sentiment Analysis Agent",
            "3. For performance metrics: use the Performance Metrics Agent",
            "Always provide evidence-based insights with specific examples and data points",
            "Structure responses with clear sections and actionable recommendations",
            "Include a sources section with all URLs crawled or searched",
        ],
        markdown=True,
        show_members_responses=True,
    )
    return _team


def team_status() -> dict:
    global _team, _team_error
    ready = _team is not None or bool(
        os.getenv("OPENAI_API_KEY") and os.getenv("FIRECRAWL_API_KEY")
    )
    return {
        "ready": ready,
        "error": _team_error,
        "model": MODEL,
        "agents": [
            "Startup / Competitor Analysis Agent",
            "Market Sentiment Analysis Agent",
            "Performance Metrics Agent",
        ],
    }


# ---------------------------------------------------------------------------
# Analysis prompts
# ---------------------------------------------------------------------------
ANALYSIS_TYPES = {"competitor", "sentiment", "metrics"}


def bullets_prompt(analysis_type: str, company: str) -> str:
    if analysis_type == "competitor":
        return (
            f"Generate up to 16 evidence-based insight bullets about {company}'s most recent "
            f"product launches.\nFormat requirements:\n"
            f"- Start every bullet with exactly one tag: Positioning | Strength | Weakness | Learning\n"
            f"- Follow the tag with a concise statement (max 30 words) referencing concrete "
            f"observations: messaging, differentiation, pricing, channel selection, timing, "
            f"engagement metrics, or customer feedback."
        )
    if analysis_type == "sentiment":
        return (
            f"Summarize market sentiment for {company} in <=10 bullets. Cover top positive & "
            f"negative themes with source mentions (G2, Reddit, Twitter, customer reviews)."
        )
    return (
        f"List (max 10 bullets) the most important publicly available KPIs & qualitative signals "
        f"for {company}'s recent product launches. Include engagement stats, press coverage, "
        f"adoption metrics, and market traction data if available."
    )


def expand_prompt(analysis_type: str, company: str, bullets: str) -> str:
    if analysis_type == "competitor":
        return dedent(f"""
            Transform the insight bullets below into a professional launch review for product
            managers analysing {company}.
            Produce well-structured **Markdown** with a mix of tables, call-outs and concise
            bullet points -- avoid long paragraphs.
            === FORMAT SPECIFICATION ===
            # {company} -- Launch Review
            ## 1. Market & Product Positioning
            - Bullet point summary of how the product is positioned (max 6 bullets).
            ## 2. Launch Strengths
            | Strength | Evidence / Rationale |
            |---|---|
            | ... | ... | (add 4-6 rows)
            ## 3. Launch Weaknesses
            | Weakness | Evidence / Rationale |
            |---|---|
            | ... | ... | (add 4-6 rows)
            ## 4. Strategic Takeaways for Competitors
            1. ... (max 5 numbered recommendations)
            === SOURCE BULLETS ===
            {bullets}
            Guidelines:
            - Populate the tables with specific points derived from the bullets.
            - Only include rows that contain meaningful data; omit any blank entries.
        """)
    if analysis_type == "sentiment":
        return dedent(f"""
            Use the tagged bullets below to create a concise market-sentiment brief for {company}.
            ### Positive Sentiment
            - List each positive point as a separate bullet (max 6).
            ### Negative Sentiment
            - List each negative point as a separate bullet (max 6).
            ### Overall Summary
            Provide a short paragraph (<=120 words) summarising the overall sentiment balance and
            key drivers.
            Tagged Bullets:
            {bullets}
        """)
    return dedent(f"""
        Convert the KPI bullets below into a launch-performance snapshot for {company} suitable
        for an executive dashboard.
        ## Key Performance Indicators
        | Metric | Value / Detail | Source |
        |---|---|---|
        | ... | ... | ... |  (include one row per KPI)
        ## Qualitative Signals
        - Bullet list of notable qualitative insights (max 5).
        ## Summary & Implications
        Brief paragraph (<=120 words) highlighting what the metrics imply about launch success and
        next steps.
        KPI Bullets:
        {bullets}
    """)


def run_bullets(analysis_type: str, company: str) -> str:
    """Non-streaming first pass producing evidence-based insight bullets."""
    team = build_team()
    resp = team.run(bullets_prompt(analysis_type, company))
    content = getattr(resp, "content", None)
    return content if content else str(resp)


def stream_report(analysis_type: str, company: str, bullets: str) -> Iterator[str]:
    """Stream the expanded Markdown report, yielding incremental text deltas."""
    team = build_team()
    prompt = expand_prompt(analysis_type, company, bullets)
    for event in team.run(prompt, stream=True):
        if isinstance(event, RunContentEvent):
            delta = event.content
            if delta:
                yield delta
        elif isinstance(event, RunContentCompletedEvent):
            continue
        elif isinstance(event, RunErrorEvent):
            yield f"\n\n> **Error during generation:** {event.content or event.error_type or 'unknown'}"
            break
