# MCP Agent 项目简历与面试准备

## 背景定位

你有四年后端开发经验，正在转向 Agent / MCP / RAG 工程化研发方向。

你的核心优势不是“会调用大模型 API”，而是能够把后端工程能力迁移到 Agent 系统中，包括：

- 协议服务设计
- API / Tool Gateway 设计
- 状态管理
- 参数校验
- 流程编排
- 错误恢复
- 安全边界
- 可观测性
- 生产化落地

推荐个人定位：

> 后端工程背景的 Agent Infra / Agent Tooling 开发者，擅长将复杂后端能力通过 MCP、工具编排、状态机和上下文管理接入 LLM Agent，并用工程化手段提升 Agent 工具调用可靠性。

---

# 一、简历版项目描述

## 项目名称

**MSInsight MCP Bridge：面向性能分析场景的渐进式披露 Agent 工具网关**

---

## 版本一：偏工程落地

设计并实现一个基于 MCP 协议的性能分析 Agent 工具网关，用于连接 LLM Agent 与 C++ 性能 Profiling 后端。系统采用 **Progressive Disclosure Meta-Tool Gateway** 架构，仅向大模型暴露 `search_profiler_tools` 与 `execute_profiler_tool` 两个 meta-tools，通过 Playbook、状态机、参数校验和上下文管理机制约束 Agent 的工具调用路径，降低 LLM 幻觉调用、跳步执行和参数错误风险。

主要工作：

- 基于 Python MCP SDK 构建 MCP Server，支持 stdio、SSE、WebSocket 多种传输模式。
- 设计 meta-tool 网关，仅暴露两个统一入口，隐藏底层原子工具，减少 LLM 工具选择复杂度。
- 设计 Playbook-driven SOP 机制，通过 YAML 定义性能分析流程、工具依赖、上下文输入输出和决策点。
- 实现状态机校验机制，对工具执行顺序、前置依赖、上下文变更进行强约束。
- 实现 Context Board，统一管理参数自动补全、结果注册、决策记录、缓存失效和分析文件切换。
- 使用 Pydantic 对工具参数进行运行时校验，提供 LLM 友好的错误反馈。
- 设计 DAG Playbook 继承与分支机制，支持从基础分析流程扩展到深度分析场景。

项目亮点：

- 将传统后端状态机、参数校验、网关设计应用到 Agent 工具调用治理中。
- 通过渐进式披露机制降低 LLM 调用复杂度，提高工具使用可靠性。
- 支持后续接入 RAG 知识库，作为 Playbook-aware 知识增强层。

---

## 版本二：偏 Agent / AI Infra

负责设计并实现一个面向性能诊断场景的 **Agent Tool Orchestration Layer**。系统基于 MCP 协议将 LLM Agent 与 C++ Profiling 后端连接起来，通过 meta-tool、Playbook、Context Board 和状态机约束工具调用流程，实现从“自由工具调用”到“受控 SOP 执行”的转变。

主要工作：

- 构建 MCP Server，封装 C++ Profiling 能力并对外提供标准化 Agent 工具接口。
- 设计 Progressive Disclosure 机制，仅向 LLM 暴露少量高层工具，底层工具通过服务端网关按步骤释放。
- 实现 Playbook Registry，支持基于 YAML 的分析流程声明、继承、DAG 分支和关键词检索。
- 实现 StepNavigator，根据当前执行历史自动推导下一步工具及参数 Schema。
- 实现 Context Board，解决多轮 Agent 工具调用中的参数传递、上下文记忆、决策注册和缓存失效问题。
- 通过 Pydantic 参数校验和 requires 依赖校验，提升 Agent 工具调用的确定性和可恢复性。
- 预留 RAG 融合路径，使知识库能够在每个 Playbook Step 中提供解释增强、历史案例和判断依据。

---

## 版本三：精简版

**MSInsight MCP Bridge｜Agent 工具编排与性能分析网关**

