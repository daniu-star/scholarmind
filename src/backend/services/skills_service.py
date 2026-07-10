import yaml
import structlog
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import settings

logger = structlog.get_logger(__name__)

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


def _now_iso() -> str:
    """统一的当前时间 ISO 字符串(使用 timezone.utc 替代 utcnow)"""
    return datetime.now(timezone.utc).isoformat()


def _skill_orm_to_dict(skill_orm) -> dict:
    """将 Skill ORM 对象转换为字典(供 DB 模式使用)"""
    return {
        "id": skill_orm.skill_id,
        "display_name": skill_orm.display_name,
        "description": skill_orm.description or "",
        "category": skill_orm.category or "custom",
        "enabled": skill_orm.enabled,
        "agents": skill_orm.agents or [],
        "triggers": skill_orm.triggers or [],
        "rules": skill_orm.rules or "",
        "is_preset": skill_orm.is_preset,
        "created_at": skill_orm.created_at.isoformat() if skill_orm.created_at else "",
        "updated_at": skill_orm.updated_at.isoformat() if skill_orm.updated_at else "",
    }


class SkillsService:
    """技能管理服务(支持 DB 模式 + 文件模式降级)

    Args:
        repository: 可选,SkillRepository 实例。提供后使用 DB 模式,否则使用文件模式。

    注意:
        DB 模式下方法为异步(async),文件模式为同步。
        调用方应使用 `await service.method()` 统一调用,
        文件模式下 async 方法会直接返回结果(通过 asyncio 兼容)。
    """

    def __init__(self, repository=None):
        self.repository = repository
        self._use_db = repository is not None

    # ── 查询方法 ──────────────────────────────────────────────

    async def list_all(self) -> list:
        """返回预设 + 自定义技能列表(DB 模式合并 DB 中的自定义技能)"""
        # 预设技能始终从内存加载(保证一致性)
        preset = [dict(s) for s in PRESET_SKILLS]

        if self._use_db:
            # DB 模式:从数据库加载所有非预设技能
            try:
                from ..models.orm import Skill
                from sqlalchemy import select

                result = await self.repository.db.execute(
                    select(Skill).where(not Skill.is_preset)
                )
                db_custom = result.scalars().all()
                custom = [_skill_orm_to_dict(s) for s in db_custom]

                # 同时同步预设技能的 enabled 状态(从 DB 读取最新状态)
                db_presets_result = await self.repository.db.execute(
                    select(Skill).where(Skill.is_preset)
                )
                db_presets = {s.skill_id: s for s in db_presets_result.scalars().all()}
                for p in preset:
                    if p["id"] in db_presets:
                        p["enabled"] = db_presets[p["id"]].enabled
            except Exception as e:
                # DB 异常时降级到文件模式
                logger.warning("list_all DB 查询失败，降级到文件模式: %s", e)
                custom = self._load_custom_skills()
        else:
            custom = self._load_custom_skills()

        return preset + custom

    async def get_skill(self, skill_id: str) -> dict | None:
        """根据 id 获取单个技能"""
        # 先查预设
        for s in PRESET_SKILLS:
            if s["id"] == skill_id:
                result = dict(s)
                # DB 模式下同步 enabled 状态
                if self._use_db:
                    try:
                        db_skill = await self.repository.get_by_skill_id(skill_id)
                        if db_skill is not None:
                            result["enabled"] = db_skill.enabled
                    except Exception as e:
                        logger.warning("get_skill 同步预设 enabled 状态失败 (%s): %s", skill_id, e)
                return result

        # 再查自定义
        if self._use_db:
            try:
                db_skill = await self.repository.get_by_skill_id(skill_id)
                if db_skill is not None:
                    return _skill_orm_to_dict(db_skill)
            except Exception as e:
                logger.warning("get_skill DB 查询自定义技能失败 (%s): %s", skill_id, e)

        # 降级到文件模式
        for s in self._load_custom_skills():
            if s["id"] == skill_id:
                return s
        return None

    # ── 写入方法 ──────────────────────────────────────────────

    async def create_skill(self, skill_data: dict) -> dict:
        """创建自定义技能"""
        skill_id = skill_data.get("id", "")
        if not skill_id:
            raise ValueError("技能 id 不能为空")
        if skill_id in PRESET_IDS:
            raise ValueError("不能使用预设技能的 id")

        # 检查重复
        if self._use_db:
            try:
                existing = await self.repository.get_by_skill_id(skill_id)
                if existing is not None:
                    raise ValueError(f"技能 id '{skill_id}' 已存在")
            except ValueError:
                raise
            except Exception as e:
                logger.warning("create_skill 重复检查失败 (%s): %s", skill_id, e)

        # 文件模式也要检查
        file_existing = self._load_custom_skills()
        if any(s["id"] == skill_id for s in file_existing):
            raise ValueError(f"技能 id '{skill_id}' 已存在")

        now = _now_iso()
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

        # DB 模式:写入数据库
        if self._use_db:
            try:
                from ..models.orm import Skill

                new_skill = Skill(
                    skill_id=skill_id,
                    display_name=skill["display_name"],
                    description=skill["description"],
                    category=skill["category"],
                    enabled=skill["enabled"],
                    agents=skill["agents"],
                    triggers=skill["triggers"],
                    rules=skill["rules"],
                    is_preset=False,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                self.repository.db.add(new_skill)
                await self.repository.db.flush()
                return skill
            except Exception as e:
                # DB 失败降级到文件
                logger.warning("create_skill DB 写入失败 (%s)，降级到文件: %s", skill_id, e)

        # 文件模式:保存 .md 文件
        self._save_skill_file(skill)
        return skill

    async def update_skill(self, skill_id: str, skill_data: dict) -> dict:
        """更新自定义技能"""
        if skill_id in PRESET_IDS:
            raise ValueError("预设技能不能修改,只能切换启用状态")

        # DB 模式
        if self._use_db:
            try:
                from ..models.orm import Skill

                result = await self.repository.db.execute(
                    select(Skill).where(Skill.skill_id == skill_id)
                )
                target = result.scalar_one_or_none()
                if target is not None:
                    for key in ("display_name", "description", "category", "agents", "triggers", "rules"):
                        if key in skill_data and skill_data[key] is not None:
                            setattr(target, key, skill_data[key])
                    target.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await self.repository.db.flush()
                    return _skill_orm_to_dict(target)
            except Exception as e:
                logger.warning("update_skill DB 更新失败 (%s)，降级到文件: %s", skill_id, e)

        # 文件模式降级
        existing = self._load_custom_skills()
        target = None
        for s in existing:
            if s["id"] == skill_id:
                target = s
                break
        if target is None:
            raise ValueError(f"技能 '{skill_id}' 不存在")

        for key in ("display_name", "description", "category", "agents", "triggers", "rules"):
            if key in skill_data and skill_data[key] is not None:
                target[key] = skill_data[key]
        target["updated_at"] = _now_iso()

        self._save_skill_file(target)
        return target

    async def delete_skill(self, skill_id: str) -> bool:
        """删除自定义技能(不能删除预设)"""
        if skill_id in PRESET_IDS:
            raise ValueError("预设技能不能删除")

        deleted = False

        # DB 模式
        if self._use_db:
            try:
                from ..models.orm import Skill

                result = await self.repository.db.execute(
                    select(Skill).where(Skill.skill_id == skill_id)
                )
                target = result.scalar_one_or_none()
                if target is not None:
                    await self.repository.db.delete(target)
                    await self.repository.db.flush()
                    deleted = True
            except Exception as e:
                logger.warning("delete_skill DB 删除失败 (%s): %s", skill_id, e)

        # 文件模式(无论 DB 是否成功,都尝试删除文件)
        filepath = Path(SKILLS_DIR) / f"{skill_id}.md"
        if filepath.exists():
            filepath.unlink()
            deleted = True

        return deleted

    async def toggle_skill(self, skill_id: str, enabled: bool) -> dict:
        """切换技能启用状态(预设和自定义均可)"""
        # 预设技能
        for s in PRESET_SKILLS:
            if s["id"] == skill_id:
                s["enabled"] = enabled
                # DB 模式下同步到数据库
                if self._use_db:
                    try:
                        await self.repository.toggle_enabled(skill_id, enabled)
                    except Exception as e:
                        logger.warning("toggle_skill 预设同步 DB 失败 (%s): %s", skill_id, e)
                return dict(s)

        # 自定义技能
        if self._use_db:
            try:
                db_skill = await self.repository.toggle_enabled(skill_id, enabled)
                if db_skill is not None:
                    return _skill_orm_to_dict(db_skill)
            except Exception as e:
                logger.warning("toggle_skill 自定义 DB 失败 (%s)，降级到文件: %s", skill_id, e)

        # 文件模式降级
        existing = self._load_custom_skills()
        for s in existing:
            if s["id"] == skill_id:
                s["enabled"] = enabled
                s["updated_at"] = _now_iso()
                self._save_skill_file(s)
                return s
        raise ValueError(f"技能 '{skill_id}' 不存在")

    async def upload_skill_file(self, file_content: bytes, filename: str) -> dict:
        """解析上传的 .md 技能文件并保存为自定义技能"""
        temp_dir = Path(SKILLS_DIR)
        temp_dir.mkdir(parents=True, exist_ok=True)

        text = file_content.decode("utf-8", errors="replace")
        parsed = self._parse_skill_text(text, filename)

        if "id" not in parsed or not parsed["id"]:
            stem = Path(filename).stem
            parsed["id"] = stem

        if parsed["id"] in PRESET_IDS:
            raise ValueError("不能使用预设技能的 id")

        # 检查重复(DB + 文件)
        if self._use_db:
            try:
                existing = await self.repository.get_by_skill_id(parsed["id"])
                if existing is not None:
                    raise ValueError(f"技能 id '{parsed['id']}' 已存在")
            except ValueError:
                raise
            except Exception as e:
                logger.warning("upload_skill_file 重复检查失败 (%s): %s", parsed["id"], e)

        file_existing = self._load_custom_skills()
        if any(s["id"] == parsed["id"] for s in file_existing):
            raise ValueError(f"技能 id '{parsed['id']}' 已存在")

        now = _now_iso()
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

        # DB 模式优先写入
        if self._use_db:
            try:
                from ..models.orm import Skill

                new_skill = Skill(
                    skill_id=parsed["id"],
                    display_name=parsed["display_name"],
                    description=parsed["description"],
                    category=parsed["category"],
                    enabled=parsed["enabled"],
                    agents=parsed["agents"],
                    triggers=parsed["triggers"],
                    rules=parsed["rules"],
                    is_preset=False,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                self.repository.db.add(new_skill)
                await self.repository.db.flush()
                return parsed
            except Exception as e:
                logger.warning("upload_skill_file DB 写入失败 (%s)，降级到文件: %s", parsed["id"], e)

        # 文件模式
        self._save_skill_file(parsed)
        return parsed

    # ── 同步辅助方法(文件模式专用) ────────────────────────────

    def _save_skill_file(self, skill_data: dict) -> str:
        """保存技能为 .md 文件(YAML frontmatter)"""
        skills_dir = Path(SKILLS_DIR)
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_id = skill_data["id"]
        filepath = skills_dir / f"{skill_id}.md"

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
        """从 data/skills/ 加载所有自定义技能"""
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
        """解析 .md 技能文件(YAML frontmatter)"""
        try:
            text = filepath.read_text(encoding="utf-8")
            return self._parse_skill_text(text, filepath.name)
        except Exception as e:
            logger.warning("解析技能文件失败 (%s): %s", filepath, e)
            return None

    def _parse_skill_text(self, text: str, filename: str = "") -> dict | None:
        """解析技能文本(YAML frontmatter + Markdown body)"""
        if not text.startswith("---"):
            return {
                "id": Path(filename).stem if filename else "",
                "rules": text.strip(),
            }

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        try:
            frontmatter = yaml.safe_load(parts[1])
        except yaml.YAMLError as e:
            logger.warning("YAML 解析失败 (%s): %s", filename, e)
            return None

        if not isinstance(frontmatter, dict):
            return None

        rules = parts[2].strip()

        skill = dict(frontmatter)
        skill["rules"] = rules
        skill["is_preset"] = frontmatter.get("is_preset", False)
        return skill
