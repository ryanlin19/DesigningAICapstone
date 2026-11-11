"""Settings shared by the pipeline and the eval scripts."""

# Model tiers. "judge" must differ from both tiers being compared.
MODELS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}
JUDGE_MODEL = "opus"

# USD per million tokens (input, output), prompts under 100K tokens.
# Source: https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-11-10).
# Re-check before reporting numbers.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

# Job-function buckets. Downstream matching compares these with job keywords.
BUCKETS = {
    "engineering": "builds software or systems: engineers, developers, architects, technical staff",
    "data_ml": "data science, analytics, machine learning, AI research engineering",
    "product": "product management or product ownership",
    "design": "UX, UI, visual or product design",
    "recruiting": "recruiters, talent acquisition, HR",
    "sales_gtm": "sales, business development, account management, partnerships, customer success",
    "marketing": "marketing, growth, brand, communications",
    "finance": "banking, investing, private equity, venture, asset management, insurance, accounting",
    "consulting": "management or strategy consulting, advisory client work",
    "research": "academic or scientific research, faculty, PhD",
    "operations": "operations, program or project management, supply chain, onboarding",
    "legal": "lawyers, counsel, paralegals, law clerks",
    "healthcare": "physicians, nurses, clinical roles",
    "education": "teachers and instructors at schools",
    "student_intern": "current students, interns, teaching or course assistants, club members",
    "leadership": "founders, executives, directors with no clear function",
    "other": "anything that is not a job, or truly unclear",
}

# Words too common in company names to suggest two names are the same company.
GENERIC_TOKENS = {
    "the", "of", "and", "&", "a", "consulting", "group", "capital", "partners", "management",
    "holdings", "holding", "university", "school", "college", "international", "company",
    "companies", "investments", "investment", "advisors", "advisory", "securities", "bank",
    "banking", "corporate", "global", "solutions", "services", "technologies", "technology",
    "systems", "health", "healthcare", "financial", "finance", "fund", "funds", "ventures",
    "labs", "lab", "ai", "inc", "llc", "ltd", "co", "corp", "public", "schools", "new", "york",
    "america", "american", "national", "center", "institute", "foundation", "club", "network",
    "media", "digital", "data", "software", "energy", "real", "estate", "asset", "assets",
    "equity", "private", "strategy", "strategies", "markets", "trading", "insurance", "llp", "lp",
    # filler and place words that caused false candidates on real data
    "first", "state", "states", "united", "center", "centre", "academy", "alliance", "associates",
    "association", "innovation", "innovations", "department", "air", "guard", "hospital", "medical",
    "general", "mortgage", "county", "city", "union", "society", "office", "graduate", "business",
    "law", "firm", "studio", "studios", "research", "science", "sciences", "education", "trust",
    "agency", "council", "project", "initiative", "boston", "georgia", "massachusetts", "texas",
    "california", "chicago", "london", "nyc", "china", "india", "europe", "world", "north", "south",
    "east", "west", "red", "big", "group", "partner", "school", "for",
}

TITLE_BATCH_SIZE = 20
MAX_CANDIDATES = 5