- 基于 MCP 协议实现 LLM Agent 与 C++ Profiling 后端的桥接服务，支持 stdio / SSE / WebSocket 多传输模式。
- 设计 Progressive Disclosure Meta-Tool Gateway，仅暴露两个 meta-tools，隐藏底层原子工具，降低 LLM 工具幻觉和误调用风险。
- 基于 YAML Playbook 实现性能分析 SOP 编排，支持步骤依赖、上下文输入输出、决策点和 DAG 分支继承。
- 实现 Context Board 与 StepNavigator，支持参数自动补全、结果注册、步骤推进、缓存失效和上下文回滚。
- 引入 Pydantic 参数校验与服务端状态机拦截，保障 Agent 工具调用顺序和参数正确性。
- 规划 RAG 知识增强层，为每个分析步骤注入领域知识、历史案例和解释依据。

---

# 二、面试版讲法

## 30 秒版本

这个项目是我从后端转向 Agent 研发的一个核心实践。它不是简单把后端接口包装成 MCP tool，而是设计了一层 Agent 工具治理网关。

我们面对的问题是：性能分析流程很依赖 SOP，LLM 如果直接看到几十个底层工具，很容易乱调、跳步骤、填错参数。所以我设计了一个渐进式披露架构，只暴露两个 meta-tools：一个用于搜索和选择分析剧本，一个用于执行当前允许的底层工具。真正的工具顺序、参数流转、上下文状态都由服务端的 Playbook、状态机和 Context Board 控制。

这个设计本质上是把后端里的网关、状态机、参数校验、流程编排能力迁移到 Agent 工具调用场景里，让 Agent 能稳定地使用复杂后端能力。

---

## 1 分钟版本

这个项目是一个基于 MCP 协议的性能分析 Agent 网关，用来连接 LLM Agent 和 C++ Profiling 后端。

一开始如果直接把所有 profiling 能力暴露成 MCP tools，会有几个问题：LLM 不知道该先调哪个工具，可能跳过初始化步骤，可能使用错误参数，也可能在多轮分析中丢失上下文。所以我没有采用“工具全量暴露”的方式，而是设计了 Progressive Disclosure Meta-Tool Gateway。

整个 MCP Server 只暴露两个工具：

- `search_profiler_tools`：根据用户问题搜索并选择分析 Playbook；
- `execute_profiler_tool`：执行底层原子工具，但会经过服务端状态机校验。

底层的分析流程由 YAML Playbook 定义，包括步骤依赖、工具输入输出、上下文映射和决策点。执行过程中，Context Board 会记录 trace 文件、iteration、rank、用户选择等上下文，并支持参数自动补全和缓存失效。StepNavigator 会根据当前执行历史自动给出下一步工具和参数 Schema。

所以 LLM 不是自由地调用任意工具，而是在服务端约束下逐步完成分析流程。这个架构比较适合性能分析、故障排查、运维诊断这类强 SOP 场景。

---

## 3 分钟深挖版本

这个项目的背景是我们有一个 C++ 性能 Profiling 后端，能做 trace 文件导入、通信耗时分析、慢节点分析等操作。我需要把这些能力接入到 LLM Agent 中，让 Agent 能根据用户描述自动完成性能排查。

但我没有直接把所有 C++ 后端能力暴露成 MCP tools，因为这样会有几个风险。

第一，工具数量多时，LLM 的 tool selection 不稳定。  
第二，性能分析是有前置依赖的，比如必须先导入 trace 文件，才能分析 iteration 或 rank。  
第三，很多参数来自上一步结果，比如慢 rank、iteration id、节点 id，如果完全依赖 LLM 自己记忆，很容易错。  
第四，用户中途切换分析文件或回退步骤时，缓存和上下文需要同步失效。

所以我设计了一个“渐进式披露”的 MCP 网关。

在 MCP 层只暴露两个 meta-tools：

