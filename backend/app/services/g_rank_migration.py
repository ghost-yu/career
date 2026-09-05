from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db import sqlite as db
from app.services.behavior_recommend import build_student_behavior_profile, normalize_strategy, rerank_job_items
from app.services.skill_proficiency import (
    DEFAULT_JOB_LEVEL,
    infer_required_proficiency_from_text,
    infer_student_proficiency_from_evidence,
    merge_proficiency_with_verification,
    proficiency_info,
)
from app.utils.labels import enrich_job_labels
from app.utils.text import normalize_token


EMPTY_JOB_POOL_RESULT = {
    "status": "empty_job_pool",
    "message": "当前暂无岗位数据，请先导入岗位并生成岗位画像",
    "items": [],
    "diagnostics": {
        "jobs_total": 0,
        "job_profiles_total": 0,
        "student_profile_source": "missing",
    },
}

DEFAULT_EMBEDDING_MODEL = os.getenv("G_RANK_EMBEDDING_MODEL", "moka-ai/m3e-base")
DEFAULT_RERANKER_MODEL = os.getenv("G_RANK_RERANKER_MODEL", "BAAI/bge-reranker-base")
DEFAULT_MODEL_DEVICE = os.getenv("G_RANK_MODEL_DEVICE", "auto")
G_RANK_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "g_rank"
FAISS_INDEX_PATH = G_RANK_DATA_DIR / "jobs_m3e.index"
FAISS_META_PATH = G_RANK_DATA_DIR / "jobs_m3e.meta.json"
SEMANTIC_QUERY_LIMIT = 900
SEMANTIC_JOB_TEXT_LIMIT = 1400
BGE_PAIR_TEXT_LIMIT = 1400

_EMBEDDING_MODEL: Any | None = None
_EMBEDDING_MODEL_ERROR: str | None = None
_RERANKER_MODEL: Any | None = None
_RERANKER_MODEL_ERROR: str | None = None
_FAISS_INDEX_CACHE: dict[str, Any] = {}
_MODEL_DEVICE_LABEL = "unknown"

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/_-]{1,}|[\u4e00-\u9fff]{2,}")

JOB_FAMILY_ALIASES = {
    "后端": "backend",
    "服务端": "backend",
    "java": "backend",
    "前端": "frontend",
    "react": "frontend",
    "vue": "frontend",
    "人工智能": "ai",
    "大模型": "ai",
    "算法": "ai",
    "数据": "data",
    "数据分析": "data",
    "bi": "data",
    "测试": "qa",
    "运维": "ops",
    "安全": "security",
    "网络安全": "security",
    "实施": "implementation",
    "技术支持": "support",
    "产品": "product",
}

FAMILY_ADJACENT = {
    "ai": {"data", "backend", "research"},
    "data": {"ai", "backend", "product"},
    "backend": {"ai", "data", "ops", "security"},
    "frontend": {"mobile", "design", "product"},
    "design": {"frontend", "product"},
    "product": {"frontend", "design", "data"},
    "qa": {"backend", "ops", "implementation"},
    "ops": {"backend", "security", "implementation"},
    "security": {"backend", "ops", "qa"},
    "implementation": {"support", "qa", "ops", "product"},
    "support": {"implementation", "ops", "product"},
}

FAMILY_CORE_TERMS = {
    "ai": {
        "人工智能",
        "大模型",
        "机器学习",
        "深度学习",
        "神经网络",
        "pytorch",
        "tensorflow",
        "transformers",
        "langchain",
        "rag",
        "agent",
        "llm",
        "nlp",
        "计算机视觉",
        "模型训练",
        "模型微调",
    },
    "backend": {"java", "spring", "springboot", "springcloud", "mybatis", "后端", "服务端", "微服务", "redis", "mysql"},
    "frontend": {"前端", "vue", "react", "typescript", "javascript", "html", "css", "webpack", "vite"},
    "data": {"数据分析", "数据仓库", "hive", "spark", "flink", "sql", "bi", "tableau", "powerbi"},
    "security": {"安全", "网络安全", "渗透", "攻防", "漏洞", "等保", "应急响应", "burpsuite", "sqlmap", "nmap", "wireshark", "waf"},
    "qa": {"测试", "软件测试", "自动化测试", "功能测试", "性能测试", "接口测试", "selenium", "jmeter", "pytest"},
    "ops": {"运维", "linux", "docker", "kubernetes", "k8s", "devops", "sre", "监控", "告警", "jenkins"},
    "product": {"产品", "产品经理", "需求分析", "原型", "axure", "prd", "用户研究", "竞品分析"},
    "design": {"设计", "ui", "视觉", "交互", "figma", "photoshop", "illustrator", "sketch"},
    "implementation": {"实施", "交付", "部署", "客户现场", "项目实施", "系统实施", "培训"},
    "support": {"技术支持", "售前", "售后", "客户支持", "故障排查", "工单", "技术咨询"},
    "mobile": {"移动端", "android", "ios", "flutter", "reactnative", "uniapp", "小程序"},
}

HIGH_SIGNAL_TERMS = {
    "java",
    "python",
    "c++",
    "sql",
    "mysql",
    "redis",
    "docker",
    "kubernetes",
    "linux",
    "spring",
    "springboot",
    "springcloud",
    "vue",
    "react",
    "typescript",
    "javascript",
    "pytorch",
    "tensorflow",
    "机器学习",
    "深度学习",
    "大模型",
    "langchain",
    "rag",
    "agent",
    "burpsuite",
    "sqlmap",
    "wireshark",
    "nmap",
    "solidity",
    "区块链",
    "智能合约",
    "web3",
    "tableau",
    "powerbi",
    "spss",
}

SKILL_GRAPH_GROUPS = [
    {
        "cluster": "消息队列",
        "terms": {"rabbitmq", "kafka", "rocketmq", "消息队列", "mq", "amqp", "流处理"},
        "learning_path": ["消息队列基础", "RabbitMQ/Kafka/RocketMQ 任选其一", "可靠投递与消费确认", "削峰填谷项目实践"],
    },
    {
        "cluster": "Java后端框架",
        "terms": {"java", "spring", "springboot", "springcloud", "mybatis", "微服务", "后端", "服务端"},
        "learning_path": ["Java 基础", "Spring Boot REST API", "MyBatis + MySQL", "Redis/消息队列", "微服务拆分"],
    },
    {
        "cluster": "关系型数据库",
        "terms": {"mysql", "postgresql", "sql", "oracle", "数据库", "rdbms"},
        "learning_path": ["SQL 查询", "表结构设计", "索引优化", "事务与锁", "慢查询分析"],
    },
    {
        "cluster": "缓存与中间件",
        "terms": {"redis", "缓存", "cache", "memcached"},
        "learning_path": ["缓存基础", "Redis 数据结构", "缓存穿透/击穿/雪崩", "分布式锁实践"],
    },
    {
        "cluster": "前端工程",
        "terms": {"vue", "react", "typescript", "javascript", "前端", "webpack", "vite"},
        "learning_path": ["HTML/CSS/JS", "Vue 或 React", "TypeScript", "组件化项目", "工程化构建"],
    },
    {
        "cluster": "人工智能应用",
        "terms": {"python", "pytorch", "tensorflow", "机器学习", "深度学习", "大模型", "rag", "langchain", "agent"},
        "learning_path": ["Python 数据处理", "机器学习基础", "深度学习框架", "RAG 应用", "智能体项目"],
    },
    {
        "cluster": "安全攻防",
        "terms": {"burpsuite", "sqlmap", "wireshark", "nmap", "渗透", "漏洞", "安全", "网络安全"},
        "learning_path": ["网络基础", "Web 漏洞", "BurpSuite/SQLMap", "漏洞复现报告", "安全加固"],
    },
    {
        "cluster": "云原生运维",
        "terms": {"linux", "docker", "kubernetes", "k8s", "devops", "sre", "运维", "云平台"},
        "learning_path": ["Linux 基础", "Docker 镜像与容器", "CI/CD", "Kubernetes", "监控告警"],
    },
]

