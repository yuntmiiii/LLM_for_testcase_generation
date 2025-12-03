import os
from typing import List, Dict
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage

load_dotenv()

API_KEY = os.getenv("ARK_API_KEY")
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_ENDPOINT = "ep-20251203162437-62hp9"

class TestCase(BaseModel):
    module_name: str = Field(description="模块名称")
    title: str = Field(description="简练的标题")
    type: str = Field(description="Stream A (业务逻辑) 或 Stream B (通用/安全)")
    pre_condition: str = Field(description="前置条件，指测试开始前系统必须具备的状态或用户所处的环境")
    visual_evidence: str = Field(
        description="【视觉溯源】必须指明该用例是基于哪张图片的什么逻辑生成的。格式示例：'基于[参考图1-流程图]的否决分支' 或 '基于[参考图2-UI]的按钮布局'。如果仅基于文本，填'无'。"
    )
    steps: List[str] = Field(
        description="操作步骤。每步不超过15字。如果涉及UI元素，请在步骤中明确指出，例如'点击[参考图1]右上角的提交按钮'。"
    )
    expected_result: str = Field(description="预期结果。")


class ModulePlan(BaseModel):
    module_name: str = Field(description="模块名称")
    identified_inputs: List[str] = Field(
        description="扫描出的所有输入字段列表 (如：手机号框、金额框、备注框)"
    )
    business_constraints: List[str] = Field(
        description="扫描出的所有业务约束规则 (如：'订单发货后不可修改'、'必须勾选协议')"
    )

    planned_stream_a_scenarios: List[str] = Field(
        description="【计划清单】列出*尽可能全面的*（至少6个）打算生成的 Stream A (业务逻辑) 场景标题。"
    )
    planned_stream_b_scenarios: List[str] = Field(
        description="【计划清单】列出*尽可能全面的*（至少6个）打算生成的 Stream B (通用标准) 场景标题。覆盖空值、超长、XSS、幂等性等。"
    )

class TestSuite(BaseModel):
    detected_modules: List[str] = Field(
        description="【第一步：全局扫描】通读全文，列出文档中包含的所有功能模块名称。"
    )

    analysis_and_plan: List[ModulePlan] = Field(
        description="【第二步：深度规划】针对 detected_modules 中的*每一个*模块，制定详细的测试计划。**必须先完成此步骤的规划，才能生成下面的 cases。**"
    )

    cases: List[TestCase] = Field(
        description="""
        【第三步：执行生成】依据 analysis_and_plan 中规划的场景，生成详细的测试用例对象。
        **注意：生成的用例数量必须与planned_stream_a_scenarios中的数量一致
        **遍历所有模块**：不要遗漏任何一个识别到的模块。**
        为了减少token消耗，你无需输出planned_stream_b_scenarios的具体测试用例
        
        """
    )


def get_llm():
    if not API_KEY:
        raise ValueError("未配置 ARK_API_KEY")

    return ChatOpenAI(
        model=MODEL_ENDPOINT,
        openai_api_key=API_KEY,
        openai_api_base=BASE_URL,
        temperature=0.1,
        max_completion_tokens = 32000,
        model_kwargs={"response_format": {"type": "json_object"}}
    )