```text
search_profiler_tools(query, select_playbook?)
execute_profiler_tool(tool_name, arguments)
```

真正的内部工具通过 `@internal_tool` 注册，但不直接暴露给 LLM。LLM 只能先搜索 Playbook，然后按照服务端返回的下一步 Schema 调用 `execute_profiler_tool`。

Playbook 是 YAML 定义的，里面描述：

```yaml
steps:
  - tool_name: import_trace_file
    action: 导入 trace 文件
  - tool_name: communication_duration_iterations
    action: 分析通信耗时
    requires: [import_trace_file]
    outputs:
      - key: iteration_candidates
        from_path: result.iterations
    decision_point:
      description: 选择要分析的 iteration
```

服务端执行时会做几层控制：

1. **全局前置校验**：没有导入 trace 文件就不能执行分析工具。
2. **Playbook requires 校验**：不能跳过前置步骤。
3. **Pydantic 参数校验**：参数类型和必填项必须正确。
4. **Context Board 参数补全**：如果参数可以从上下文推导，就自动补齐。
5. **结果注册**：从工具结果中提取关键字段写入上下文。
6. **缓存失效**：如果用户改变关键参数，后续步骤结果自动失效。
7. **StepNavigator 自动推进**：每次执行后返回下一步工具和参数 Schema。

我觉得这个项目的核心价值是：它不是简单做一个 MCP wrapper，而是把 Agent 工具调用变成了一个可治理、可约束、可恢复的后端流程编排系统。

后续我准备把 RAG 知识库作为 Playbook-aware Context Layer 接进来，让每个步骤执行后都能根据当前 playbook、step、tool result 和 Context Board 检索相关知识，给出解释、历史案例和判断依据。但 RAG 只作为解释增强层，不改变状态机和工具执行路径，避免破坏现有的确定性。

---

# 三、面试官可能追问的问题与回答方向

## 1. 为什么不直接暴露所有 MCP tools？

回答重点：

> 因为这个场景不是开放式问答，而是强 SOP 的性能分析流程。直接暴露所有工具会导致 LLM 工具选择不稳定、跳过前置步骤、参数传递错误。  
> 所以我采用 meta-tool 网关，只暴露少量入口，底层工具由服务端根据 Playbook 和状态机逐步释放。

可补充：

- 工具越多，LLM tool selection 越不稳定；
- 服务端校验比 prompt 提示更可靠；
- 渐进式披露可以降低上下文噪声。

---

## 2. 你的 MCP 和普通 API Gateway 有什么区别？

回答重点：

> 普通 API Gateway 更多关注鉴权、路由、限流、协议转换；这个 MCP Gateway 关注的是 Agent 工具调用治理，包括工具选择约束、执行顺序约束、上下文记忆、参数补全和下一步引导。

类比：

```text
API Gateway 管请求入口
MCP Meta-Tool Gateway 管 Agent 行为路径
```

---

## 3. Playbook 是什么？为什么不用代码硬编码流程？

回答重点：

> Playbook 是可配置的分析 SOP。用 YAML 定义步骤、依赖、输入输出和决策点，可以让流程和代码解耦。新增分析场景时，不需要改核心执行逻辑，只需要新增或继承 Playbook。

强调：

- 更适合专家知识沉淀；
- 支持继承和复用；
- 让业务流程可审查、可版本化。

---

## 4. Context Board 解决了什么问题？

回答重点：

> 解决多轮 Agent 调用中的上下文丢失和参数传递问题。比如上一步返回了可选 iteration，用户选择其中一个，后续工具需要自动使用这个 iteration id。Context Board 负责把这些中间状态结构化保存，并支持参数自动补全、结果注册和缓存失效。

例子：

```text
工具 A 输出 slow_rank_candidates
用户选择 rank 3
Context Board 注册 selected_rank = 3
工具 B 参数 rank_id 自动补全为 3
```

