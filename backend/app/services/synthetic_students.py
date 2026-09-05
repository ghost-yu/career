from __future__ import annotations

import json
import random
from typing import Any

from app.db import sqlite as db
from app.services.llm import llm_client
from app.services.student_profile import build_student_profile_from_manual
from app.utils.ids import now_iso
from app.utils.labels import job_family_label

NAMES = [
    '张晨曦', '李嘉宁', '王若涵', '刘子昂', '陈思远', '杨雨桐', '赵明轩', '周可欣', '吴昊然', '郑书瑶',
    '孙浩宇', '朱语彤', '胡博文', '徐清妍', '高宇航', '林思齐', '何俊杰', '郭诗雨', '马景辰', '罗安琪',
    '梁子墨', '宋雨辰', '谢嘉怡', '韩宇泽', '曹欣怡', '唐文博', '冯梦洁', '彭奕辰', '邓安然', '薛晨露',
    '蒋奕宁', '许柏舟', '苏静怡', '顾星野', '叶清禾', '陶知夏', '程奕帆', '聂心妍', '吕承泽', '沈若安',
]

FAMILIES = {
    'backend': ['Java', 'Spring Boot', 'MySQL', 'Redis', 'Docker', 'Linux', '消息队列', 'RESTful API', '微服务', 'Git'],
    'frontend': ['TypeScript', 'React', 'Vue', 'Vite', 'Node.js', '前端工程化', '组件设计', 'ECharts', 'Axios', 'Pinia'],
    'ai': ['Python', 'PyTorch', '机器学习', '深度学习', '数据清洗', 'NLP', '模型评估', '向量检索', 'Prompt Engineering', 'RAG'],
    'data': ['Python', 'SQL', 'Pandas', '数据分析', '可视化', '数仓建模', 'ETL', 'BI', 'Airflow', 'Spark'],
    'qa': ['测试用例设计', '接口测试', '自动化测试', 'Pytest', 'Selenium', 'JMeter', '缺陷管理', 'Postman', '性能测试'],
    'ops': ['Linux', 'Docker', 'Kubernetes', 'CI/CD', 'Nginx', '监控告警', '脚本自动化', '云平台', 'GitLab CI', 'Prometheus'],
    'product': ['需求分析', 'Axure', 'PRD', '流程设计', '数据分析', '用户研究', '跨团队沟通', '竞品分析', '原型设计'],
    'design': ['Figma', '交互设计', '界面设计', '用户体验', '设计系统', '原型设计', '信息架构', '可用性测试'],
    'implementation': ['软件部署', '系统实施', '客户培训', '需求沟通', '文档编写', '数据库基础', '问题排查', '项目驻场'],
    'support': ['技术支持', '售前演示', '问题定位', '客户沟通', '方案讲解', '远程协助', '培训支持'],
    'security': ['网络安全', '漏洞扫描', '渗透测试', '日志分析', '应急响应', '安全加固', 'Linux'],
    'embedded': ['C', 'C++', '嵌入式', '单片机', 'ARM', '驱动开发', '硬件调试', '串口通信'],
    'mobile': ['Android', 'iOS', 'Flutter', 'Kotlin', 'Swift', '移动端性能优化', '客户端架构'],
}

SOFT_POOL = ['沟通能力', '学习能力', '抗压能力', '创新能力', '团队协作', '自驱力', '逻辑分析', '时间管理', '表达能力', '用户同理心']
CERT_POOL = ['CET-4', 'CET-6', '软考中级', '计算机二级', 'PMP', '华为HCIA', '阿里云ACA', '普通话证书']
CITIES = ['北京', '上海', '深圳', '广州', '杭州', '成都', '南京', '武汉', '西安', '苏州', '长沙']
SCHOOLS = ['某双一流大学', '某理工大学', '某信息工程大学', '某财经大学', '某工业大学', '某师范大学']
MAJORS = ['计算机科学与技术', '软件工程', '数据科学与大数据技术', '信息管理与信息系统', '人工智能', '网络工程']
CLUBS = ['院学生会', '机器人实验室', '开源技术协会', '数据智能社', '软件创新实验班', 'ACM 集训队']
COMPETITIONS = ['蓝桥杯', '中国大学生计算机设计大赛', '互联网+ 创新创业大赛', '数学建模竞赛', '服务外包创新创业大赛']
INDUSTRIES = ['互联网平台', '工业软件', '教育科技', '智能制造', 'SaaS 企业服务', '金融科技']


def _family_chinese(code: str) -> str:
    return job_family_label(code)


def _project_lines(family: str, skills: list[str]) -> list[str]:
    return [
        f'项目一：围绕{_family_chinese(family)}方向完成综合项目，主要使用{skills[0]}、{skills[1]}、{skills[2]}，负责需求拆解、模块实现、联调与复盘。',
        f'项目二：参与一个跨团队课程 / 比赛项目，使用{skills[3]}、{skills[4]}支撑功能交付，最终输出可演示版本与技术文档。',
        f'项目三：尝试结合真实业务场景优化性能、稳定性或用户体验，沉淀了排查问题、沟通推进和结果量化的经验。',
    ]


