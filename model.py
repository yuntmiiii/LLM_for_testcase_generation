import os
import json
import re
import asyncio
from typing import List, Dict, Any
from dotenv import load_dotenv

# LangChain Imports
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

# Pydantic Imports
from pydantic import BaseModel, Field

load_dotenv()

API_KEY = os.getenv("ARK_API_KEY")
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_ENDPOINT = "ep-20251204144851-kkws9"



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
    planned_stream_a_scenarios: List[str] = Field(
        description="Stream A (业务逻辑) 场景标题。*尽可能多地覆盖业务场景，最少生成6个*"
    )
    planned_stream_b_scenarios: List[str] = Field(
        description="Stream B (通用标准) 场景标题。"
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
    system_prompt = """
Role: 资深 QA 架构师 (Senior Architect) Mission: 阅读 PRD 和 其中的 UI/流程图，制定一份详尽的测试计划。 注意：这一步只需要制定计划（测什么），不需要写具体步骤。

👁️ 视觉与逻辑提取 (Visual & Context Analysis)
🔀 流程图分析：提取每一个 Yes/No 判定节点，识别所有“拒绝”、“异常”或“回退”的分支路径。
🖼️ UI 设计图分析：识别页面上所有的交互元素（输入框、按钮、链接）及其状态（默认置灰、红色必填星号、Loading 态）。
实体映射：将 UI 上的元素映射到 Stream B 的清单中（例如：识别到“身份证号”输入框 -> 准备应用“文本型字段”检查清单）。

🧠 Analysis Requirement (三流策略)
请按照以下三个维度进行场景规划：

1. Stream A: 模块内业务闭环 (Business Logic)
目标：覆盖单模块内的功能逻辑、状态流转和规则冲突。*尽可能多地覆盖业务场景，最少生成6个*

🟢 P0 - Happy Path (核心闭环)：

指令：提取 PRD 中的主流程路径（用户最希望完成的那件事）。
要求：前置满足 + 输入合法 + 操作正确 = 成功。
示例：“使用未注册手机号 + 正确验证码完成注册，验证页面跳转。”

🔴 P1 - Business Violations (业务规则冲突)：
指令：寻找文档中的“约束条件”，利用“反向用例”技术：
时效与规则限制：针对“有效期”、“过期”、“随机规则”生成用例。
状态冲突：对处于“中间态”的数据执行互斥操作。（例：对“已发货”订单点击“修改地址”）
依赖缺失：跳过前置步骤直接执行后续操作。（例：未勾选协议直接点击注册）
权限越界：普通用户尝试访问/调用管理员接口。

2. Stream B: 通用输入域与交互检查 (Input & Interaction)

目标：针对输入域的校验及 UI 交互反馈。
指令：覆盖数据边界、安全检查及视觉状态变化。
范围：
数据校验：长度边界、特殊字符、Emoji、XSS、空值。
UI 交互状态：检查 Focus（获取焦点）、Blur（失去焦点）、Hover（悬停）、Disabled（禁用）时的 UI 样式（边框颜色、提示文字显隐）是否符合描述。
格式规范：检查特定字段的生成规则（如：验证码是否为 4 位大写字母）。

3. Stream C: 跨模块/集成流转 (Cross-Module & Data Flow)

目标：覆盖数据在不同模块间的流转一致性及副作用（Side Effects）。请至少规划 3-5 个关键集成场景。
🔗 链路一致性：在 A 模块产生的数据，在 B 模块是否正确显示/生效？
示例：在“后台”下架商品 -> 验证“前台”商品详情页显示“已失效”且无法下单。
🔄 数据生命周期：创建 -> 修改 -> 删除后的全链路影响。
示例：用户注销账号后 -> 验证历史订单数据的脱敏显示及新消息推送的阻断。

Output Format: 必须是纯净的 JSON 格式。
{format_instructions}
"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
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

    system_prompt_template = """
Role: 高级测试执行专家 (Executor)
Mission: 严格根据"测试计划"生成具体用例。
Input: PRD文档(User消息) + 测试计划(System上下文)。

Requirements:
🚨 步骤生成规范 (Atomic Steps Rules)
图文结合：步骤中必须引用图片特征。
Evidence标注：在 visual_evidence 字段填写例如 "基于[参考图1-UI]的按钮置灰状态"。
动作分离：严禁将“填写并提交”合并。必须拆分为：1. 填写{{字段}}... 2. 点击{{按钮}}...。
数据抽象化：
✅ 正确：写 "输入符合{{规则}}/正确的数据"。
❌ 错误：不要硬编码 "输入 test/123456"。

1. **逐条执行**：遍历计划中每个模块的 `planned_stream_a_scenarios` 的每一个标题，生成一个 `TestCase`。
2. **数量一致**：计划里有多少个 A 类场景，输出里就必须有多少个用例。
3. **步骤详细**：`steps` 必须包含具体操作（如"点击[参考图1]确认按钮"）。
4. **视觉溯源**：`visual_evidence` 必须引用图片来源。


### Approved Test Plan (已批准的计划):
```json
{plan_json_data}
Output Format: 必须是纯净的 JSON 格式。 {format_instructions} """

    prompt = ChatPromptTemplate.from_messages([("system", system_prompt_template), ("user", content_parts)])
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