---

## 5. 状态机是怎么防止 LLM 乱调工具的？

回答重点：

> 每个工具执行前都会检查当前 Playbook 的 requires 依赖，以及全局必备前置条件。如果依赖未满足，服务端直接拒绝执行，并返回明确错误信息和下一步建议。  
> 这不是 prompt 约束，而是服务端硬约束。

---

## 6. 为什么需要 Pydantic 参数校验？MCP schema 不够吗？

回答重点：

> MCP schema 能告诉 LLM 参数结构，但不能保证 LLM 一定按 schema 调用。并且我的 `execute_profiler_tool` 是 meta-tool，内部工具的真实 schema 是动态释放的，所以需要在服务端用 Pydantic 做运行时强校验。

强调：

- MCP schema 是提示；
- Pydantic 是服务端强校验；
- 错误信息要 LLM-friendly，便于自动修正。

---

## 7. 你这个系统如何支持多轮对话？

回答重点：

> 多轮对话的状态不依赖 LLM 自己记忆，而是由服务端维护。Session State 记录执行历史，Context Board 记录结构化上下文，StepNavigator 根据状态计算下一步。LLM 只需要按响应中的 schema 继续调用即可。

如果被追问多客户端并发：

> 对于 stdio 本地模式，全局 state 可以工作；但对于 SSE/WebSocket 多客户端模式，必须将 state 改为 session-scoped。每个 MCP connection 或业务 session 应该持有独立 SessionState、Context Board 和 execution history，避免不同用户 trace 分析上下文串扰。

---

## 8. 为什么支持 DAG Playbook？

回答重点：

> 因为性能分析通常不是单一路径。基础分析完成后，可能根据结果进入通信分析、慢节点分析、内存分析等分支。DAG Playbook 可以复用公共初始化步骤，同时在后续分支中保留共享上下文，避免重复执行。

---

## 9. 如果接 RAG，你会怎么接？

回答重点：

> 我不会把 RAG 暴露成一个让 LLM 自由调用的独立工具，而是作为 MCP 内部的 Playbook-aware 知识增强层。  
> 它读取当前 playbook、step、tool result 和 Context Board，返回解释、判断依据和历史案例，但不修改状态机，不决定工具执行顺序。

一句话：

```text
Playbook / State 是事实源，RAG 是解释源。
```

---

## 10. 这个项目体现了你从后端转 Agent 的哪些能力？

回答重点：

> 我不是只会调 LLM API，而是能把后端工程能力迁移到 Agent 系统里。比如协议服务、状态管理、参数校验、流程编排、网关设计、错误恢复、可观测性和安全边界。  
> Agent 研发的难点不是让模型回答一次，而是让它稳定地使用工具完成复杂任务。

重点句：

> 我理解的 Agent 工程化，本质是把不确定的模型行为放进确定的后端约束系统里。

---

# 四、需要重点准备的内容

## A. MCP 基础

需要能讲清楚：

- MCP 是什么？
- MCP Server / Client / Tool 的关系是什么？
- MCP 和普通 HTTP API 的区别是什么？
- MCP tool schema 是怎么给 LLM 使用的？
- stdio、SSE、WebSocket / Streamable HTTP 传输有什么区别？
- FastMCP 和原生 MCP SDK 的区别是什么？
- 为什么本项目用原生 SDK，或者为什么可以迁移到 FastMCP？

建议表达：

> MCP 是一种让 LLM Agent 标准化调用外部工具和上下文资源的协议。它把工具能力、参数 schema、执行结果封装成统一接口，让不同 Agent Client 能以一致方式接入后端能力。

---

## B. Agent Tool Calling 机制

需要准备：

- LLM 是如何选择 tool 的？

  - 首先在工具定义阶段，开发者会提供工具的描述、schema等内容
  - LLM会根据用户意图及工具描述判断是否要进行工具的调用，生产参数json交由程序调用

