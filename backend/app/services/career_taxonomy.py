from __future__ import annotations

from typing import Any

LEVELS = ["junior", "mid", "senior", "lead", "director"]

TRACKS: dict[str, dict[str, Any]] = {
    "backend": {
        "label": "后端开发",
        "keywords": ["后端", "java", "golang", "go", "python", "服务端", "spring", "微服务", "c++"],
        "titles": {
            "junior": "后端开发工程师",
            "mid": "资深后端开发工程师",
            "senior": "后端技术专家",
            "lead": "后端架构师 / 技术负责人",
            "director": "研发经理 / 技术总监",
        },
        "switch_to": ["data", "ops", "ai", "product"],
    },
    "frontend": {
        "label": "前端开发",
        "keywords": ["前端", "react", "vue", "javascript", "typescript", "web前端", "小程序"],
        "titles": {
            "junior": "前端开发工程师",
            "mid": "资深前端开发工程师",
            "senior": "前端技术专家",
            "lead": "前端架构师 / 体验平台主管",
            "director": "前端负责人 / 技术总监",
        },
        "switch_to": ["product", "design", "mobile", "backend"],
    },
    "data": {
        "label": "数据开发",
        "keywords": ["数据开发", "数仓", "etl", "spark", "hadoop", "sql", "大数据", "bi", "数据分析"],
        "titles": {
            "junior": "数据开发工程师",
            "mid": "高级数据开发工程师",
            "senior": "数据平台专家",
            "lead": "数据架构师 / 数据平台主管",
            "director": "数据负责人 / 数据总监",
        },
        "switch_to": ["backend", "ai", "product"],
    },
    "ai": {
        "label": "人工智能",
        "keywords": ["算法", "机器学习", "深度学习", "nlp", "cv", "aigc", "rag", "llm", "ai"],
        "titles": {
            "junior": "算法工程师",
            "mid": "高级算法工程师",
            "senior": "算法专家 / 模型负责人",
            "lead": "AI 技术负责人 / 算法架构师",
            "director": "AI 研发经理 / 算法总监",
        },
        "switch_to": ["data", "backend", "research"],
    },
    "research": {
        "label": "科研研发",
        "keywords": ["研究员", "科研", "实验室", "博士后", "research"],
        "titles": {
            "junior": "研究助理 / 科研工程师",
            "mid": "科研工程师 / 研究员",
            "senior": "高级研究员",
            "lead": "课题负责人 / 首席研究员",
            "director": "研究中心负责人 / 首席科学家",
        },
        "switch_to": ["ai", "data", "product"],
    },
    "qa": {
        "label": "测试质量",
        "keywords": ["测试", "qa", "自动化测试", "性能测试", "测试开发"],
        "titles": {
            "junior": "测试工程师",
            "mid": "高级测试工程师",
            "senior": "测试开发专家",
            "lead": "测试负责人 / 质量负责人",
            "director": "质量总监 / 交付质量负责人",
        },
        "switch_to": ["backend", "ops", "product"],
    },
    "ops": {
        "label": "运维云平台",
        "keywords": ["运维", "devops", "sre", "云平台", "k8s", "docker", "监控"],
        "titles": {
            "junior": "运维工程师",
            "mid": "高级运维工程师 / DevOps 工程师",
            "senior": "平台运维专家 / SRE",
            "lead": "运维负责人 / 平台架构师",
            "director": "云平台负责人 / 运维总监",
        },
        "switch_to": ["backend", "security", "implementation"],
    },
    "product": {
        "label": "产品经理",
        "keywords": ["产品", "pm", "产品经理", "需求分析", "prd"],
        "titles": {
            "junior": "产品助理 / 产品专员",
            "mid": "产品经理",
            "senior": "高级产品经理",
            "lead": "产品负责人 / 产品专家",
            "director": "产品总监 / 业务负责人",
        },
        "switch_to": ["frontend", "data", "implementation", "design"],
    },
    "design": {
        "label": "设计体验",
        "keywords": ["ui", "ux", "视觉", "交互", "设计师", "体验设计"],
        "titles": {
            "junior": "UI/UX 设计师",
            "mid": "高级体验设计师",
            "senior": "设计专家 / 体验负责人",
            "lead": "设计主管 / 设计负责人",
            "director": "设计总监 / 创意负责人",
        },
        "switch_to": ["product", "frontend", "marketing"],
    },
    "implementation": {
        "label": "实施交付",
        "keywords": ["实施", "交付", "部署", "客户现场", "培训", "售后支持", "项目驻点"],
        "titles": {
            "junior": "实施工程师",
            "mid": "高级实施工程师 / 交付工程师",
            "senior": "实施专家 / 交付顾问",
            "lead": "实施负责人 / 交付经理",
            "director": "交付总监 / 解决方案负责人",
        },
        "switch_to": ["support", "product", "ops", "qa"],
    },
    "support": {
        "label": "技术支持",
        "keywords": ["技术支持", "售前", "售后", "客户支持", "培训"],
        "titles": {
            "junior": "技术支持工程师",
            "mid": "高级技术支持工程师",
            "senior": "解决方案顾问 / 技术顾问",
            "lead": "支持负责人 / 解决方案经理",
            "director": "客户成功总监 / 技术服务负责人",
        },
        "switch_to": ["implementation", "product", "ops", "sales"],
    },
    "sales": {
        "label": "销售商务",
        "keywords": ["销售", "商务", "bd", "业务拓展", "客户经理", "渠道经理", "大客户", "解决方案销售"],
        "titles": {
            "junior": "销售代表 / 商务专员",
            "mid": "客户经理 / 渠道经理",
            "senior": "大客户经理 / 解决方案销售经理",
            "lead": "销售负责人 / 区域销售经理",
            "director": "销售总监 / 商务总监",
        },
        "switch_to": ["support", "product", "implementation", "data"],
    },
    "security": {
        "label": "网络安全",
        "keywords": ["安全", "渗透", "攻防", "漏洞", "等保"],
        "titles": {
            "junior": "安全工程师",
            "mid": "高级安全工程师",
            "senior": "安全专家 / 攻防专家",
            "lead": "安全负责人 / 安全架构师",
            "director": "安全总监 / 信息安全负责人",
        },
        "switch_to": ["ops", "backend", "qa"],
    },
    "embedded": {
        "label": "嵌入式",
        "keywords": ["嵌入式", "单片机", "arm", "固件", "驱动", "硬件测试"],
        "titles": {
            "junior": "嵌入式开发工程师",
            "mid": "高级嵌入式开发工程师",
            "senior": "嵌入式系统专家",
            "lead": "嵌入式架构师 / 技术负责人",
            "director": "嵌入式研发负责人 / 技术总监",
        },
        "switch_to": ["backend", "mobile", "qa"],
    },
    "mobile": {
        "label": "移动开发",
        "keywords": ["ios", "android", "移动开发", "flutter", "鸿蒙"],
        "titles": {
            "junior": "移动开发工程师",
            "mid": "高级移动开发工程师",
            "senior": "移动端技术专家",
            "lead": "移动技术负责人 / 客户端架构师",
            "director": "客户端负责人 / 技术总监",
        },
        "switch_to": ["frontend", "backend", "product"],
    },
}

FAMILY_ALIAS: dict[str, str] = {
    "backend": "backend",
    "frontend": "frontend",
    "ai": "ai",
    "data": "data",
    "qa": "qa",
    "ops": "ops",
    "product": "product",
    "design": "design",
    "implementation": "implementation",
    "support": "support",
    "sales": "sales",
    "security": "security",
    "embedded": "embedded",
    "mobile": "mobile",
    "research": "research",
}


def track_label(track: str) -> str:
    return (TRACKS.get(track) or {}).get("label") or track


def level_rank(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError:
        return 1


def title_for(track: str, level: str) -> str:
    t = TRACKS.get(track) or {}
    titles = t.get("titles") or {}
    return titles.get(level) or f"{track_label(track)}岗位"


def switch_targets(track: str) -> list[str]:
    return list((TRACKS.get(track) or {}).get("switch_to") or [])
