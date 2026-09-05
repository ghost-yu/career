import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import agent, g_rank_migration as ranking
from app.services.action_planner import build_action_plan_from_gaps
from app.services.report_quality import check_markdown


class DemoQualityTests(unittest.TestCase):
    def test_report_checker_counts_actions_across_phase_subheadings(self):
        md = '## 4. 行动计划\n### 近期（4周）\n- **A**\n- **B**\n### 中期（12周）\n- **C**\n### 求职冲刺（24周）\n- **D**\n## 5. 评估与动态调整\n'
        self.assertNotIn('few_actions', [x['type'] for x in check_markdown(md)])
        short = md.replace('- **C**', '').replace('- **D**', '')
        self.assertIn('few_actions', [x['type'] for x in check_markdown(short)])

    def test_duplicate_skill_gaps_do_not_create_repeated_actions(self):
        with patch('app.services.action_planner._resources_for_skill', return_value=['官方文档']):
            phases = build_action_plan_from_gaps([{'name':'HTML/CSS'}, {'name':'html/css'}, {'name':'JavaScript'}])
        titles = [x.title for x in phases[0].actions]
        self.assertEqual(titles, ['补齐核心技能：HTML/CSS', '补齐核心技能：JavaScript'])

    def test_retrieval_bonuses_do_not_inflate_ability_score(self):
        student=SimpleNamespace(hard_skills=['Java'],soft_skills=[],certificates=[],resume_text='x'*200,completeness_score=60,competitiveness_score=60)
        job=SimpleNamespace(hard_skills=['Java'],soft_skills=[],certificates=[],description='x'*200,job_family='backend')
        mocks = {
            '_basic_score': (50,True), '_skill_coverage': {'score':50,'matched':[],'missing':[],'transferable':[],'proficiency':[]},
            '_quality_score':50, '_potential_score':50, '_infer_query_families':['backend'],
            '_family_core_hits':1, '_ambiguous_skill_penalty':(0,[]), '_intent_score':(30,[]),
            '_broad_jd_penalty':(0,False), '_anchor_bonus':30, '_query_anchor_adjustment':(20,[],[]),
        }
        with ExitStack() as stack:
            for name,value in mocks.items(): stack.enter_context(patch.object(ranking,name,return_value=value))
            result=ranking._dimension_scores(student,'Java','',job)
        self.assertEqual(result['overall_score'],50)
        self.assertEqual(result['ranking_score'],100)


class PersonalAdviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_advice_has_budget_and_project_evidence(self):
        profile={'experience_detail_items':{'projects':[{'content':'SparseLLM','evidence':'128K是外推估计'}]}}
        with patch.object(agent,'_student_profile_snapshot',return_value=profile), patch.object(agent,'_recent_dialogue',return_value=[]), patch.object(agent.llm_client,'chat',new=AsyncMock(return_value=SimpleNamespace(text='第1周准备，第2周复盘。'))) as chat:
            answer=await agent._personal_advice_answer('TEST','两周计划',None)
        self.assertIn('第2周',answer)
        self.assertEqual(chat.call_args.kwargs['max_tokens'],2200)
        self.assertIn('SparseLLM',chat.call_args.args[1])

    async def test_two_week_followup_precedes_generic_gap_router(self):
        with patch.object(agent.llm_client,'runtime_config',return_value={}), patch.object(agent.llm_client,'is_enabled',return_value=True), patch.object(agent,'_personal_advice_answer',new=AsyncMock(return_value='第1周整理项目证据；第2周准备面试。')) as answer, patch.object(agent,'_safe_score') as score:
            result=await agent.run_agent('TEST',{'message':'针对我的短板给我两周准备计划','session_id':'SESSION'}, {})
        self.assertEqual(result['type'],'text')
        self.assertIn('第2周',result['content'])
        answer.assert_awaited_once_with('TEST','针对我的短板给我两周准备计划','SESSION')
        score.assert_not_called()

    def test_normal_tool_requests_keep_their_route(self):
        self.assertFalse(agent._needs_personal_advice('推荐岗位'))
        self.assertFalse(agent._needs_personal_advice('为这个岗位生成报告'))
        self.assertTrue(agent._needs_personal_advice('结合我的简历比较两个方向'))

    def test_project_names_are_not_model_configuration_questions(self):
        self.assertFalse(agent._is_model_info_query('根据我的简历，SparseLLM项目有什么亮点？'))
        self.assertFalse(agent._is_model_info_query('LLM推理优化和模型蒸馏如何准备面试？'))
        self.assertFalse(agent._is_model_info_query('我的模型蒸馏项目有什么亮点？'))
        self.assertTrue(agent._is_model_info_query('你是什么模型？'))
        self.assertTrue(agent._is_model_info_query('what model are you?'))


if __name__=='__main__': unittest.main()
