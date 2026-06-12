import os, json, yaml
from pathlib import Path
from typing import Optional
from datetime import datetime

from ..config import settings

SKILLS_DIR = settings.SKILLS_DIR

# 8 preset skills (cannot be deleted, only toggled)
PRESET_SKILLS = [
    {"id": "academic-researcher", "display_name": "学术研究助手", "description": "文献检索与分析", "category": "core", "enabled": True, "agents": ["researcher"]},
    {"id": "systematic-literature-review", "display_name": "系统文献综述", "description": "系统文献综述流水线", "category": "core", "enabled": True, "agents": ["synthesizer"]},
    {"id": "scientific-thinking-literature-review", "display_name": "科学思维文献综述", "description": "科学思维文献综述", "category": "advanced", "enabled": True, "agents": ["reviewer"]},
    {"id": "nature-polishing", "display_name": "Nature级学术润色", "description": "Nature风格学术语言润色", "category": "advanced", "enabled": False, "agents": ["polisher"]},
    {"id": "reduce-aigc-rate", "display_name": "降低AIGC检测率", "description": "降低AI生成内容检测率", "category": "utility", "enabled": False, "agents": ["polisher"]},
    {"id": "nature-writing", "display_name": "Nature风格学术写作", "description": "Nature风格学术写作辅助", "category": "advanced", "enabled": False, "agents": ["polisher"]},
    {"id": "nature-citation", "display_name": "Nature引用管理", "description": "Nature格式引用管理", "category": "auxiliary", "enabled": False, "agents": ["architect"]},
    {"id": "nature-figure", "display_name": "Nature图表生成", "description": "Nature级学术图表生成", "category": "auxiliary", "enabled": True, "agents": ["researcher", "architect"]},
]

PRESET_IDS = {s["id"] for s in PRESET_SKILLS}


