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
MODEL_ENDPOINT = "ep-20251125155621-z8fhp"

class TestCase(BaseModel):
    module: str = Field(
        description="功能模块名称。请依据 PRD 的业务结构划分，例如 '搜索模块'、'支付模块'、'审批流' 等。")
    title: str = Field(description="测试标题。必须原子化")
    pre_condition: str = Field(description="前置条件，需明确状态")
    visual_evidence: str = Field(
        description="【视觉溯源】必须指明该用例是基于哪张图片的什么逻辑生成的。格式示例：'基于[参考图1-流程图]的否决分支' 或 '基于[参考图2-UI]的按钮布局'。如果仅基于文本，填'无'。"
    )

    steps: List[str] = Field(
        description="操作步骤。如果涉及UI元素，请在步骤中明确指出，例如'点击[参考图1]右上角的提交按钮'。"
    )
    expected_result: str = Field(description="预期结果。")


class TestSuite(BaseModel):
    detected_modules: List[str] = Field(
        description="【全局扫描】请先通读全文，列出文档中包含的所有功能模块名称。"
    )

    analysis: Dict[str, str] = Field(
        description="【覆盖率规划】这是一个字典。Key是模块名称（必须与 detected_modules 一致），Value是该模块的详细测试分析思路。"
    )

    cases: List[TestCase] = Field(
        description="【执行生成】基于 detected_modules 列表..."
    )


def get_llm():
    if not API_KEY:
        raise ValueError("未配置 ARK_API_KEY")

    return ChatOpenAI(
        model=MODEL_ENDPOINT,
        openai_api_key=API_KEY,
        openai_api_base=BASE_URL,
        temperature=0.1,
        max_tokens=4096,
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
你是一个追求“零漏测”的资深 QA 架构师。你的任务是基于 PRD 和 UI 截图，为任意软件功能（无论是金融、后台还是社交）生成**地毯式覆盖**的测试用例。

### 🧠 核心思维模型 (Universal Analysis Framework)
在生成用例前，你必须针对扫描到的每个模块执行以下 **发散分析**（CoT）：
1.  **规则提取**：先在思维中扫描 PRD，提取所有“必须”、“不可”、“依赖”等强约束条件。
2.  **输入遍历**：识别页面**所有**输入项。针对**每一个**输入项，设计独立的边界测试。
3.  **动作拆解**：识别页面**所有**操作按钮。针对**每一个**动作，设计状态流转和权限测试。

### 👁️ 视觉逻辑提取 (Visual Logic Extraction)
你必须区分不同图片的类型，并从中提取独特的测试点，填入 `visual_evidence` 字段：
1.  **当看到 🔀 流程图 (Flowcharts)**：
    * **路径遍历**：覆盖每一个 Yes/No 分支路径。
    * *生成策略*：为流程图的判定节点生成“业务逻辑异常”用例。
    * *证据标注*：`visual_evidence` 填写 "基于[参考图X-流程图]的否决分支"。
2.  **当看到 🖼️ UI 设计图 (UI Screenshots)**：
    * **布局与文案**：检查按钮置灰、文案提示、默认状态。
    * *生成策略*：生成“UI 反馈与交互”用例。
    * *证据标注*：`visual_evidence` 填写 "基于[参考图X-UI]的按钮默认状态"。

### 🚨 暴力覆盖率矩阵 (Explosive Coverage Matrix) - 数量协议
对于每一个功能模块，生成的用例**总数不得少于 8 条**，且必须严格遵守以下配比：

1.  **🟢 核心业务闭环 (Happy Path)** [1-2条]:
    * **定义**：前置满足 + 输入合法 + 操作正确 = 成功。
    * *通用逻辑*：覆盖最主干的成功流程。

2.  **🔴 业务逻辑与规则冲突 (Business Logic Violations)** [至少 3 条 - 必须多样化]:
    * **严禁偷懒！** 必须利用 **“场景裂变”** 寻找不同的逻辑切入点。
    * ❌ 错误：只生成一条笼统的“操作失败”。
    * ✅ 正确（裂变示例）：
        - 场景 A (状态冲突): 对“已完成/审批中”的数据执行“修改/删除”。
        - 场景 B (依赖缺失): 未完成前置步骤（如未勾选协议、未填必填项）直接提交。
        - 场景 C (数据约束): 违反唯一性（名称重复）、违反时效性（操作过期数据）。
        - 场景 D (权限身份): 普通用户尝试访问管理员功能/接口。

3.  **🟡 输入边界与格式 (Input Boundaries)** [至少 3 条 - 字段遍历]:
    * **遍历原则**：如果页面有 3 个输入框，必须分别为这 3 个框各生成一条异常用例。
    * ✅ 正确（遍历示例）：
        - 场景 A: [字段1-文本] 输入为空 / 超长 / Emoji / 敏感词。
        - 场景 B: [字段2-数值] 输入 0 / 负数 / 小数 / 非数字。
        - 场景 C: [字段3-文件] 格式不支持 / 体积超限。

4.  **🔵 UI 反馈与交互完整性 (UI & Interaction)** [1-2条]:
    * **中断与幂等**：快速连续点击提交按钮（防抖检查）、弱网下操作。
    * **默认与反馈**：检查 Placeholder、Loading 状态、Toast 提示文案，并引用 [参考图X]。

### 🚨 步骤生成规范 (Atomic Steps)
1.  **图文结合**：步骤中必须引用图片特征。
    * ✅ 写法：点击[参考图1]底部的红色“立即支付”按钮。
2.  **动作分离**：严禁将“填写并提交”合并。必须拆分为：1. 填写[具体字段]；2. 点击[具体按钮]。
3.  **数据抽象化 (等价类)**：
    -   ❌ 严禁硬编码：不要写 "输入 admin/123456"
    -   ✅ 有效等价类：写 "输入符合规则的有效数据（如：未注册手机号）"
    -   ✅ 无效等价类：写 "输入违反{{规则}}的数据（如：长度超过20字符）

### 输出格式
{format_instructions}
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_text),
        HumanMessage(content=content_parts)
    ])

    chain = prompt | llm | parser

    try:
        print("正在调用 LLM 进行推理 (包含 CoT 分析)...")
        result: TestSuite = await chain.ainvoke({
            "format_instructions": parser.get_format_instructions()
        })

        print("\n--- Model CoT Analysis ---")
        print(result.detected_modules)
        print(result.analysis)
        print("--------------------------\n")
        final_cases = [case.dict() for case in result.cases]
        return {"cases": final_cases}

    except Exception as e:
        print(f"LangChain 处理失败: {e}")
        return {"cases": [], "error": str(e)}