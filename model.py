import os
import json
import re
import asyncio
from typing import List, Dict, Any
from dotenv import load_dotenv
from prompts.planner import PLANNER_SYSTEM_PROMPT
from prompts.business import BUSINESS_SYSTEM_PROMPT
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from pydantic import BaseModel, Field

load_dotenv()
API_KEY = os.getenv("ARK_API_KEY")
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_ENDPOINT = os.getenv("SEEDVISION_ENDPOINT")

class TestCase(BaseModel):
    module_name: str = Field(description="模块名称")
    title: str = Field(description="简练的标题")
    type: str = Field(description="Stream A/Stream B/Stream C")
    pre_condition: str = Field(description="前置条件，指测试开始前系统必须具备的状态或用户所处的环境")
    visual_evidence: str = Field(
        description="【视觉溯源】必须指明该用例是基于哪张图片的什么逻辑生成的。格式示例：'基于[参考图1-流程图]的否决分支'。如果仅基于文本，填'无'。"
    )
    steps: List[str] = Field(
        description="操作步骤。每步不超过15字。如果涉及UI元素，请在步骤中明确指出。"
    )
    expected_result: str = Field(description="预期结果")


class ModulePlan(BaseModel):
    module_name: str = Field(description="模块名称")
    identified_inputs: List[str] = Field(description="扫描出的所有输入字段列表")
    business_constraints: List[str] = Field(description="扫描出的所有业务约束规则")
    involved_roles: List[str] = Field(description="需要参与测试的用户角色，例如：管理员、普通会员、未登录用户")
    data_requirements: List[str] = Field(description="为了测试各种约束，需要准备的特殊数据特征，例如：'过期的优惠券'、'余额为0的账户'")
    risk_assessment: str = Field(description="该模块的风险等级(High/Medium/Low)及理由。涉及资金、隐私、核心流程为 High")
    planned_stream_a_scenarios: List[str] = Field(
        description="Stream A (业务逻辑) 场景标题。*尽可能多地覆盖业务场景，最少生成6个*"
    )
    planned_stream_b_scenarios: List[str] = Field(
        description="Stream B (通用标准) 场景标题。进行UI交互检查。针对identified_inputs中的每个输入框进行数据校验，覆盖边界值、特殊字符、Emoji。"
    )
    planned_stream_c_scenarios: List[str] = Field(
        description="Stream C (Cross-Module & Data Flow) 场景标题。"
    )


class TestPlanResult(BaseModel):
    detected_modules: List[str] = Field(description="识别到的模块列表")
    analysis_and_plan: List[ModulePlan] = Field(description="详细计划")

class TestCaseGenerationResult(BaseModel):
    cases: List[TestCase] = Field(description="生成的测试用例列表")

def get_llm():
    if not API_KEY:
        raise ValueError("未配置 ARK_API_KEY")
    return ChatOpenAI(
        model=MODEL_ENDPOINT,
        openai_api_key=API_KEY,
        openai_api_base=BASE_URL,
        temperature=0.1,
        max_completion_tokens=32000,
        model_kwargs={
            "response_format": {"type": "json_object"}
        }
    )


def clean_json_string(content: str) -> str:
    content = content.strip()
    if "```json" in content:
        pattern = r"```json(.*?)```"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
    elif "```" in content:
        pattern = r"```(.*?)```"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
    return content


def build_content_parts(parsed_data: list) -> list:
    content_parts = [{"type": "text", "text": "以下是 PRD 文档内容和参考图："}]
    img_count = 0
    for node in parsed_data:
        if node['type'] == 'text':
            content_parts.append({"type": "text", "text": node['content']})
        elif node['type'] == 'image':
            img_count += 1
            content_parts.append({"type": "text", "text": f"\n[参考图 {img_count}]\n"})
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": node['base64']}
            })
    return content_parts



async def step_1_analyze_and_plan(llm, content_parts) -> TestPlanResult:
    print("--- [Step 1] 正在规划测试场景 (Architect Phase) ---")
    parser = PydanticOutputParser(pydantic_object=TestPlanResult)
    prompt = ChatPromptTemplate.from_messages([
        ("system", PLANNER_SYSTEM_PROMPT),
        ("user", content_parts)
    ])

    chain = prompt | llm
    response = await chain.ainvoke({"format_instructions": parser.get_format_instructions()})
    cleaned_content = clean_json_string(response.content)

    try:
        result = parser.parse(cleaned_content)
        print(f"✅ Step 1 完成。规划了 {len(result.analysis_and_plan)} 个模块的测试方案。")
        print(result)
        return result
    except Exception as e:
        print(f"❌ Step 1 解析失败: {e}")
        print(f"原始内容片段: {cleaned_content[:200]}...")
        raise e


async def step_2_generate_cases(llm, content_parts, plan_result: TestPlanResult) -> TestCaseGenerationResult:
    print("--- [Step 2] 正在生成具体用例 (Execution Phase) ---")

    parser = PydanticOutputParser(pydantic_object=TestCaseGenerationResult)

    try:
        plan_json = json.dumps(plan_result.model_dump(), ensure_ascii=False, indent=2)
    except AttributeError:
        plan_json = json.dumps(plan_result.dict(), ensure_ascii=False, indent=2)


    prompt = ChatPromptTemplate.from_messages([("system", BUSINESS_SYSTEM_PROMPT), ("user", content_parts)])
    chain = prompt | llm

    response = await chain.ainvoke({
        "plan_json_data": plan_json,
        "format_instructions": parser.get_format_instructions()
    })

    cleaned_content = clean_json_string(response.content)

    try:
        result = parser.parse(cleaned_content)
        print(f"✅ Step 2 完成。共生成 {len(result.cases)} 条详细用例。")
        print(result)
        return result
    except Exception as e:
        print(f"❌ Step 2 解析失败: {e}")
        print(f"原始内容片段: {cleaned_content[:500]}...")
        raise e