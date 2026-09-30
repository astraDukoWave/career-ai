"""Unit tests for app.services.cv_format (pure functions, no network)."""

from app.services.cv_format import clean_bullet, normalize_skills

# The exact one-liner from a real CV generated on 2026-09-28. The old
# frontend split it on every "/", which broke groups into orphan fragments.
REAL_ONE_LINER = (
    "Core Frontend: React.js, TypeScript, JavaScript (ES6+), Next.js, HTML5, CSS3, "
    "Tailwind CSS, Vite, Component Libraries (ShadcnUI, Material UI) / AI & Automation "
    "Tools: Context Engineering, Advanced Prompt Engineering, Cursor, Replit, V0, N8N, "
    "LLM API Integration (OpenAI / Anthropic / Google AI), AI Agents & Chatbots / State & "
    "Data Management: React Query (TanStack Query), Zustand, Zod (schema validation), "
    "Context API, React Hooks / Backend & Cloud: Node.js, Express, Python FastAPI, "
    "Supabase, Vercel, Render, Replit Deployments, RESTful APIs, PostgreSQL, Redis / "
    "CI/CD & Testing: GitHub Actions, Git, Jest, Vitest, Cypress, Playwright, Docker, "
    "Nx Monorepos / Workflow & Methodologies: Agile/Scrum, Rapid Prototyping "
    '("Speed over perfection"), Back-Office & CRM Workflow Integration.'
)


def test_real_one_liner_keeps_groups_and_parentheses_intact():
    layout = normalize_skills([REAL_ONE_LINER])

    assert [g.label for g in layout.groups] == [
        "Core Frontend",
        "AI & Automation Tools",
        "State & Data Management",
        "Backend & Cloud",
        "CI/CD & Testing",
        "Workflow & Methodologies",
    ]
    assert layout.ungrouped == []
    items = {g.label: g.items for g in layout.groups}
    assert "Component Libraries (ShadcnUI, Material UI)" in items["Core Frontend"]
    assert "LLM API Integration (OpenAI / Anthropic / Google AI)" in items["AI & Automation Tools"]
    assert items["Workflow & Methodologies"] == [
        "Agile/Scrum",
        'Rapid Prototyping ("Speed over perfection")',
        "Back-Office & CRM Workflow Integration",
    ]


def test_one_group_per_line():
    layout = normalize_skills(["Frontend: React, TypeScript", "Backend: Python, FastAPI"])
    assert [(g.label, g.items) for g in layout.groups] == [
        ("Frontend", ["React", "TypeScript"]),
        ("Backend", ["Python", "FastAPI"]),
    ]


def test_plain_comma_list_has_no_groups():
    layout = normalize_skills(["Python, FastAPI, React"])
    assert layout.groups == []
    assert layout.ungrouped == ["Python", "FastAPI", "React"]


def test_slash_inside_skill_names_is_not_a_separator():
    layout = normalize_skills(["CI/CD, HTML5/CSS3, Agile/Scrum"])
    assert layout.ungrouped == ["CI/CD", "HTML5/CSS3", "Agile/Scrum"]


def test_unlabelled_part_continues_a_group_only_within_its_line():
    layout = normalize_skills(["Frontend: React / Next.js", "Git, Docker"])
    assert [(g.label, g.items) for g in layout.groups] == [("Frontend", ["React", "Next.js"])]
    assert layout.ungrouped == ["Git", "Docker"]


def test_duplicates_are_dropped_case_insensitively():
    layout = normalize_skills(["Frontend: React, react", "Tools: Docker, REACT"])
    assert layout.flat == ["React", "Docker"]


def test_urls_are_not_mistaken_for_labels():
    layout = normalize_skills(["https://github.com/example"])
    assert layout.groups == []
    assert layout.ungrouped == ["https://github.com/example"]


def test_clean_bullet_strips_markers_and_markdown_bold():
    assert clean_bullet("* Tech Stack: React, TypeScript.") == "Tech Stack: React, TypeScript."
    assert clean_bullet("    * Implemented natural language UI") == "Implemented natural language UI"
    assert clean_bullet("• Led migration") == "Led migration"
    assert clean_bullet("- Built X") == "Built X"
    assert clean_bullet("1. Shipped Y") == "Shipped Y"
    assert clean_bullet("**Impact:** cut latency 40%") == "Impact: cut latency 40%"


def test_clean_bullet_keeps_leading_numbers_and_drops_marker_only_lines():
    assert clean_bullet("2.5M users served") == "2.5M users served"
    assert clean_bullet("-10% cloud cost") == "-10% cloud cost"
    assert clean_bullet("*") == ""
    assert clean_bullet("  -  ") == ""


def test_clean_inline_strips_markdown_and_spaces_parentheses():
    from app.services.cv_format import clean_inline

    assert clean_inline("Performant **Frontend Developer** with **React**") == (
        "Performant Frontend Developer with React"
    )
    assert clean_inline("Universidad del Valle de México(UVM)") == "Universidad del Valle de México (UVM)"
    assert clean_inline("Built a useEffect(x) hook") == "Built a useEffect(x) hook"
    assert clean_inline(None) is None


def test_format_month_renders_iso_months_and_keeps_free_text():
    from app.services.cv_format import format_month

    assert format_month("2026-5") == "May 2026"
    assert format_month(" 2026-01 ") == "Jan 2026"
    assert format_month("2026-13") == "2026-13"
    assert format_month("Jan 2022") == "Jan 2022"
    assert format_month("Present") == "Present"
    assert format_month("2027") == "2027"


def test_format_month_and_present_follow_the_cv_language():
    from app.services.cv_format import format_month, section_titles

    assert format_month("2026-01", "es") == "Ene 2026"
    assert format_month("2026-8", "es") == "Ago 2026"
    assert format_month("Present", "es") == "Actualidad"
    assert format_month("presente", "en") == "Present"
    assert format_month("egreso estimado 2027", "es") == "egreso estimado 2027"
    assert section_titles("es")["education"] == "Educación"
    assert section_titles("fr") == section_titles("en")


def test_long_spanish_group_label_is_still_a_label():
    layout = normalize_skills(["Automatización e integración de herramientas: GitHub Actions, Celery"])
    assert [(g.label, g.items) for g in layout.groups] == [
        ("Automatización e integración de herramientas", ["GitHub Actions", "Celery"])
    ]
    assert layout.ungrouped == []