- tool description 对调用稳定性有什么影响？

  - 好的description能够清晰的告诉LLM工具描述，LLM能够自行判断tool的调用时机，也能提供few-shot辅助工具更好的理解，但是对于LLM来说他只是一种软约束，在上下文过长时对工具的描述注意力会下降，以及同义词会造成误调用。应该在代码层面进行JSON Schema、Pydantic的强校验，使用动态工具注入，增加负向提示词等。

- 工具太多会带来什么问题？

  - 上下文窗口爆炸，会引起 模型端注意力涣散、语义空间重叠；在呈现效果上，会出现规划链条断裂(跳步问题)与格式坍塌（格式错误、参数错误、漏掉required）；工程端：会导致首字延迟飙升；token成本增长。面对这类问题可以通过动态路由、工具检索；分层agent架构；精简Schema进行优化

- 为什么需要减少 exposed tools（工具暴露）？

  - 同上

- 什么是 progressive disclosure（渐进式披露）？

  - 在LLM和Agent中，渐进式披露是指不要试图一次性让大模型昨晚所有的决定，而是通过“漏斗式”或“多阶段”的机制，让模型在特定的步骤只接触特定的工具和信息。通常有三种实现方式
    - 工具层面的渐进：LLM不会感知到所有的工具，而是按需去获取
    - 工作流层面的渐进：用户在执行完一步后，服务端才返回下一步要如何执行
    - 参数/Schema层的渐进：先披露核心参数，程序发现缺了控制细节后，再要求模型补充

- 什么是 tool hallucination（工具幻觉）？

  - 工具幻觉是指LLM在进行Tool Calling时，生成了不存在、不合法或不适合当前上下文的工具调用（调用了不存在的工具、调用了存在但当前不该调用的工具、参数幻觉），可以从不同的层面去处理这个问题：*第一是模型输入侧，减少模型犯错的机会，包括工具命名清晰、schema* *严格、工具数量收敛、渐进式披露和* *prompt* *规则。**第二是服务端执行侧，不能信任模型生成的* *tool* *第二是服务端执行侧，不能信任模型生成的* *tool*。*第三是执行后恢复和安全侧，工具结果要结构化，错误信息要可恢复，高风险操作要用户确认，并且要有审计日志和最小权限控制。*

- 如何防止 LLM 调不存在的工具或错误参数？

  - 模型测：工具命名、描述要清晰，schema严格，工具数量要收敛
  - 服务端：不能信赖模型生成的tool，要白名单、参数校验、权限校验、前置依赖的校验
  - 执行后恢复和安全侧：高风险操作要用户确认，并要有审计日志和最小权限控制

  LLM可以生成调用意图，但是否允许执行必须由服务端决定

重点表达：

> 工具调用不能只靠 prompt，需要服务端强校验和流程约束。

---

## C. 当前项目架构

要能画出这张图：

```text
LLM Agent
  |
  | MCP
  v
search_profiler_tools / execute_profiler_tool
  |
  v
Meta-Tool Gateway
  |
  +--> Playbook Registry
  +--> Session State
  +--> Context Board
  +--> StepNavigator
  +--> Pydantic Validator
  |
  v
Internal Tools
  |
  v
C++ Profiling Backend
```

每个模块准备一句话解释：

- **Meta-Tool Gateway**：统一工具入口，拦截非法调用。
- **Playbook Registry**：加载和查询 YAML SOP。
- **Session State**：记录当前 playbook 和执行历史。
- **Context Board**：管理参数、结果、决策和缓存失效。
- **StepNavigator**：计算当前进度和下一步。
- **Internal Tools**：真正调用 C++ profiling 后端的原子能力。

---

## D. 后端能力如何迁移到 Agent 研发

这是转型面试的重点。

准备表达：