def _resume_text(name: str, family: str, skills: list[str], city: str, major: str, certs: list[str], experience: dict[str, int]) -> str:
    school = random.choice(SCHOOLS)
    club = random.choice(CLUBS)
    competition = random.choice(COMPETITIONS)
    industry = random.choice(INDUSTRIES)
    projects = _project_lines(family, skills)
    target = _family_chinese(family)
    return f"""姓名：{name}
求职意向：希望在{city}从事{target}相关岗位，可接受校招 / 实习转正，也愿意从强相关岗位起步。
教育背景：{school}，{major}专业，本科在读。主修课程包括数据结构、数据库、操作系统、软件工程、计算机网络等。
核心技能：{'、'.join(skills[:8])}。
项目经历：
1. {projects[0]} 结果：将核心流程跑通，阶段演示获得课程组认可，并完成问题清单与优化记录。
2. {projects[1]} 结果：在多人协作中承担主要开发 / 分析工作，推动版本按期交付。
3. {projects[2]} 结果：通过多轮验证优化页面响应速度、接口稳定性或实验指标，形成复盘报告。
实习经历：曾在{industry}相关团队参加短期实习或企业实践，接触真实需求沟通、问题排查、文档沉淀与跨角色协作。
竞赛与成果：参加{competition}，累计完成 {experience.get('projects', 0)} 个项目训练，具备从需求理解到结果呈现的完整闭环意识。
校园经历：曾在{club}担任骨干，负责活动策划、成员分工和进度推进，提升了沟通、协作与抗压能力。
证书：{certs[0]}、{certs[1]}。
自我评价：对{target}方向有持续兴趣，愿意通过实习、项目、比赛和开源不断补齐短板，希望毕业后尽快进入真实业务团队成长。"""


def _llm_expand_resume(payload: dict[str, Any], fallback: str) -> str:
    if not llm_client.is_enabled():
        return fallback
    system = """你是中文技术简历写作助手。请基于输入的结构化学生信息，写一份更像牛客/校招论坛风格的中文长简历文本。
要求：
1. 只使用输入信息，不要编造不存在的公司、奖项、论文。
2. 输出 1200~2200 字。
3. 包含：求职意向、教育背景、核心技能、3段项目经历、实习/实践经历、竞赛与校园经历、证书、自我评价。
4. 项目经历尽量用“背景-动作-结果”写法，突出量化结果、职责和技术细节。
5. 只输出纯文本，不要 markdown，不要 JSON。
"""
    try:
        resp = llm_client.chat_sync(system, json.dumps(payload, ensure_ascii=False))
        text = str(resp.text or '').strip()
        return text if len(text) >= 400 else fallback
    except Exception:
        return fallback


def seed_synthetic_students(count: int = 30, overwrite_existing: bool = False, use_llm_expand: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    count = max(1, min(int(count), 200))
    random.seed(42 + count)
    family_keys = list(FAMILIES.keys())
    for idx in range(count):
        sid = f'SYN{idx+1:03d}'
        existing = db.get_student(sid)
        if existing and not overwrite_existing:
            profile = db.get_student_profile(sid)
            out.append({'student_id': sid, 'name': existing.get('name'), 'profile_exists': bool(profile)})
            continue
        name = NAMES[idx % len(NAMES)]
        family = family_keys[idx % len(family_keys)]
        skill_pool = FAMILIES[family][:]
        random.shuffle(skill_pool)
        skills = skill_pool[: random.randint(6, 8)]
        soft = random.sample(SOFT_POOL, k=random.randint(4, 5))
        certs = random.sample(CERT_POOL, k=2)
        city = random.choice(CITIES)
        major = MAJORS[idx % len(MAJORS)]
        experience = {
            'internships': random.randint(0, 2),
            'projects': random.randint(3, 6),
            'awards': random.randint(1, 3),
            'publications': random.randint(0, 1) if family in {'ai', 'data'} else 0,
            'open_source': random.randint(0, 2) if family in {'backend', 'frontend', 'ai', 'ops'} else random.randint(0, 1),
            'leadership': random.randint(0, 2),
        }
        min_salary = random.choice([7000, 8000, 9000, 10000])
        max_salary = min_salary + random.choice([4000, 6000, 8000])
        base_resume = _resume_text(name, family, skills, city, major, certs, experience)
        llm_payload = {
            'name': name,
            'family': family,
            'family_label': _family_chinese(family),
            'skills': skills,
            'soft_skills': soft,
            'certificates': certs,
            'city': city,
            'major': major,
            'experience': experience,
            'base_resume': base_resume,
        }
        resume_text = _llm_expand_resume(llm_payload, base_resume) if use_llm_expand else base_resume
        payload = {
            'name': name,
            'hard_skills': skills,
            'soft_skills': soft,
            'certificates': certs,
            'raw_text': resume_text,
            'experience': experience,
            'preferences': {
                'preferred_locations': [city],
                'preferred_job_families': [family],
                'target_salary_min': min_salary,
                'target_salary_max': max_salary,
                'notes': f'偏好{_family_chinese(family)}方向，希望通过项目、实习和持续学习缩短从校园到岗位的适应期。',
            },
        }
        db.upsert_student(sid, name, created_at=now_iso())
        profile = build_student_profile_from_manual(sid, payload)
        out.append({
            'student_id': sid,
            'name': name,
            'job_family': family,
            'job_family_label': _family_chinese(family),
            'resume_chars': len(resume_text),
            'profile': profile.model_dump(),
        })
    return out