async def generate_test_cases_llm(parsed_data: list):
    print(f"正在构建 LangChain 请求 (Endpoint: {MODEL_ENDPOINT})...")

    llm = get_llm()
    parser = PydanticOutputParser(pydantic_object=TestSuite)

    content_parts = []

    content_parts.append({
        "type": "text",
        "text": "请分析以下PRD文档内容（包含文本和UI参考图），生成测试用例。"
    })

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

    system_prompt_text = """
Role: 资深 QA 架构师 (Senior QA Architect)
Mission: 你现在的任务是基于我提供的 PRD (需求文档) 和 UI 截图/流程图，为软件功能生成一份*地毯式覆盖*的测试用例。
Core Strategy (核心策略): 为了保证用例既懂业务又懂技术，你必须严格执行 “双流生成策略” (Two-Stream Strategy)：

🌊 Stream A - 深度定制流 (用于功能/业务逻辑)：
策略：严禁套用模板。你必须深度阅读 PRD 文本，像侦探一样提取业务规则、约束条件和流程跳转。
目标：覆盖核心业务闭环 + 复杂的业务逻辑冲突。

📋 Stream B - 标准化清单流 (用于非功能/UI/安全/边界)：
策略：不要发散思考。直接将文档中的具体字段（如“手机号框”、“金额框”）填入下文提供的 “通用检查清单” 中。
目标：覆盖输入边界、安全性、网络中断、交互反馈。

Phase 1: 👁️ 视觉与逻辑提取 (Visual & Context Analysis)
在生成具体用例前，请先在思维链 (CoT) 中执行以下分析：
视觉锚点提取：
🔀 流程图：提取每一个 Yes/No 判定节点，识别所有“拒绝”或“异常”的分支路径。
🖼️ UI 设计图：识别页面上所有的交互元素（输入框、按钮、链接）及其状态（默认置灰、红色必填星号）。
实体映射：将 UI 上的元素映射到 Stream B 的清单中（例如：识别到“身份证号”输入框 -> 准备应用“文本型字段”检查清单）。

Phase 2: 🌊 Stream A - 深度业务逻辑生成 (Customized Business Logic)
此部分的用例必须直接来源于 PRD 的文字描述或流程图逻辑。
1. 🟢 核心业务闭环 (Happy Path) [优先级 P0]
指令：提取 PRD 中的主流程路径（用户最希望完成的那件事）。
要求：前置满足 + 输入合法 + 操作正确 = 成功。
写法示例：“使用未注册手机号 + 正确验证码完成注册，并验证页面自动跳转至首页。”

2. 🔴 业务规则冲突与逻辑裂变 (Business Violations) [优先级 P1]
指令：寻找文档中的**“约束条件”**（必须、不可、只有...才...），利用 “场景裂变” 技术生成反向用例：
状态冲突：对处于“{{中间状态}}”的数据执行“{{互斥操作}}”。（例：对“已发货”订单点击“修改地址”）
依赖缺失：跳过前置步骤直接执行后续操作。（例：未勾选“用户协议”直接点击注册）
数据约束：违反唯一性、库存限制、时效性。（例：选择库存为 0 的商品提交订单）
权限越界：普通用户尝试访问管理员功能/接口。

🚨 步骤生成规范 (Atomic Steps Rules)
图文结合：步骤中必须引用图片特征。
Evidence标注：在 visual_evidence 字段填写例如 "基于[参考图1-UI]的按钮置灰状态"。
动作分离：严禁将“填写并提交”合并。必须拆分为：1. 填写{{字段}}... 2. 点击{{按钮}}...。
数据抽象化：
✅ 正确：写 "输入符合{{规则}}的有效数据"。
❌ 错误：不要硬编码 "输入 test/123456"。

### 输出格式
{format_instructions}
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_text),
        HumanMessage(content=content_parts)
    ])

    generation_chain = prompt | llm

    try:
        print("正在调用 LLM 进行推理...")

        # 2. 获取原始响应 (Response)
        response = await generation_chain.ainvoke({
            "format_instructions": parser.get_format_instructions()
        })

        # 3. 提取并打印原始内容
        # 如果使用的是 ChatModel (如 GPT-4, Claude)，结果在 .content 中
        # 如果使用的是普通 LLM，结果直接就是字符串
        raw_content = response.content if hasattr(response, "content") else response

        print("\n========== LLM 原始输出 Start ==========")
        print(raw_content)
        print("========== LLM 原始输出 End ==========\n")

        # 4. 手动调用 parser 进行解析
        # 注意：parser.parse 通常是同步方法，直接传入字符串即可
        result: TestSuite = parser.parse(raw_content)

        print("\n--- Model CoT Analysis ---")
        # 增加 getattr 保护，防止解析出的对象缺失字段导致报错
        print(getattr(result, "detected_modules", "No modules detected"))
        print(getattr(result, "analysis_and_plan", "No analysis"))
        print("--------------------------\n")

        final_cases = [case.dict() for case in result.cases]
        final_analysis = [plan.dict() for plan in result.analysis_and_plan]

        return {
            "cases": final_cases,
            "analysis": final_analysis
        }

    except Exception as e:
        print(f"LangChain 处理失败: {e}")
        # 在错误处理中，如果 raw_content 存在，也可以选择将其打印或记录下来以便调试
        # print(f"错误发生时的原始内容: {locals().get('raw_content', '未获取到内容')}")
        return {"cases": [], "analysis": [], "error": str(e)}