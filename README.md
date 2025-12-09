# 🚀 LLM-based PRD to Test Case Generator

本项目是一个基于 **FastAPI** 和 **LangChain** 的自动化测试用例生成工具。它利用大语言模型（支持多模态视觉能力）直接解析 **飞书 (Feishu/Lark) 在线文档**，理解产品需求（PRD）中的业务逻辑和 UI 设计图，自动生成高质量的测试计划与详细用例。

## ✨ 核心特性

* **📚 飞书文档深度解析**：支持解析飞书 Wiki 和 Docx 文档，自动提取标题、列表、代码块，并智能处理文档中的 **图片**（UI 设计图、流程图）。
* **👁️ 多模态视觉理解**：通过 LLM 的视觉能力，分析流程图中的分支（Yes/No 判定）和 UI 图中的交互元素（按钮状态、输入框限制）。
* **🧠 三流策略 (Three-Stream Strategy)**：
    * **Stream A (业务闭环)**：覆盖核心 Happy Path 和业务规则冲突（P0/P1）。
    * **Stream B (交互标准)**：覆盖输入域校验、UI 状态（Hover/Disabled）检查。
    * **Stream C (跨模块集成)**：覆盖数据流转和副作用（Side Effects）。
* **⚡ 流式响应 (Streaming)**：采用 Server-Sent Events (SSE) 风格的流式输出，实时向前端反馈解析进度、提取的图片、分析策略及最终用例。

## 📂 项目结构

```text
.
├── main.py             # FastAPI 服务入口，处理 HTTP 请求与流式响应
├── model.py            # AI 核心逻辑，封装 LangChain 调用、Prompt 策略与 Pydantic 模型
├── prd_parser.py       # 飞书文档解析器，处理 API 鉴权、文本提取与图片压缩
├── .env                # 环境变量配置 (需自行创建)
└── requirements.txt    # 项目依赖