> 我之前做后端时关注接口设计、状态一致性、参数校验、错误处理和服务稳定性。转到 Agent 研发后，我发现这些能力反而更重要，因为 LLM 行为有不确定性，需要用后端工程手段做约束。  
> 所以这个项目里我没有把 LLM 当成完全可信的调用方，而是把它当成一个可能犯错的客户端，通过网关、状态机、schema、Pydantic、Context Board 来保证执行正确性。

---

## E. 可靠性设计

需要准备这些点：

- 服务端强校验，而不是只靠 prompt；
- requires 防跳步；
- Pydantic 防参数错误；
- Context Board 防上下文丢失；
- 文件切换时 reset context；
- 参数变化时 invalidation；
- DAG 切换时清理非共享状态；
- 错误信息要能指导 LLM 修正。

---

## F. 多 Session / 并发问题

这个点很容易被高级面试官问。

需要准备：

- 当前是否是全局 state？
- 如果是，全局 state 在 SSE/WebSocket 下有什么问题？
- 如何改成 session-scoped state？
- MCP session 如何映射到业务 session？
- WebSocket 每个连接是否应该有独立状态？
- stdio 单用户模式和远程多用户模式区别是什么？

建议回答：

> 对于 stdio 本地模式，全局 state 可以工作；但对于 SSE/WebSocket 多客户端模式，必须将 state 改为 session-scoped。每个 MCP connection 或业务 session 应该持有独立 SessionState、Context Board 和 execution history，避免不同用户 trace 分析上下文串扰。

---

## G. RAG 融合方案

准备四句话：

1. RAG 不应该替代 Playbook 状态机；
2. RAG 作为 Playbook-aware Context Layer；
3. 输入是当前 playbook、step、tool result、context；
4. 输出是解释、历史案例、判断依据和引用。

重点边界：

```text
RAG 不修改状态，不决定工具顺序，不生成内部 tool_name。
```

---

## H. 和 LangChain / AutoGen / CrewAI 的区别

可能被问：为什么不用现成 Agent 框架？

回答：

> LangChain / AutoGen 更偏 Agent 编排框架，而我这个项目解决的是底层工具治理和协议接入问题。MCP 是工具接入协议，Playbook Gateway 是对工具调用路径的约束。它可以被 LangChain、Claude Desktop 或其他 MCP Client 调用，不绑定某个 Agent 框架。

---

## I. 项目不足和优化方向

可以主动说：

1. **多 session 状态隔离需要加强**
   - 从全局 state 改为 session-scoped state。

2. **响应结构可以更机器可读**
   - 目前 next step 主要是 markdown，可以增加标准 JSON block。

3. **RAG 还没完全融合**
   - 后续作为解释增强层接入。

4. **可观测性可以增强**
   - 增加 tracing、tool execution span、playbook progress metrics。

5. **权限和安全可以细化**
   - 对不同工具、路径、文件类型增加更细粒度控制。

---

# 五、个人定位与自我介绍

## 个人定位

### 定位一

**后端工程背景的 Agent Infra / Agent Tooling 开发者**

### 定位二

**擅长将复杂后端能力 MCP 化、工具化、Agent 化的工程师**

### 定位三

**面向企业场景的 Agent 工程化开发者，关注工具治理、状态管理和可靠性**

---

## 自我介绍版本一：偏正式

我有四年后端开发经验，最近主要在往 Agent 工程化方向转。相比单纯调用大模型 API，我更关注如何让 Agent 稳定、安全、可控地使用复杂后端能力。

我最近做的一个项目是基于 MCP 协议的性能分析工具网关。这个项目把 C++ Profiling 后端接入到 LLM Agent 中，但没有简单暴露所有底层工具，而是设计了一个渐进式披露的 meta-tool 网关，只暴露两个高层工具，由服务端通过 Playbook、状态机、Context Board 和参数校验来控制 Agent 的调用路径。

