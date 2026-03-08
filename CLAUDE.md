# CLAUDE.md

## 项目初始化
- 新项目第一次使用：创建 `planning/`（存放 context.md、logging.md）和 `reports/`（存放总结报告）
- 初始化完成后立即填写 planning/context.md 的项目简介、技术栈、环境配置区块

## 启动流程
- 新对话必须按顺序读取：CLAUDE.md → planning/context.md
- 禁止未读取以上文件就扫描整个项目代码
- 通过 planning/context.md 定位目标文件，不要全项目扫描

## 常用命令
- 运行：`uvicorn backend.main:app --reload`
- 测试：`pytest tests/ -v`
- Lint/格式化：`pylint backend/` 和 `bandit -r backend/`
- 安装包：`pip install -r backend/requirements.txt`

## 计划文档（按需读取）
- 计划文档指 planning/PROJECT_PLAN.md（项目规划）和 planning/TODOLIST.md（任务清单）
- 日常开发（改 bug、单模块修改、改 UI）：不需要读取
- 以下情况必须额外读取 planning/PROJECT_PLAN.md：
  - 新增模块
  - 修改模块间的依赖关系
  - 重构或优化架构
  - 改动涉及 2 个以上模块

## context.md 维护规则

### 触发时机（以下任一情况立即更新）
- 完成任务或模块开发后
- 新增文件时 → 添加到模块索引
- 删除或重命名文件后 → 从模块索引中移除或更新对应条目
- 修改已有方法签名（参数、返回值、名称）后 → 更新模块索引中的对应方法记录
- 新增或移除模块间依赖后 → 更新"依赖关系"区块
- 关键配置参数变更后 → 更新"关键配置参数"区块

### 更新内容
- 完成了什么、文件路径、关键接口、依赖关系、时间戳
- 模块索引只记录公开接口和关键方法，私有方法不需要列出
- planning/context.md 无行数限制，内容增多属正常现象

### 一致性检查
- 开始新任务前，检查 planning/context.md 与实际代码是否一致，不一致则先修正
- 超过 7 天未更新的模块，开始相关任务前主动确认信息是否准确

## TODOLIST.md 维护规则
- 完成任务后标记已完成
- 发现新的子任务时添加到 planning/TODOLIST.md
- 保持与 planning/context.md 一致

## logging.md 维护规则
- 每次代码修改完成后，在 planning/logging.md 追加一条记录
- 格式：`## [YYYY-MM-DD] 类型 | 简述`，包含：变更内容、涉及文件、测试结果
- 只追加，不修改历史记录；无行数限制
- 类型标签：`优化` / `修复` / `重构` / `新增`

## 安全规范
- 关键配置参数的实际值（API Key、密码等）禁止写入 planning/context.md
- 敏感值必须存放在 .env 文件中，.env 必须加入 .gitignore，禁止上传 GitHub
- planning/context.md 的"关键配置参数"区块只记录参数名和文件位置，不记录实际值

## 语言规范
- 代码（变量名、函数名、注释）使用英文
- 开发文档（CLAUDE.md、planning/*.md 等）使用中文
- 所有与用户的对话回复使用中文

## 开发环境
- 所有命令在虚拟环境中执行，禁止使用全局环境
- 虚拟环境路径：`venv/`（项目根目录）
- 激活（Linux/WSL）：`source venv/bin/activate`
- 激活（Windows CMD）：`venv\Scripts\activate`
- Python 版本：3.12.3

## 开发行为
- 先讨论方案，等我确认后再执行代码
- 不要过度设计，只做当前需要的功能
- 只关注 planning/context.md 模块索引中涉及的模块，稳定区不要随意改动
- 每完成一个任务后，必须进行测试验证，确认功能正常后才能继续下一个任务
- 测试失败必须修复，不得带着问题继续推进

## 文件同步规则
- CLAUDE.md 与 agents.md 内容必须始终保持一致
- 修改 CLAUDE.md 后，立即将相同内容同步写入 agents.md
- 修改 agents.md 后，立即将相同内容同步写入 CLAUDE.md
- 两个文件唯一区别：CLAUDE.md 第一行标题为 `# CLAUDE.md`，agents.md 第一行标题为 `# agents.md`