SKILL_GRAPH_INDEX: dict[str, dict[str, Any]] = {}
for _group in SKILL_GRAPH_GROUPS:
    for _term in _group["terms"]:
        _key = normalize_token(_term)
        if _key:
            SKILL_GRAPH_INDEX[_key] = _group

GENERIC_BROAD_PATTERNS = [
    "各语言都有hc",
    "岗位全",
    "均有岗位需求",
    "国内一线大厂开放职位",
    "前端后端开发算法ai运维安全",
    "java/c++/python/go",
]

AMBIGUOUS_SKILL_RULES = [
    {
        "term": "ai",
        "positive_context": {"人工智能", "大模型", "机器学习", "深度学习", "神经网络", "模型", "rag", "agent", "llm"},
        "negative_context": {"illustrator", "photoshop", "indesign", "ui", "视觉", "平面设计", "设计软件", "图标设计", "配色"},
    }
]

CN_STOPWORDS = {
    "岗位",
    "职位",
    "工作",
    "实习",
    "工程师",
    "能力",
    "经验",
    "要求",
    "负责",
    "熟悉",
    "掌握",
    "相关",
    "优先",
    "以及",
    "进行",
    "具有",
    "具备",
}


@dataclass
class GRankStudent:
    student_id: str
    hard_skills: list[str]
    soft_skills: list[str]
    certificates: list[str]
    preferred_locations: list[str]
    preferred_job_families: list[str]
    resume_text: str
    completeness_score: float
    competitiveness_score: float
    hard_skill_items: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass
class GRankJob:
    job_id: str
    title: str
    company_name: str
    location: str
    industry: str
    job_family: str
    description: str
    company_intro: str
    hard_skills: list[str]
    soft_skills: list[str]
    certificates: list[str]
    hard_skill_items: list[dict[str, Any]]
    raw: dict[str, Any]


def _tokenize(value: Any) -> list[str]:
    text = str(value or "").strip().lower()
    if not text:
        return []
    return [token for token in TOKEN_RE.findall(text) if token]


def _recall_tokens(value: Any) -> list[str]:
    raw = str(value or "").lower()
    tokens: list[str] = []
    for token in TOKEN_RE.findall(raw):
        key = normalize_token(token)
        if len(key) > 1 and key not in CN_STOPWORDS:
            tokens.append(key)
    compact_cn = "".join(re.findall(r"[\u4e00-\u9fff]+", raw))
    if len(compact_cn) >= 2:
        tokens.extend(compact_cn[i : i + 2] for i in range(len(compact_cn) - 1))
    return tokens


def _text_join(*parts: Any) -> str:
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _student_text(student: GRankStudent) -> str:
    return _text_join(
        student.resume_text,
        " ".join(student.hard_skills),
        " ".join(student.soft_skills),
        " ".join(student.certificates),
        " ".join(student.preferred_job_families),
        " ".join(student.preferred_locations),
    )


def _job_text(job: GRankJob) -> str:
    return _text_join(
        job.title,
        job.company_name,
        job.location,
        job.industry,
        job.description,
        job.company_intro,
        " ".join(job.hard_skills),
        " ".join(job.soft_skills),
        " ".join(job.certificates),
        job.job_family,
    )


def _clip_text(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit]


def _semantic_student_query(student: GRankStudent, query: str) -> str:
    return _clip_text(
        _text_join(
            query,
            student.resume_text,
            " ".join(student.hard_skills[:32]),
            " ".join(student.soft_skills[:16]),
            " ".join(student.certificates[:12]),
            " ".join(student.preferred_job_families[:8]),
            " ".join(student.preferred_locations[:8]),
        ),
        SEMANTIC_QUERY_LIMIT,
    )


def _semantic_job_text(job: GRankJob) -> str:
    return _clip_text(_job_text(job), SEMANTIC_JOB_TEXT_LIMIT)


def _bge_pair_text_for_student(student: GRankStudent, query: str) -> str:
    return _clip_text(_semantic_student_query(student, query), BGE_PAIR_TEXT_LIMIT)


def _bge_pair_text_for_job(job: GRankJob) -> str:
    return _clip_text(_job_text(job), BGE_PAIR_TEXT_LIMIT)


def _enable_offline_model_mode() -> None:
    # The competition demo should run from local cache; this avoids surprise network calls.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _resolve_model_device() -> str | None:
    global _MODEL_DEVICE_LABEL
    wanted = str(DEFAULT_MODEL_DEVICE or "auto").strip().lower()
    if wanted and wanted != "auto":
        _MODEL_DEVICE_LABEL = wanted
        return wanted
    try:
        import torch

        if torch.cuda.is_available():
            _MODEL_DEVICE_LABEL = "cuda"
            return "cuda"
    except Exception:
        pass
    _MODEL_DEVICE_LABEL = "cpu"
    return "cpu"


def _load_embedding_model() -> tuple[Any | None, str]:
    global _EMBEDDING_MODEL, _EMBEDDING_MODEL_ERROR
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL, "ok"
    if _EMBEDDING_MODEL_ERROR:
        return None, _EMBEDDING_MODEL_ERROR
    try:
        _enable_offline_model_mode()
        from sentence_transformers import SentenceTransformer

        _EMBEDDING_MODEL = SentenceTransformer(DEFAULT_EMBEDDING_MODEL, local_files_only=True, device=_resolve_model_device())
        return _EMBEDDING_MODEL, "ok"
    except Exception as exc:
        _EMBEDDING_MODEL_ERROR = f"{type(exc).__name__}: {str(exc)[:180]}"
        return None, _EMBEDDING_MODEL_ERROR


def _load_bge_reranker() -> tuple[Any | None, str]:
    global _RERANKER_MODEL, _RERANKER_MODEL_ERROR
    if _RERANKER_MODEL is not None:
        return _RERANKER_MODEL, "ok"
    if _RERANKER_MODEL_ERROR:
        return None, _RERANKER_MODEL_ERROR
    try:
        _enable_offline_model_mode()
        from sentence_transformers import CrossEncoder

        _RERANKER_MODEL = CrossEncoder(DEFAULT_RERANKER_MODEL, local_files_only=True, device=_resolve_model_device())
        return _RERANKER_MODEL, "ok"
    except Exception as exc:
        _RERANKER_MODEL_ERROR = f"{type(exc).__name__}: {str(exc)[:180]}"
        return None, _RERANKER_MODEL_ERROR


def prewarm_g_rank_models(*, build_index: bool = True, max_jobs: int = 20000) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "reranker_model": DEFAULT_RERANKER_MODEL,
        "device": _MODEL_DEVICE_LABEL,
        "build_index": bool(build_index),
    }
    _, embedding_reason = _load_embedding_model()
    stats["embedding_reason"] = embedding_reason
    _, reranker_reason = _load_bge_reranker()
    stats["reranker_reason"] = reranker_reason
    if build_index:
        jobs = _candidate_jobs(q=None, location=None, max_candidates=max(1, int(max_jobs or 20000)))
        _, job_ids, index_reason = _load_or_build_faiss_index(jobs)
        stats["index_reason"] = index_reason
        stats["index_jobs"] = len(job_ids)
        stats["candidate_jobs"] = len(jobs)
    stats["device"] = _MODEL_DEVICE_LABEL
    return stats