这个项目让我比较系统地实践了 MCP、tool calling、Agent 状态管理、工具编排和 RAG 融合设计。我觉得我的优势是能把后端工程中的稳定性、状态一致性、接口治理经验迁移到 Agent 系统建设里。

---

## 自我介绍版本二：偏技术亮点

我之前主要做后端开发，有四年经验。现在转向 Agent 研发，重点关注 Agent 和后端系统的结合。

我做过一个 MCP Server 项目，用来连接 LLM Agent 和 C++ 性能分析后端。这个项目的核心不是简单封装 API，而是解决 LLM 工具调用不稳定的问题。我设计了 Progressive Disclosure Meta-Tool Gateway，只暴露两个 meta-tools，底层工具通过 Playbook 和状态机逐步释放。执行过程中会做参数自动补全、Pydantic 校验、前置依赖校验、上下文注册和下一步 schema 自动生成。

我理解的 Agent 工程化，不是让模型自由发挥，而是把模型的不确定性放进确定的后端约束系统里。这也是我从后端转 Agent 研发时比较有优势的地方。

---

# 六、建议重点背的几句话

1. **这个项目不是 MCP wrapper，而是 Agent 工具治理网关。**

2. **我没有把 LLM 当成可信调用方，而是像后端对外部客户端一样，对它做参数校验、状态校验和权限边界控制。**

3. **Progressive Disclosure 的核心是减少 LLM 一次性看到的工具和上下文，让它每一步只面对当前可执行的操作。**

4. **Playbook / State Machine 是事实源，RAG 只是解释源。**

5. **Agent 工程化的关键，是用确定性的后端系统约束不确定的模型行为。**

6. **我的后端经验可以迁移到 Agent 研发里的协议服务、状态管理、工具治理、错误恢复和生产化落地。**

---

# 七、需要补齐的知识短板

## MCP

- MCP lifecycle
- Tool / Resource / Prompt 区别
- stdio vs SSE vs Streamable HTTP
- FastMCP vs 原生 SDK
- MCP Client 和 Server 如何通信

## LLM Tool Calling

- function calling / tool calling 原理
- schema 对 tool calling 的影响
- tool selection 失败原因
- tool hallucination
- tool result 如何影响下一轮推理

## Agent 架构

- ReAct
  - 思考
  - 行动
  - 观察

- Plan-and-Execute
  - 先计划后执行

- Workflow Agent vs Autonomous Agent
- Memory / State / Context 区别
- multi-agent 什么时候需要，什么时候不需要

## RAG

- embedding
- chunking
- retrieval
- rerank
- hybrid search
- citation
- query rewrite
- RAG hallucination
- GraphRAG / Agentic RAG 基础概念

## 工程化

- 状态隔离
- 并发安全
- 参数校验
- 超时重试
- 幂等性
- 日志与 tracing
- 工具调用审计
- 安全边界

---

# 八、面试时可以反问的问题

1. 你们现在 Agent 是更多偏 Workflow，还是偏 Autonomous Agent？
2. 工具调用失败时，你们是靠模型自修复，还是服务端有明确错误恢复机制？
3. 你们的 RAG 是独立问答系统，还是会参与业务流程编排？
4. Agent 的状态是放在 prompt 里，还是服务端维护？
5. MCP 在你们团队是作为标准工具协议使用，还是内部有自定义 tool runtime？
6. 你们更关注模型效果，还是 Agent 系统的稳定性和可观测性？

---

# 九、最终包装方向

最终可以这样总结：

> 四年后端经验，正在转向 Agent 研发。优势不是只会调用模型，而是能把复杂后端能力通过 MCP、工具编排、状态机和上下文管理接入 Agent，并用工程化手段提升 Agent 工具调用的可靠性。

适合投递方向：

- Agent Infra Engineer
- AI Application Backend Engineer
- LLM 应用工程师
- MCP / Tooling Engineer
- RAG / Agent 工程化方向
- 企业 AI 助手后端开发
- 智能运维 / AIOps Agent 开发
