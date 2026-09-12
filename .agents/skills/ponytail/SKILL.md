---
name: ponytail
description: Quick-reference cheatsheet and streamlined pattern recipes for maximum code reusability, consistent architecture, and efficient coding in ForensiX.
---

# Ponytail Coding Skill: Streamlined, High-Reusability Engineering

When writing new features, entities, or commands in ForensiX (Trace), follow the **Unified 5-Layer Pattern**. This pattern maximizes code reusability, minimizes boilerplate, and strictly adheres to `AGENTS.md`.

---

## The Unified 5-Layer Recipe

### 1. Domain Layer (`src/trace_core/domain/models/`)
Inherit from `BaseEntity` to gain `id` (UUID), `opened_at`, `updated_at`, and `is_deleted` with UTC enforcement.

```python
from trace_core.domain.common import BaseEntity


class EvidenceItem(BaseEntity):
    case_id: uuid.UUID
    evidence_number: str
    description: str
    source_type: str
```

---

### 2. DTO Layer (`src/trace_core/application/dto.py`)
Inherit from `BaseResponseDto` and `BaseFilterDto`.

```python
from trace_core.application.dto import BaseResponseDto, BaseFilterDto


class EvidenceResponseDto(BaseResponseDto):
    evidence_number: str
    description: str


class EvidenceFilterDto(BaseFilterDto):
    source_type: str | None = None
```

---

### 3. Repository Layer (`src/trace_core/adapters/db/repositories/`)
Inherit from `SqlAlchemyBaseRepository[ModelT, EntityT, IdT]`.
You get `create()`, `get_by_id()`, `list_all()`, `update()`, `delete()`, `exists()`, and `count()` automatically!

```python
class SqlAlchemyEvidenceRepository(SqlAlchemyBaseRepository[EvidenceModel, EvidenceItem, uuid.UUID]):
    def __init__(self, session: Session):
        super().__init__(session=session, model_cls=EvidenceModel)

    def _to_domain(self, model: EvidenceModel) -> EvidenceItem: ...
    def _to_model(self, entity: EvidenceItem) -> EvidenceModel: ...
    def _update_model(self, model: EvidenceModel, entity: EvidenceItem) -> None: ...
```

---

### 4. Application Service Layer (`src/trace_core/application/`)
Inherit from `BaseService`.

```python
from trace_core.application.base import BaseService


class EvidenceService(BaseService):
    def get_evidence(self, identifier: str) -> EvidenceResponseDto:
        with self.session_manager.session() as session:
            repo = SqlAlchemyEvidenceRepository(session)
            item = repo.resolve(identifier)
            if not item:
                raise NotFoundError("Evidence", identifier)
            return EvidenceResponseDto.from_domain(item)
```

---

### 5. Presentation / CLI Layer (`src/trace_core/cli/commands/`)
Use `capture_cli_errors` to eliminate duplicate try/except blocks and guarantee standardized error cards and exit codes.

```python
from trace_core.cli.error_handler import capture_cli_errors


@app.command("show")
def show_evidence(identifier: str = typer.Argument(...)) -> None:
    """Show evidence details."""
    with capture_cli_errors("Show Evidence"):
        service = _get_service()
        item = service.get_evidence(identifier)
        render_entity_panel("Evidence Item", [("Number", item.evidence_number)])
```

---

## Forensic TUI Design System & Color Palette (`src/trace_core/cli/ui/theme.py`)

Always use `THEME_TOKENS` rather than raw or bright terminal colors:

```python
from trace_core.cli.ui.theme import THEME_TOKENS
```

| Token Role | Color Token | Hex / Style | Usage |
| :--- | :--- | :--- | :--- |
| **Card Borders** | `THEME_TOKENS["border_card"]` | `#273442` | Inner sub-panels, tables, and dividers |
| **Outer Border** | `THEME_TOKENS["border_outer"]` | `#3A4A5A` | Master dossier frame |
| **Active / Highlight** | `THEME_TOKENS["border_primary"]` | `#4F7FAF` | Focused elements, wizard active steps |
| **Alert Border** | `THEME_TOKENS["border_alert"]` | `#A85D66` | Restrained error cards |
| **Hero Title** | `THEME_TOKENS["title_hero"]` | `bold #E8EEF5` | Neutral white headings |
| **Section Headings**| `THEME_TOKENS["section_title"]` | `bold #72B7D3` | Soft cyan section titles & case numbers |
| **Labels** | `THEME_TOKENS["label"]` | `#AAB7C5` | Secondary muted gray labels |
| **Values / Data** | `THEME_TOKENS["value"]` | `#E5EAF0` | High-contrast neutral white values |
| **Muted Info** | `THEME_TOKENS["muted"]` | `#687786` | Low-emphasis information, colons |
| **Search Tags** | `THEME_TOKENS["tag"]` | `#6FA8B8` | Desaturated cyan tag pills |
| **Status: Open** | `THEME_TOKENS["status_open"]` | `bold #5FD18A` | Soft green operational state |
| **Status: Review** | `THEME_TOKENS["status_review"]` | `bold #D8B56A` | Soft amber review state |
| **Status: Closed** | `THEME_TOKENS["status_closed"]` | `bold #A88BD6` | Soft violet closed state |
| **Status: Danger** | `THEME_TOKENS["status_archived"]`| `bold #D06A73` | Muted red deleted state |

### Visual Hierarchy Rules
- **Blue-gray (`#273442` / `#3A4A5A`)** $\to$ Structure and borders
- **Soft cyan (`#72B7D3`)** $\to$ Information / section headings
- **Bright neutral white (`#E5EAF0`)** $\to$ Actual forensic data
- **Muted gray (`#AAB7C5` / `#687786`)** $\to$ Labels, colons, secondary details
- **Restrained accents** $\to$ Green (`#5FD18A`), Amber (`#D8B56A`), Violet (`#A88BD6`), Muted Red (`#D06A73`)