class SkillsService:
    """技能管理服务

    Args:
        repository: 可选，SkillRepository 实例。提供后使用 DB 模式，否则使用文件模式。
    """

    def __init__(self, repository=None):
        self.repository = repository
        self._use_db = repository is not None

    def list_all(self) -> list:
        """Return preset + custom skills"""
        preset = [dict(s) for s in PRESET_SKILLS]
        custom = self._load_custom_skills()
        return preset + custom

    def get_skill(self, skill_id: str) -> dict | None:
        """Get single skill by id"""
        # Check presets first
        for s in PRESET_SKILLS:
            if s["id"] == skill_id:
                return dict(s)
        # Then check custom
        for s in self._load_custom_skills():
            if s["id"] == skill_id:
                return s
        return None

    def create_skill(self, skill_data: dict) -> dict:
        """Create custom skill, save .md file"""
        skill_id = skill_data.get("id", "")
        if not skill_id:
            raise ValueError("技能 id 不能为空")
        if skill_id in PRESET_IDS:
            raise ValueError("不能使用预设技能的 id")
        # Check duplicate in custom skills
        existing = self._load_custom_skills()
        if any(s["id"] == skill_id for s in existing):
            raise ValueError(f"技能 id '{skill_id}' 已存在")

        now = datetime.now().isoformat()
        skill = {
            "id": skill_id,
            "display_name": skill_data.get("display_name", skill_id),
            "description": skill_data.get("description", ""),
            "category": skill_data.get("category", "custom"),
            "enabled": skill_data.get("enabled", True),
            "agents": skill_data.get("agents", []),
            "triggers": skill_data.get("triggers", []),
            "rules": skill_data.get("rules", ""),
            "is_preset": False,
            "created_at": now,
            "updated_at": now,
        }
        self._save_skill_file(skill)
        return skill

    def update_skill(self, skill_id: str, skill_data: dict) -> dict:
        """Update custom skill"""
        if skill_id in PRESET_IDS:
            raise ValueError("预设技能不能修改，只能切换启用状态")
        existing = self._load_custom_skills()
        target = None
        for s in existing:
            if s["id"] == skill_id:
                target = s
                break
        if target is None:
            raise ValueError(f"技能 '{skill_id}' 不存在")

        # Update fields
        for key in ("display_name", "description", "category", "agents", "triggers", "rules"):
            if key in skill_data and skill_data[key] is not None:
                target[key] = skill_data[key]
        target["updated_at"] = datetime.now().isoformat()

        self._save_skill_file(target)
        return target

    def delete_skill(self, skill_id: str) -> bool:
        """Delete custom skill (not preset)"""
        if skill_id in PRESET_IDS:
            raise ValueError("预设技能不能删除")
        filepath = Path(SKILLS_DIR) / f"{skill_id}.md"
        if not filepath.exists():
            return False
        filepath.unlink()
        return True

    def toggle_skill(self, skill_id: str, enabled: bool) -> dict:
        """Toggle enabled state for any skill"""
        # For preset skills, update in-memory state
        for s in PRESET_SKILLS:
            if s["id"] == skill_id:
                s["enabled"] = enabled
                return dict(s)
        # For custom skills, update file
        existing = self._load_custom_skills()
        for s in existing:
            if s["id"] == skill_id:
                s["enabled"] = enabled
                s["updated_at"] = datetime.now().isoformat()
                self._save_skill_file(s)
                return s
        raise ValueError(f"技能 '{skill_id}' 不存在")

    def upload_skill_file(self, file_content: bytes, filename: str) -> dict:
        """Parse uploaded .md skill file and save as custom skill"""
        # Save temporarily then parse
        temp_dir = Path(SKILLS_DIR)
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Parse the content directly
        text = file_content.decode("utf-8", errors="replace")
        parsed = self._parse_skill_text(text, filename)

        # Assign id from filename if not in frontmatter
        if "id" not in parsed or not parsed["id"]:
            stem = Path(filename).stem
            parsed["id"] = stem

        if parsed["id"] in PRESET_IDS:
            raise ValueError("不能使用预设技能的 id")

        # Check duplicate
        existing = self._load_custom_skills()
        if any(s["id"] == parsed["id"] for s in existing):
            raise ValueError(f"技能 id '{parsed['id']}' 已存在")

        now = datetime.now().isoformat()
        parsed.setdefault("display_name", parsed["id"])
        parsed.setdefault("description", "")
        parsed.setdefault("category", "custom")
        parsed.setdefault("enabled", True)
        parsed.setdefault("agents", [])
        parsed.setdefault("triggers", [])
        parsed.setdefault("rules", "")
        parsed["is_preset"] = False
        parsed["created_at"] = now
        parsed["updated_at"] = now

        self._save_skill_file(parsed)
        return parsed

    def _save_skill_file(self, skill_data: dict) -> str:
        """Save skill as .md with YAML frontmatter"""
        skills_dir = Path(SKILLS_DIR)
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_id = skill_data["id"]
        filepath = skills_dir / f"{skill_id}.md"

        # Build frontmatter
        frontmatter = {
            "id": skill_id,
            "display_name": skill_data.get("display_name", ""),
            "description": skill_data.get("description", ""),
            "category": skill_data.get("category", "custom"),
            "enabled": skill_data.get("enabled", True),
            "agents": skill_data.get("agents", []),
            "triggers": skill_data.get("triggers", []),
            "is_preset": skill_data.get("is_preset", False),
            "created_at": skill_data.get("created_at", ""),
            "updated_at": skill_data.get("updated_at", ""),
        }

        rules = skill_data.get("rules", "")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("---\n")
            f.write(yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False))
            f.write("---\n\n")
            f.write(rules)

        return str(filepath)

    def _load_custom_skills(self) -> list:
        """Load all custom skills from data/skills/"""
        skills_dir = Path(SKILLS_DIR)
        if not skills_dir.exists():
            return []

        skills = []
        for fp in skills_dir.glob("*.md"):
            parsed = self._parse_skill_file(fp)
            if parsed is not None:
                skills.append(parsed)
        return skills

    def _parse_skill_file(self, filepath: Path) -> dict | None:
        """Parse .md skill file with YAML frontmatter"""
        try:
            text = filepath.read_text(encoding="utf-8")
            return self._parse_skill_text(text, filepath.name)
        except Exception:
            return None

    def _parse_skill_text(self, text: str, filename: str = "") -> dict | None:
        """Parse skill text with YAML frontmatter"""
        if not text.startswith("---"):
            # No frontmatter, treat entire content as rules
            return {
                "id": Path(filename).stem if filename else "",
                "rules": text.strip(),
            }

        # Split frontmatter and body
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        try:
            frontmatter = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None

        if not isinstance(frontmatter, dict):
            return None

        rules = parts[2].strip()

        skill = dict(frontmatter)
        skill["rules"] = rules
        skill["is_preset"] = frontmatter.get("is_preset", False)
        return skill