def _job_index_signature(jobs: list[GRankJob]) -> str:
    h = hashlib.sha1()
    for job in sorted(jobs, key=lambda x: x.job_id):
        h.update(job.job_id.encode("utf-8", errors="ignore"))
        h.update(b"\0")
        h.update(str(len(_semantic_job_text(job))).encode("ascii", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _read_faiss_meta() -> dict[str, Any] | None:
    try:
        if not FAISS_META_PATH.exists():
            return None
        return json.loads(FAISS_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_faiss_meta(meta: dict[str, Any]) -> None:
    G_RANK_DATA_DIR.mkdir(parents=True, exist_ok=True)
    FAISS_META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_or_build_faiss_index(jobs: list[GRankJob]) -> tuple[Any | None, list[str], str]:
    if not jobs:
        return None, [], "empty_jobs"
    model, reason = _load_embedding_model()
    if model is None:
        return None, [], f"embedding_unavailable:{reason}"
    try:
        import faiss
        import numpy as np
    except Exception as exc:
        return None, [], f"faiss_unavailable:{type(exc).__name__}: {str(exc)[:120]}"

    signature = _job_index_signature(jobs)
    cached = _FAISS_INDEX_CACHE.get(signature)
    if cached:
        return cached["index"], list(cached["job_ids"]), "memory_cache"

    meta = _read_faiss_meta()
    if meta and meta.get("signature") == signature and FAISS_INDEX_PATH.exists():
        try:
            index = faiss.read_index(str(FAISS_INDEX_PATH))
            job_ids = [str(x) for x in (meta.get("job_ids") or [])]
            if index.ntotal == len(job_ids) == len(jobs):
                _FAISS_INDEX_CACHE.clear()
                _FAISS_INDEX_CACHE[signature] = {"index": index, "job_ids": job_ids}
                return index, job_ids, "disk_cache"
        except Exception:
            pass

    texts = [_semantic_job_text(job) for job in jobs]
    try:
        vectors = model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        arr = np.asarray(vectors, dtype="float32")
        if arr.ndim != 2 or arr.shape[0] != len(jobs):
            return None, [], "embedding_shape_error"
        index = faiss.IndexFlatIP(int(arr.shape[1]))
        index.add(arr)
        job_ids = [job.job_id for job in jobs]
        G_RANK_DATA_DIR.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(FAISS_INDEX_PATH))
        _write_faiss_meta(
            {
                "signature": signature,
                "job_ids": job_ids,
                "model": DEFAULT_EMBEDDING_MODEL,
                "count": len(job_ids),
            }
        )
        _FAISS_INDEX_CACHE.clear()
        _FAISS_INDEX_CACHE[signature] = {"index": index, "job_ids": job_ids}
        return index, job_ids, "rebuilt"
    except Exception as exc:
        return None, [], f"build_failed:{type(exc).__name__}: {str(exc)[:160]}"


def _semantic_recall(student: GRankStudent, query: str, jobs: list[GRankJob], top_k: int) -> tuple[list[tuple[str, float]], dict[str, Any]]:
    index, job_ids, source = _load_or_build_faiss_index(jobs)
    if index is None or not job_ids:
        return [], {"semantic_enabled": False, "semantic_reason": source}
    model, reason = _load_embedding_model()
    if model is None:
        return [], {"semantic_enabled": False, "semantic_reason": reason}
    try:
        import numpy as np

        q_text = _semantic_student_query(student, query)
        if not q_text:
            return [], {"semantic_enabled": False, "semantic_reason": "empty_query"}
        q_vec = model.encode([q_text], show_progress_bar=False, normalize_embeddings=True)
        q_arr = np.asarray(q_vec, dtype="float32")
        search_k = max(1, min(len(job_ids), int(top_k)))
        scores, idxs = index.search(q_arr, search_k)
        rows: list[tuple[str, float]] = []
        for score, idx in zip(scores[0].tolist(), idxs[0].tolist()):
            if idx < 0 or idx >= len(job_ids):
                continue
            rows.append((job_ids[idx], float(score)))
        return rows, {"semantic_enabled": True, "semantic_reason": source}
    except Exception as exc:
        return [], {"semantic_enabled": False, "semantic_reason": f"search_failed:{type(exc).__name__}: {str(exc)[:140]}"}


def _company_key(name: str) -> str:
    text = normalize_token(name)
    for key, value in {
        "外企德科": "外企德科",
        "德科信息": "外企德科",
        "软通动力信息技术": "软通动力",
        "软通动力": "软通动力",
    }.items():
        if normalize_token(key) in text:
            return normalize_token(value)
    for suffix in ["信息技术有限公司", "数字技术有限公司", "科技有限公司", "技术有限公司", "股份有限公司", "有限公司", "集团", "分公司"]:
        text = text.replace(normalize_token(suffix), "")
    return text


def _duplicate_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            normalize_token(item.get("title")),
            _company_key(str(item.get("company_name") or "")),
        ]
    )


def _safe_terms(items: list[dict[str, Any]] | None, key: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        raw = str(item.get(key) or "").strip()
        token = normalize_token(raw)
        if not raw or not token or token in seen:
            continue
        seen.add(token)
        out.append(raw)
    return out


def _safe_profile_items(items: list[dict[str, Any]] | None, primary_key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get(primary_key) or item.get("name") or item.get("mention") or item.get("skill_id") or "").strip()
        key = normalize_token(name)
        if not name or not key or key in seen:
            continue
        seen.add(key)
        row = dict(item)
        row["_name"] = name
        out.append(row)
    return out


def _skill_group(term: str) -> dict[str, Any] | None:
    key = normalize_token(term)
    if not key:
        return None
    if key in SKILL_GRAPH_INDEX:
        return SKILL_GRAPH_INDEX[key]
    for token, group in SKILL_GRAPH_INDEX.items():
        if token and (token in key or key in token):
            return group
    return None


def _skill_relation(student_skill: str, job_skill: str) -> tuple[str, float, str]:
    s_key = normalize_token(student_skill)
    j_key = normalize_token(job_skill)
    if not s_key or not j_key:
        return "none", 0.0, ""
    if s_key == j_key or s_key in j_key or j_key in s_key:
        return "exact", 1.0, "技能名称直接命中"
    s_group = _skill_group(student_skill)
    j_group = _skill_group(job_skill)
    if s_group and j_group and s_group.get("cluster") == j_group.get("cluster"):
        return "transferable", 0.68, f"同属{j_group.get('cluster')}技能簇"
    return "none", 0.0, ""


def _infer_skill_proficiency(skill_name: str, skill_item: dict[str, Any] | None, resume_text: str) -> dict[str, Any]:
    info = infer_student_proficiency_from_evidence(skill_name, skill_item or {}, resume_text)
    return {
        "level": round(float(info.get("score") or 0.0), 2),
        "code": info.get("level"),
        "label": info.get("label"),
        "rank": info.get("rank"),
        "evidence": str(info.get("evidence") or "")[:180],
        "source": info.get("source"),
    }


def _infer_required_proficiency(skill_name: str, job: GRankJob) -> dict[str, Any]:
    for item in job.hard_skill_items or []:
        name = str(item.get("_name") or item.get("mention") or item.get("name") or "").strip()
        if name and normalize_token(name) == normalize_token(skill_name):
            explicit = item.get("proficiency") or item.get("level")
            if explicit:
                info = proficiency_info(explicit, default=DEFAULT_JOB_LEVEL)
                return {
                    "level": round(float(info.get("score") or 0.0), 2),
                    "code": info.get("level"),
                    "label": info.get("label"),
                    "rank": info.get("rank"),
                    "evidence": str(item.get("evidence") or "")[:180],
                }
    info = infer_required_proficiency_from_text(skill_name, _text_join(job.title, job.description, " ".join(job.hard_skills)), default=DEFAULT_JOB_LEVEL)
    return {
        "level": round(float(info.get("score") or 0.0), 2),
        "code": info.get("level"),
        "label": info.get("label"),
        "rank": info.get("rank"),
        "evidence": str(info.get("evidence") or "")[:180],
    }


def _build_skill_gap_paths(missing_skills: list[str]) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill in missing_skills[:8]:
        key = normalize_token(skill)
        if not key or key in seen:
            continue
        seen.add(key)
        group = _skill_group(skill)
        if group:
            steps = list(group.get("learning_path") or [])[:5]
            cluster = str(group.get("cluster") or "技能簇")
        else:
            steps = [f"补齐 {skill} 基础概念", f"完成 1 个包含 {skill} 的小项目", "把项目过程写入简历并补充量化结果"]
            cluster = "独立技能"
        paths.append({"target_skill": skill, "cluster": cluster, "steps": steps})
    return paths


def _counterfactual_actions(missing_skills: list[str], transferable: list[dict[str, Any]], current_score: float) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for idx, skill in enumerate(missing_skills[:5]):
        gain = max(3.0, 8.0 - idx * 1.2)
        actions.append(
            {
                "action": f"补齐 {skill} 并完成一个可展示项目",
                "target_skill": skill,
                "estimated_gain": round(gain, 1),
                "estimated_score_after": round(min(95.0, current_score + gain), 1),
            }
        )
    for row in transferable[:3]:
        to_skill = str(row.get("to_skill") or "").strip()
        if not to_skill:
            continue
        gain = 3.0
        actions.append(
            {
                "action": f"把已有 {row.get('from_skill')} 经验迁移到 {to_skill} 场景",
                "target_skill": to_skill,
                "estimated_gain": gain,
                "estimated_score_after": round(min(95.0, current_score + gain), 1),
            }
        )
    return actions[:6]


def _infer_query_families(student: GRankStudent, query: str, explicit_family: str | None = None) -> list[str]:
    found: list[str] = []
    explicit = str(explicit_family or "").strip().lower()
    if explicit:
        if explicit in JOB_FAMILY_ALIASES:
            explicit = JOB_FAMILY_ALIASES[explicit]
        if explicit and explicit not in found:
            found.append(explicit)
    query_text = normalize_token(query)
    for alias, family in JOB_FAMILY_ALIASES.items():
        if normalize_token(alias) in query_text and family not in found:
            found.append(family)
    if found:
        return found
    for family in student.preferred_job_families:
        if family and family not in found:
            found.append(family)
    return found


def load_student(student_id: str) -> GRankStudent | None:
    profile_row = db.get_student_profile(student_id)
    if not profile_row or not isinstance(profile_row.get("profile"), dict):
        return None
    profile = profile_row["profile"]
    prefs = profile.get("preferences") or {}
    return GRankStudent(
        student_id=str(student_id),
        hard_skills=_safe_terms(profile.get("hard_skills"), "mention"),
        soft_skills=_safe_terms(profile.get("soft_skills"), "name"),
        certificates=_safe_terms(profile.get("certificates"), "name"),
        preferred_locations=[str(x).strip() for x in (prefs.get("preferred_locations") or []) if str(x).strip()],
        preferred_job_families=[str(x).strip().lower() for x in (prefs.get("preferred_job_families") or []) if str(x).strip()],
        resume_text=str(profile.get("resume_text") or profile.get("profile_notes") or prefs.get("notes") or ""),
        completeness_score=float(profile.get("completeness_score") or 0.0),
        competitiveness_score=float(profile.get("competitiveness_score") or 0.0),
        hard_skill_items=_safe_profile_items(profile.get("hard_skills"), "mention"),
        raw=profile,
    )


def load_job(job_id: str) -> GRankJob | None:
    job = db.get_job(job_id)
    if not job:
        return None
    profile_row = db.get_job_profile(job_id)
    profile = (profile_row or {}).get("profile") or {}
    return GRankJob(
        job_id=str(job_id),
        title=str(job.get("title") or ""),
        company_name=str(job.get("company_name") or ""),
        location=str(job.get("location") or ""),
        industry=str(job.get("industry") or ""),
        job_family=str(profile.get("job_family") or "").strip().lower(),
        description=str(job.get("description") or ""),
        company_intro=str(job.get("company_intro") or ""),
        hard_skills=_safe_terms(profile.get("hard_skills"), "mention"),
        soft_skills=_safe_terms(profile.get("soft_skills"), "name"),
        certificates=_safe_terms(profile.get("certificates"), "name"),
        hard_skill_items=_safe_profile_items(profile.get("hard_skills"), "mention"),
        raw=job,
    )


def summarize_job_pool() -> dict[str, int]:
    return {
        "jobs_total": int(db.count_jobs()),
        "job_profiles_total": int(db.count_job_profiles()),
        "student_profiles_total": int(db.count_student_profiles()),
    }


def build_recommendation_payload(student_id: str) -> dict[str, Any]:
    student = load_student(student_id)
    stats = summarize_job_pool()
    if stats["jobs_total"] <= 0:
        out = dict(EMPTY_JOB_POOL_RESULT)
        out["diagnostics"] = {**out["diagnostics"], **stats}
        return out
    if student is None:
        return {
            "status": "missing_student_profile",
            "message": "当前学生画像不存在，请先生成学生画像",
            "items": [],
            "diagnostics": stats,
        }
    if stats["job_profiles_total"] <= 0:
        return {
            "status": "missing_job_profiles",
            "message": "岗位已导入，但岗位画像为空，请先批量生成岗位画像",
            "items": [],
            "diagnostics": stats,
        }
    return {
        "status": "ready",
        "student": student,
        "diagnostics": stats,
    }


def _weighted_overlap_tokens(text: str, tokens: list[str], weight: float) -> float:
    hay = normalize_token(text)
    score = 0.0
    for token in tokens:
        key = normalize_token(token)
        if key and key in hay:
            score += weight
    return score


def _anchor_bonus(student: GRankStudent, query: str, job: GRankJob) -> float:
    anchors = set()
    for term in student.hard_skills[:20] + _tokenize(query):
        key = normalize_token(term)
        if key in HIGH_SIGNAL_TERMS or any(ch in key for ch in ["安全", "漏洞", "防火墙", "区块链", "合约"]):
            anchors.add(key)
    hay = normalize_token(_job_text(job))
    bonus = 0.0
    for anchor in anchors:
        if anchor and anchor in hay:
            bonus += 8.0
    return min(32.0, bonus)


def _query_anchor_adjustment(query: str, job: GRankJob) -> tuple[float, list[str], list[str]]:
    anchors: list[str] = []
    seen: set[str] = set()
    for term in _tokenize(query):
        key = normalize_token(term)
        if not key or key in seen:
            continue
        if key in HIGH_SIGNAL_TERMS or key in JOB_FAMILY_ALIASES:
            seen.add(key)
            anchors.append(key)
    if not anchors:
        return 0.0, [], []
    hay = normalize_token(_text_join(job.title, job.description, " ".join(job.hard_skills), job.job_family))
    matched = [anchor for anchor in anchors if anchor in hay]
    missing = [anchor for anchor in anchors if anchor not in hay]
    score = min(16.0, len(matched) * 6.0)
    # For explicit tools/languages in the search box, absence is a strong relevance warning.
    hard_missing = [x for x in missing if x in HIGH_SIGNAL_TERMS]
    if hard_missing:
        score -= min(24.0, len(hard_missing) * 12.0)
    return score, matched, missing


def _location_match(student: GRankStudent, location: str, job: GRankJob) -> bool:
    wanted = [str(location).strip()] if str(location or "").strip() else student.preferred_locations
    if not wanted:
        return True
    loc = normalize_token(job.location)
    return any(normalize_token(city) in loc for city in wanted if normalize_token(city))


def _is_adjacent_family(job_family: str, wanted_families: list[str]) -> bool:
    jf = str(job_family or "").strip().lower()
    return any(jf in FAMILY_ADJACENT.get(str(fam or "").strip().lower(), set()) for fam in wanted_families)


def _family_core_hits(job: GRankJob, families: list[str]) -> list[str]:
    hay = normalize_token(_job_text(job))
    hits: list[str] = []
    seen: set[str] = set()
    for family in families:
        for term in FAMILY_CORE_TERMS.get(str(family or "").strip().lower(), set()):
            key = normalize_token(term)
            if key and key in hay and key not in seen:
                seen.add(key)
                hits.append(term)
    return hits


def _ambiguous_skill_penalty(job: GRankJob, wanted_families: list[str]) -> tuple[float, list[str]]:
    hay = normalize_token(_job_text(job))
    penalties: list[str] = []
    total = 0.0
    for rule in AMBIGUOUS_SKILL_RULES:
        term = normalize_token(rule.get("term"))
        if not term or term not in hay:
            continue
        positives = [normalize_token(x) for x in (rule.get("positive_context") or []) if normalize_token(x)]
        negatives = [normalize_token(x) for x in (rule.get("negative_context") or []) if normalize_token(x)]
        positive_hit = any(x in hay for x in positives)
        negative_hit = any(x in hay for x in negatives)
        if "ai" in wanted_families and negative_hit and not positive_hit:
            total -= 18.0
            penalties.append("岗位中的 AI 更可能是设计软件/缩写，不是人工智能方向")
    return total, penalties


def _intent_score(student: GRankStudent, query: str, job: GRankJob, explicit_family: str | None = None) -> tuple[float, list[str]]:
    wanted_families = _infer_query_families(student, query, explicit_family)
    notes: list[str] = []
    score = 0.0
    if wanted_families:
        if job.job_family in wanted_families:
            score += 16.0
            notes.append("职业方向一致")
        elif _is_adjacent_family(job.job_family, wanted_families):
            score -= 8.0
            notes.append("职业方向相邻")
        elif job.job_family:
            score -= 26.0
            notes.append("职业方向偏离")

    title_text = normalize_token(job.title)
    for family in wanted_families:
        if family == "data" and any(x in title_text for x in ["数据", "bi", "分析"]):
            score += 8.0
        if family == "backend" and any(x in title_text for x in ["java", "后端", "服务端"]):
            score += 8.0
        if family == "frontend" and any(x in title_text for x in ["前端", "vue", "react"]):
            score += 8.0
        if family == "security" and any(x in title_text for x in ["安全", "攻防", "渗透"]):
            score += 8.0
        if family == "implementation" and any(x in title_text for x in ["实施", "交付"]):
            score += 8.0
        if family == "support" and any(x in title_text for x in ["支持", "售前", "售后"]):
            score += 8.0
    return score, notes


def _broad_jd_penalty(job: GRankJob) -> tuple[float, bool]:
    text = normalize_token(_job_text(job))
    for pattern in GENERIC_BROAD_PATTERNS:
        if normalize_token(pattern) in text:
            return -22.0, True
    return 0.0, False


def _skill_coverage(student: GRankStudent, job: GRankJob) -> dict[str, Any]:
    student_items = {normalize_token(item.get("_name")): item for item in student.hard_skill_items if normalize_token(item.get("_name"))}
    student_terms = {normalize_token(term): term for term in student.hard_skills if normalize_token(term)}
    ability_rows = [row for row in ((student.raw.get("extraction_meta") or {}).get("ability_verification") or []) if isinstance(row, dict)]
    ability_by_skill: dict[str, dict[str, Any]] = {}
    for row in ability_rows:
        for skill in row.get("skills") or []:
            token = normalize_token(skill)
            if token:
                ability_by_skill[token] = row
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    transferable: list[dict[str, Any]] = []
    proficiency_rows: list[dict[str, Any]] = []
    numerator = 0.0
    denominator = 0.0
    for term in job.hard_skills:
        key = normalize_token(term)
        if not key:
            continue
        required = _infer_required_proficiency(term, job)
        denominator += max(0.45, float(required["level"]))
        best = {"relation": "none", "score": 0.0, "student_skill": "", "reason": ""}
        for s_key, s_name in student_terms.items():
            relation, rel_score, reason = _skill_relation(s_name, term)
            if rel_score > float(best["score"]):
                best = {"relation": relation, "score": rel_score, "student_skill": s_name, "reason": reason}
        if float(best["score"]) > 0:
            skill_item = student_items.get(normalize_token(best["student_skill"]))
            prof = _infer_skill_proficiency(str(best["student_skill"]), skill_item, student.resume_text)
            ability_hit = None
            best_token = normalize_token(str(best["student_skill"]))
            target_token = normalize_token(term)
            for token, row_hit in ability_by_skill.items():
                if token and (token in best_token or best_token in token or token in target_token or target_token in token):
                    ability_hit = row_hit
                    break
            if ability_hit:
                merged = merge_proficiency_with_verification(
                    prof.get("code"),
                    verification_level=ability_hit.get("level"),
                    verification_score=ability_hit.get("overall_score"),
                )
                prof = {
                    **prof,
                    "level": round(float(merged.get("score") or prof.get("level") or 0.0), 2),
                    "code": merged.get("level"),
                    "label": merged.get("label"),
                    "rank": merged.get("rank"),
                    "source": "ability_verification",
                    "ability_verification": ability_hit,
                    "evidence": ability_hit.get("evidence") or prof.get("evidence"),
                }
            prof_ratio = min(1.0, float(prof["level"]) / max(0.35, float(required["level"])))
            contribution = float(best["score"]) * prof_ratio * max(0.45, float(required["level"]))
            numerator += contribution
            row = {
                "name": term,
                "match": round(float(best["score"]) * prof_ratio, 2),
                "student_skill": best["student_skill"],
                "relation": best["relation"],
                "reason": best["reason"],
                "student_proficiency": prof,
                "required_proficiency": required,
            }
            matched.append(row)
            proficiency_rows.append(row)
            if best["relation"] == "transferable":
                transferable.append(
                    {
                        "from_skill": best["student_skill"],
                        "to_skill": term,
                        "reason": best["reason"],
                        "confidence": round(float(best["score"]), 2),
                    }
                )
        else:
            missing.append({"name": term, "match": 0.0, "required_proficiency": required})
    if not job.hard_skills:
        return {
            "score": 72.0,
            "matched": matched,
            "missing": missing,
            "transferable": transferable,
            "proficiency": proficiency_rows,
        }
    coverage = numerator / max(1.0, denominator)
    score = 35.0 + coverage * 65.0
    if len(job.hard_skills) >= 4 and not matched:
        score = min(score, 42.0)
    return {
        "score": max(0.0, min(100.0, score)),
        "matched": matched[:8],
        "missing": missing[:8],
        "transferable": transferable[:8],
        "proficiency": proficiency_rows[:10],
    }


def _quality_score(student: GRankStudent, job: GRankJob) -> float:
    if not job.soft_skills:
        return min(85.0, 50.0 + len(student.soft_skills) * 4.0)
    student_terms = {normalize_token(term): term for term in student.soft_skills if normalize_token(term)}
    matched = sum(1 for term in job.soft_skills if normalize_token(term) in student_terms)
    return max(0.0, min(100.0, 42.0 + matched * 14.0 + min(16.0, len(student.soft_skills) * 2.0)))


def _potential_score(student: GRankStudent) -> float:
    return max(
        35.0,
        min(
            100.0,
            0.48 * float(student.completeness_score or 0.0) + 0.52 * float(student.competitiveness_score or 0.0),
        ),
    )


def _basic_score(student: GRankStudent, location: str, job: GRankJob) -> tuple[float, bool]:
    score = 60.0
    location_ok = _location_match(student, location, job)
    score += 18.0 if location_ok else -12.0
    if job.certificates and student.certificates:
        student_certs = {normalize_token(x) for x in student.certificates if normalize_token(x)}
        cert_hits = sum(1 for cert in job.certificates if normalize_token(cert) in student_certs)
        score += min(10.0, cert_hits * 4.0)
    return max(0.0, min(100.0, score)), location_ok


def _evidence_quality(student: GRankStudent, job: GRankJob) -> dict[str, Any]:
    student_signal_count = len(student.hard_skills) + len(student.soft_skills) + len(student.certificates)
    job_signal_count = len(job.hard_skills) + len(job.soft_skills) + len(job.certificates)
    resume_len = len(str(student.resume_text or ""))
    jd_len = len(str(job.description or ""))
    sparse_student = student_signal_count < 3 and resume_len < 180
    sparse_job = job_signal_count < 3 and jd_len < 160
    penalty = 0.0
    warnings: list[str] = []
    if sparse_student:
        penalty -= 10.0
        warnings.append("学生画像/简历证据偏少")
    if sparse_job:
        penalty -= 14.0
        warnings.append("岗位画像/岗位原文证据偏少")
    return {
        "student_signal_count": student_signal_count,
        "job_signal_count": job_signal_count,
        "resume_text_length": resume_len,
        "job_text_length": jd_len,
        "sparse_student": sparse_student,
        "sparse_job": sparse_job,
        "penalty": penalty,
        "warnings": warnings,
    }


def _dimension_scores(student: GRankStudent, query: str, location: str, job: GRankJob, explicit_family: str | None = None) -> dict[str, Any]:
    basic, location_ok = _basic_score(student, location, job)
    skill_result = _skill_coverage(student, job)
    skills = float(skill_result["score"])
    matched_skill_rows = list(skill_result["matched"])
    missing_skill_rows = list(skill_result["missing"])
    transferable_rows = list(skill_result["transferable"])
    proficiency_rows = list(skill_result["proficiency"])
    matched_skills = [str(row.get("name") or "") for row in matched_skill_rows if str(row.get("name") or "").strip()]
    missing_skills = [str(row.get("name") or "") for row in missing_skill_rows if str(row.get("name") or "").strip()]
    qualities = _quality_score(student, job)
    potential = _potential_score(student)
    wanted_families = _infer_query_families(student, query, explicit_family)
    family_matched = bool(wanted_families and job.job_family in wanted_families)
    family_adjacent = bool(wanted_families and not family_matched and _is_adjacent_family(job.job_family, wanted_families))
    family_unrelated = bool(wanted_families and job.job_family and not family_matched and not family_adjacent)
    explicit_family_hits = _family_core_hits(job, wanted_families)
    ambiguous_penalty, ambiguous_notes = _ambiguous_skill_penalty(job, wanted_families)
    intent_bonus, intent_notes = _intent_score(student, query, job, explicit_family)
    broad_penalty, broad_hit = _broad_jd_penalty(job)
    anchor_bonus = _anchor_bonus(student, query, job)
    query_anchor_adjustment, query_anchor_hits, query_anchor_misses = _query_anchor_adjustment(query, job)
    evidence_quality = _evidence_quality(student, job)

    overall = 0.2 * basic + 0.4 * skills + 0.15 * qualities + 0.25 * potential
    # Retrieval intent changes ordering; it must not inflate measured ability.
    overall += broad_penalty + ambiguous_penalty + float(evidence_quality["penalty"])
    if family_adjacent:
        overall = min(overall, 78.0 if explicit_family_hits else 68.0)
    if family_unrelated:
        overall = min(overall - 14.0, 54.0)
    overall = max(0.0, min(100.0, overall))

    confidence = min(
        100.0,
        0.4 * float(student.completeness_score or 0.0)
        + 0.35 * float(student.competitiveness_score or 0.0)
        + 8.0 * len(matched_skills)
        + (8.0 if location_ok else 0.0),
    )
    hard_query_misses = [x for x in query_anchor_misses if x in HIGH_SIGNAL_TERMS]
    query_hard_mismatch = bool(hard_query_misses and not query_anchor_hits)
    low_confidence = overall < 55.0 or (skills < 45.0 and not matched_skills) or query_hard_mismatch or family_unrelated or bool(ambiguous_notes) or bool(evidence_quality["sparse_job"])
    if low_confidence:
        overall = min(overall, 54.0)
    gap_paths = _build_skill_gap_paths(missing_skills)
    counterfactual = _counterfactual_actions(missing_skills, transferable_rows, overall)
    strength_fallbacks = [x for x in query_anchor_hits if x not in matched_skills]
    gap_fallbacks = [x for x in query_anchor_misses if x not in missing_skills]
    top_strengths = (matched_skills + strength_fallbacks)[:5]
    top_gaps = (missing_skills + gap_fallbacks)[:6]

    return {
        "overall_score": round(overall, 2),
        "ranking_score": round(max(0.0, min(100.0, overall + intent_bonus + anchor_bonus + query_anchor_adjustment)), 2),
        "dimension_scores": {
            "basic": {"score": round(basic, 2), "details": [{"item": "location", "result": "match" if location_ok else "mismatch"}]},
            "skills": {
                "score": round(skills, 2),
                "matched": matched_skill_rows,
                "missing": missing_skill_rows,
                "transferable": transferable_rows,
                "proficiency_evidence": proficiency_rows,
                "gap_paths": gap_paths,
                "relation": "high" if family_matched else ("medium" if family_adjacent else ("unknown" if not wanted_families else "low")),
            },
            "qualities": {"score": round(qualities, 2), "signals": [{"name": name} for name in student.soft_skills[:8]]},
            "potential": {"score": round(potential, 2), "signals": [{"name": "completeness", "value": student.completeness_score}, {"name": "competitiveness", "value": student.competitiveness_score}]},
        },
        "top_strengths": top_strengths,
        "top_gaps": top_gaps,
        "skill_transfer_paths": gap_paths,
        "counterfactual_actions": counterfactual,
        "proficiency_evidence": proficiency_rows,
        "evidence_quality": evidence_quality,
        "intent_notes": intent_notes,
        "wanted_families": wanted_families,
        "family_matched": family_matched,
        "family_adjacent": family_adjacent,
        "family_unrelated": family_unrelated,
        "explicit_family_hits": explicit_family_hits,
        "ambiguous_skill_penalty": round(ambiguous_penalty, 2),
        "ambiguous_skill_notes": ambiguous_notes,
        "anchor_bonus": round(anchor_bonus, 2),
        "broad_jd_hit": broad_hit,
        "broad_jd_penalty": round(broad_penalty, 2),
        "query_anchor_adjustment": round(query_anchor_adjustment, 2),
        "query_anchor_hits": query_anchor_hits,
        "query_anchor_misses": query_anchor_misses,
        "query_hard_mismatch": query_hard_mismatch,
        "low_confidence": low_confidence,
        "confidence": round(confidence, 2),
    }


def _candidate_jobs(q: str | None, location: str | None, max_candidates: int) -> list[GRankJob]:
    # Query text should drive ranking, not hard filter the candidate pool.
    # Otherwise a sparse or short query can collapse recall to zero.
    rows = db.list_jobs(q=None, location=location, limit=max_candidates, offset=0)
    out: list[GRankJob] = []
    for row in rows:
        job = load_job(str(row.get("job_id") or ""))
        if job is None:
            continue
        if not db.get_job_profile(job.job_id):
            continue
        out.append(job)
    return out


def _bm25_recall(query: str, jobs: list[GRankJob], top_k: int) -> list[tuple[str, float]]:
    query_terms = _recall_tokens(query)
    if not query_terms or not jobs:
        return []
    docs = [_recall_tokens(_job_text(job)) for job in jobs]
    avgdl = sum(len(doc) for doc in docs) / max(1, len(docs))
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    q_counts = Counter(query_terms)
    k1 = 1.5
    b = 0.75
    rows: list[tuple[str, float]] = []
    for job, doc in zip(jobs, docs):
        if not doc:
            continue
        tf = Counter(doc)
        score = 0.0
        dl = len(doc)
        for term, qf in q_counts.items():
            freq = tf.get(term, 0)
            if freq <= 0:
                continue
            idf = math.log(1 + (len(docs) - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            denom = freq + k1 * (1 - b + b * dl / max(1.0, avgdl))
            score += idf * (freq * (k1 + 1) / denom) * max(1, qf)
        if score > 0:
            rows.append((job.job_id, score))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:top_k]


def _anchor_recall(student: GRankStudent, query: str, jobs: list[GRankJob], top_k: int) -> list[tuple[str, float]]:
    anchors: set[str] = set()
    for term in student.hard_skills[:40] + _tokenize(query):
        key = normalize_token(term)
        if not key:
            continue
        if key in HIGH_SIGNAL_TERMS or len(key) >= 4 or any(ch in key for ch in ["安全", "漏洞", "防火墙", "区块链", "合约", "数据"]):
            anchors.add(key)
    if not anchors:
        return []
    rows: list[tuple[str, float]] = []
    for job in jobs:
        text = normalize_token(_job_text(job))
        hard = {normalize_token(x) for x in job.hard_skills}
        score = 0.0
        for anchor in anchors:
            if anchor in hard:
                score += 12.0
            elif anchor in text:
                score += 5.0
        if score > 0:
            rows.append((job.job_id, score))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:top_k]


def _rrf(rankings: dict[str, list[tuple[str, float]]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = defaultdict(float)
    for pairs in rankings.values():
        for rank, (job_id, _score) in enumerate(pairs, start=1):
            fused[job_id] += 1.0 / (k + rank)
    return dict(fused)


def _recall_candidates(
    student: GRankStudent,
    query: str,
    jobs: list[GRankJob],
    *,
    pool_size: int,
    semantic_enabled: bool = True,
    explicit_family: str | None = None,
) -> tuple[list[GRankJob], dict[str, Any]]:
    wanted_families = _infer_query_families(student, query, explicit_family)
    full_query = _text_join(query, " ".join(wanted_families), " ".join(student.hard_skills[:8]))
    bm25 = _bm25_recall(full_query, jobs, top_k=max(pool_size, 80))
    anchor = _anchor_recall(student, query, jobs, top_k=max(pool_size, 80))
    semantic: list[tuple[str, float]] = []
    semantic_stats: dict[str, Any] = {"semantic_enabled": False, "semantic_reason": "disabled"}
    if semantic_enabled:
        semantic, semantic_stats = _semantic_recall(student, query, jobs, top_k=max(pool_size, 120))
    coarse = sorted(
        [(job.job_id, _coarse_score(student, query, job, explicit_family=explicit_family)) for job in jobs],
        key=lambda x: x[1],
        reverse=True,
    )[: max(pool_size, 120)]
    fused = _rrf({"bm25": bm25, "anchor": anchor, "semantic": semantic, "coarse": coarse})
    by_id = {job.job_id: job for job in jobs}
    ordered_ids = sorted(fused, key=fused.get, reverse=True)[:pool_size]
    selected = [by_id[jid] for jid in ordered_ids if jid in by_id]
    if len(selected) < min(pool_size, len(jobs)):
        seen = {job.job_id for job in selected}
        for job_id, _score in coarse:
            if job_id not in seen and job_id in by_id:
                selected.append(by_id[job_id])
                seen.add(job_id)
            if len(selected) >= pool_size:
                break
    return selected, {
        "bm25_hits": len(bm25),
        "anchor_hits": len(anchor),
        "semantic_hits": len(semantic),
        "coarse_hits": len(coarse),
        "fused_hits": len(fused),
        **semantic_stats,
    }


def _normalize_bge_scores(rows: list[tuple[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    values = [float(score) for _, score in rows]
    lo = min(values)
    hi = max(values)
    if hi - lo <= 1e-9:
        return {job_id: 0.5 for job_id, _ in rows}
    return {job_id: (float(score) - lo) / (hi - lo) for job_id, score in rows}


def _bge_rerank_scores(
    student: GRankStudent,
    query: str,
    jobs: list[GRankJob],
    *,
    top_n: int,
) -> tuple[dict[str, float], dict[str, Any]]:
    if not jobs or top_n <= 0:
        return {}, {"bge_rerank_enabled": False, "bge_rerank_reason": "empty_pool"}
    model, reason = _load_bge_reranker()
    if model is None:
        return {}, {"bge_rerank_enabled": False, "bge_rerank_reason": reason}
    selected = jobs[: max(1, min(len(jobs), int(top_n)))]
    try:
        left = _bge_pair_text_for_student(student, query)
        pairs = [(left, _bge_pair_text_for_job(job)) for job in selected]
        raw_scores = model.predict(pairs, show_progress_bar=False)
        rows = [(job.job_id, float(score)) for job, score in zip(selected, raw_scores)]
        return _normalize_bge_scores(rows), {
            "bge_rerank_enabled": True,
            "bge_rerank_reason": "ok",
            "bge_rerank_scored": len(rows),
        }
    except Exception as exc:
        return {}, {
            "bge_rerank_enabled": False,
            "bge_rerank_reason": f"predict_failed:{type(exc).__name__}: {str(exc)[:140]}",
        }


def _apply_model_rank_fusion(items: list[dict[str, Any]], *, bge_weight: float) -> list[dict[str, Any]]:
    if not items:
        return []
    weight = max(0.0, min(0.45, float(bge_weight or 0.0)))
    out: list[dict[str, Any]] = []
    for item in items:
        ranked = dict(item)
        base_rank = float(ranked.get("rank_score") or ranked.get("overall_score") or 0.0)
        bge_score = ranked.get("bge_rerank_score")
        if bge_score is not None:
            model_score = max(0.0, min(100.0, float(bge_score) * 100.0))
            fused = (1.0 - weight) * max(0.0, min(100.0, base_rank)) + weight * model_score
            ranked["model_rank_score"] = round(fused, 2)
        else:
            ranked["model_rank_score"] = round(max(0.0, min(100.0, base_rank)), 2)
        # Keep rank_score display friendly while sorting by model_rank_score.
        ranked["rank_score"] = ranked["model_rank_score"]
        out.append(ranked)
    out.sort(key=lambda x: (float(x.get("model_rank_score") or 0.0), float(x.get("overall_score") or 0.0)), reverse=True)
    return out


def _apply_direction_rank_guard(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    guarded: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        overall = float(row.get("overall_score") or 0.0)
        cap: float | None = None
        reason = ""
        if row.get("family_unrelated"):
            cap = min(54.0, overall)
            reason = "explicit_family_unrelated"
        elif row.get("family_adjacent"):
            family_hits = [str(x).strip() for x in (row.get("explicit_family_hits") or []) if str(x).strip()]
            cap = min(82.0, overall + 8.0) if family_hits else min(72.0, overall + 4.0)
            reason = "explicit_family_adjacent"
        if cap is not None:
            for key in ["rank_score", "model_rank_score", "final_rank_score"]:
                if key in row and row.get(key) is not None:
                    row[key] = round(min(float(row.get(key) or 0.0), cap), 2)
            row["direction_rank_guard"] = reason
        guarded.append(row)
    guarded.sort(key=lambda x: (float(x.get("rank_score") or x.get("model_rank_score") or x.get("overall_score") or 0.0), float(x.get("overall_score") or 0.0)), reverse=True)
    return guarded


def _collapse_duplicates(items: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for item in items:
        key = _duplicate_key(item)
        if key not in grouped:
            grouped[key] = item
        else:
            duplicates += 1
            if float(item.get("rank_score") or item.get("overall_score") or 0.0) > float(grouped[key].get("rank_score") or grouped[key].get("overall_score") or 0.0):
                grouped[key] = item
    rows = list(grouped.values())
    rows.sort(key=lambda x: (float(x.get("rank_score") or 0.0), float(x.get("overall_score") or 0.0)), reverse=True)
    return rows[:limit], duplicates


def _coarse_score(student: GRankStudent, query: str, job: GRankJob, explicit_family: str | None = None) -> float:
    student_text = _student_text(student)
    job_text = _job_text(job)
    score = 0.0
    score += _weighted_overlap_tokens(job_text, _tokenize(query), 3.2)
    score += _weighted_overlap_tokens(job_text, student.hard_skills[:14], 2.4)
    score += _weighted_overlap_tokens(job_text, student.soft_skills[:10], 1.0)
    score += _weighted_overlap_tokens(job_text, student.certificates[:6], 1.2)
    score += _weighted_overlap_tokens(job_text, student.preferred_locations[:3], 2.5)
    intent_bonus, _ = _intent_score(student, query, job, explicit_family)
    score += max(0.0, intent_bonus)
    score += _anchor_bonus(student, query, job)
    if student_text and job_text:
        score += min(10.0, math.sqrt(len(set(_tokenize(student_text)) & set(_tokenize(job_text)))) * 2.0)
    return score


def recommend_jobs_g_rank(
    student_id: str,
    *,
    top_k: int = 20,
    q: str | None = None,
    location: str | None = None,
    job_family: str | None = None,
    strategy: str | None = None,
    max_candidates: int = 2000,
    strict_family: bool = True,
    semantic_enabled: bool = True,
    bge_rerank_enabled: bool = True,
    bge_rerank_top_n: int = 20,
    bge_rerank_weight: float = 0.28,
) -> dict[str, Any]:
    payload = build_recommendation_payload(student_id)
    if payload.get("status") != "ready":
        return payload

    student: GRankStudent = payload["student"]
    strategy_name = normalize_strategy(strategy)
    query = str(q or "").strip()
    explicit_family = str(job_family or "").strip().lower()
    preference_map = {
        str(item.get("job_id") or ""): str(item.get("preference") or "").strip().upper()
        for item in db.list_student_job_preferences(student_id, limit=2000)
        if str(item.get("job_id") or "").strip()
    }
    candidate_jobs = _candidate_jobs(q=query if query else None, location=location, max_candidates=max_candidates)
    recalled_jobs, recall_stats = _recall_candidates(
        student,
        query,
        candidate_jobs,
        pool_size=min(len(candidate_jobs), max(160, top_k * 16)),
        semantic_enabled=semantic_enabled,
        explicit_family=explicit_family,
    )

    coarse = [{"job": job, "coarse_score": _coarse_score(student, query, job, explicit_family=explicit_family)} for job in recalled_jobs]
    coarse.sort(key=lambda x: x["coarse_score"], reverse=True)
    refine_pool = coarse[: min(len(coarse), max(120, top_k * 12))]
    bge_score_map: dict[str, float] = {}
    bge_stats: dict[str, Any] = {"bge_rerank_enabled": False, "bge_rerank_reason": "disabled"}
    if bge_rerank_enabled:
        bge_score_map, bge_stats = _bge_rerank_scores(
            student,
            query,
            [row["job"] for row in refine_pool],
            top_n=min(len(refine_pool), max(top_k, min(160, int(bge_rerank_top_n or 20)))),
        )
    bge_weight = max(0.0, min(0.45, float(bge_rerank_weight or 0.0)))

    items = []
    low_confidence_items = []
    for row in refine_pool:
        job = row["job"]
        dims = _dimension_scores(student, query, str(location or ""), job, explicit_family=explicit_family)
        bge_norm = bge_score_map.get(job.job_id)
        display_score = float(dims["overall_score"])
        rank_score = float(dims["ranking_score"])
        if bge_norm is not None:
            rank_score = (1.0 - bge_weight) * rank_score + bge_weight * (float(bge_norm) * 100.0)
        item = {
            "job_id": job.job_id,
            "title": job.title,
            "company_name": job.company_name,
            "location": job.location,
            "industry": job.industry,
            "job_family": job.job_family,
            "description": job.description[:600],
            "overall_score": dims["overall_score"],
            "score": dims["overall_score"],
            "rank_score": round(rank_score, 2),
            "dimension_scores": dims["dimension_scores"],
            "top_strengths": dims["top_strengths"],
            "top_gaps": dims["top_gaps"],
            "skill_transfer_paths": dims["skill_transfer_paths"],
            "counterfactual_actions": dims["counterfactual_actions"],
            "proficiency_evidence": dims["proficiency_evidence"],
            "evidence_quality": dims["evidence_quality"],
            "match_reason": "、".join(dims["intent_notes"][:2]) or "基础技能与岗位文本相关",
            "g_rank_confidence": dims["confidence"],
            "query_intent_boost": 0.0,
            "g_rank_anchor_bonus": dims["anchor_bonus"],
            "coarse_score": round(float(row["coarse_score"]), 2),
            "broad_jd_hit": dims["broad_jd_hit"],
            "broad_jd_penalty": dims["broad_jd_penalty"],
            "query_anchor_adjustment": dims["query_anchor_adjustment"],
            "query_anchor_hits": dims["query_anchor_hits"],
            "query_anchor_misses": dims["query_anchor_misses"],
            "query_hard_mismatch": dims["query_hard_mismatch"],
            "wanted_families": dims["wanted_families"],
            "family_matched": dims["family_matched"],
            "family_adjacent": dims["family_adjacent"],
            "family_unrelated": dims["family_unrelated"],
            "explicit_family_hits": dims["explicit_family_hits"],
            "ambiguous_skill_penalty": dims["ambiguous_skill_penalty"],
            "ambiguous_skill_notes": dims["ambiguous_skill_notes"],
            "is_low_confidence": False,
            "ai_rerank_used": False,
            "ai_rerank_score": None,
            "ai_rerank_reason": "",
            "bge_rerank_used": bge_norm is not None,
            "bge_rerank_score": round(float(bge_norm), 4) if bge_norm is not None else None,
        }
        preference = preference_map.get(job.job_id, "")
        item["user_preference"] = preference or None
        item["is_favorite"] = preference == "FAVORITE"
        item["is_dismissed"] = preference == "DISMISS"
        if preference == "DISMISS":
            continue
        if preference == "FAVORITE":
            item["rank_score"] = round(float(item.get("rank_score") or 0.0) + 4.0, 2)
            item["recommendation_type"] = "已收藏岗位"
        if strict_family and explicit_family and dims["family_unrelated"]:
            item["is_low_confidence"] = True
            item["recommendation_type"] = "方向不匹配候选"
            low_confidence_items.append(item)
            continue
        if strict_family and student.preferred_job_families and job.job_family and job.job_family not in student.preferred_job_families and dims["overall_score"] < 70:
            continue
        if dims["low_confidence"]:
            item["is_low_confidence"] = True
            item["recommendation_type"] = "低置信候选"
            low_confidence_items.append(item)
            continue
        if not item.get("recommendation_type"):
            if dims["family_adjacent"]:
                item["recommendation_type"] = "相邻探索岗位"
            else:
                item["recommendation_type"] = "精准匹配岗位"
        items.append(item)

    behavior_profile = build_student_behavior_profile(student_id=student_id, lookback_days=180, limit=1000)
    reranked = rerank_job_items(items=items, strategy=strategy_name, student_profile=student.raw, behavior_profile=behavior_profile)
    reranked = _apply_model_rank_fusion(reranked, bge_weight=bge_weight)
    reranked = _apply_direction_rank_guard(reranked)
    collapsed, duplicate_filtered = _collapse_duplicates(reranked, top_k)
    if len(collapsed) < top_k and low_confidence_items:
        low_ranked = rerank_job_items(
            items=low_confidence_items,
            strategy=strategy_name,
            student_profile=student.raw,
            behavior_profile=behavior_profile,
        )
        low_ranked = _apply_model_rank_fusion(low_ranked, bge_weight=bge_weight)
        low_ranked = _apply_direction_rank_guard(low_ranked)
        used_keys = {_duplicate_key(item) for item in collapsed}
        for item in low_ranked:
            key = _duplicate_key(item)
            if key in used_keys:
                continue
            collapsed.append(item)
            used_keys.add(key)
            if len(collapsed) >= top_k:
                break
    rows = [enrich_job_labels(item) for item in collapsed]

    return {
        "status": "ok",
        "student_id": student_id,
        "items": rows,
        "engine": "g_rank_migration_v4_m3e_faiss_bge",
        "strategy": strategy_name,
        "profile_source": "existing",
        "total_candidates": len(reranked),
        "jobs_total": len(candidate_jobs),
        "low_confidence_count": len(low_confidence_items),
        "strict_family": bool(strict_family),
        "diagnostics": {
            **(payload.get("diagnostics") or {}),
            "candidate_jobs": len(candidate_jobs),
            **recall_stats,
            "coarse_pool": len(coarse),
            "refine_pool": len(refine_pool),
            "kept_after_filter": len(items),
            "duplicate_filtered": duplicate_filtered,
            "favorite_preferences": sum(1 for value in preference_map.values() if value == "FAVORITE"),
            "dismiss_preferences": sum(1 for value in preference_map.values() if value == "DISMISS"),
            "behavior_used_events": int(behavior_profile.get("used_events") or 0),
            **bge_stats,
            "bge_rerank_weight": bge_weight,
            "model_device": _MODEL_DEVICE_LABEL,
        },
        "low_confidence_items": [enrich_job_labels(item) for item in low_confidence_items[: min(20, len(low_confidence_items))]],
    }
