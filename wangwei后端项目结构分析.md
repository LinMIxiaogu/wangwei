# wangwei 后端项目结构分析

> 源码路径：`/Users/tanglulu/PycharmProjects/wangwei`  
> 分析重点：后端整体结构、AI 工作流设计、模块拆分、关键文件路径、技术栈与工程风险。  
> 结论先行：这是一个“视频转小红书笔记”的 AI 后端，不是传统 CRUD 后端。核心能力是把视频拆解为字幕、关键帧、风格、景点、热点、图片和文案，再通过 LangGraph 编排成一条多节点 AI 内容生产流水线，并通过 SSE 把每个节点的进度实时推给前端。

## 1. 项目定位

这个项目的主业务可以概括为：

用户上传或提供一个视频，后端自动完成以下事情：

1. 提取视频关键帧。
2. 抽取音频并做 ASR 语音识别。
3. 将关键帧和字幕按时间对齐。
4. 用 LLM / VLM 分析视频内容、选择关键图片、分析小红书风格。
5. 提取视频中的 POI / 景点，并调用内部 POI 服务补全景点详情。
6. 检索小红书热词与热榜内容。
7. 生成小红书标题、正文、话题标签。
8. 对图片进行增强、搜索替换和拼图。
9. 生成最终图文笔记。
10. 对最终笔记做 VLM 评分。
11. 可选调用小红书 MCP 工具发布笔记。

从代码结构看，项目核心不是“一个接口返回一个结果”，而是“一个长任务工作流”。每个节点会持续向前端推送状态，适合前端展示类似“AI 正在处理视频、正在分析风格、正在生成文案”的过程。

## 2. 技术栈

### 2.1 Web 服务层

- `FastAPI`：主 Web 框架。
- `uvicorn`：服务启动。
- `StreamingResponse`：用于 SSE 流式输出。
- `sse-starlette`：依赖中包含，但主链路主要直接使用 FastAPI 的 `StreamingResponse`。
- `pydantic`：请求、响应、状态数据建模。

关键路径：

- `src/main.py`：主 FastAPI 应用，也是大部分业务接口所在位置。
- `src/app/app.py`：一个更简单的视频上传示例应用，像是早期 demo 或独立测试入口，不是主业务入口。

### 2.2 AI 编排层

- `LangGraph`：工作流编排核心。
- `LangChain`：LLM 消息、模型封装、工具调用基础设施。
- `langchain-openai`：通过 OpenAI 兼容接口调用模型。
- `langchain-mcp-adapters`：连接 MCP 服务，用于小红书发布工具。
- `json_repair`：修复和解析 LLM 可能返回的不稳定 JSON。

关键路径：

- `src/graph/graph_builder.py`：注册 LangGraph 节点。
- `src/graph/state/types.py`：定义 LangGraph 全局 State。
- `src/graph/node/node.py`：大部分核心节点实现。
- `src/graph/node/node_by_xhs_style.py`：小红书风格分析节点。
- `src/graph/node/node_by_poi_extract.py`：景点 / POI 提取节点。
- `src/graph/node/node_by_xhs_cover.py`：封面图优化节点。
- `src/graph/node/xhs_note_text_node.py`：小红书热词 / 热点匹配节点。

### 2.3 模型调用层

项目里有两套模型调用方式：

1. `src/graph/llm/config.py`  
   面向固定 OpenAI 兼容模型的工厂，主要看到 `azure/gpt-5-chat-2025-08-07`，并集成 Langfuse callback。

2. `src/graph/llm/openrouter.py`  
   面向“按业务名选择模型”的工厂。它会根据环境变量里的 `LLM_MODEL_CONFIG_*` 配置，为不同业务节点选择不同模型或不同模型类型。

关键路径：

- `src/service/vlm_service.py`：统一的 VLM / LLM 服务封装，业务节点一般通过它调用模型。
- `src/graph/llm/openrouter.py`：按 `biz_name` 解析模型、base_url、api_key、model_type。
- `src/graph/llm/OpenRouterImageModel.py`：OpenRouter 图像模型封装。
- `src/graph/llm/QunarImageModel.py`：去哪儿内部图像模型封装。
- `src/graph/llm/embedding_model.py`：M3E embedding 模型封装。

### 2.4 多媒体处理

- `ffmpeg-python`：视频转音频。
- `PySceneDetect`：视频场景切分。
- `opencv-python-headless`：视频帧读取、清晰度计算。
- `Pillow`：拼图处理。
- `scikit-learn`：依赖中存在，README 中提到可用于关键帧聚类，不过当前关键帧服务主要是场景检测 + 清晰度筛选。

关键路径：

- `src/service/key_frame_service.py`：场景检测、关键帧提取、清晰度评分。
- `src/service/main_service.py`：音频提取、音频上传等通用视频处理能力。
- `src/utils/collage_util.py`：拼图图片下载、LLM 生成拼图方案、执行拼图函数。
- `src/service/collage_tem_service.py`：拼图模板接口。

### 2.5 外部服务和数据层

- `MySQL` / `aiomysql`：用户、聊天消息、视频工作流记录。
- `PostgreSQL / pgvector`：从代码注释看，热词向量检索使用 pgvector。
- `OBS`：对象存储，上传视频、音频、关键帧、拼图、增强图。
- `火山引擎 ASR`：语音识别。
- `Everypixel`：图片质量评分接口。代码中保留了封装，但当前主工作流没有启用这一步。
- `Tikhub`：小红书热榜数据。
- 内部 POI 服务：景点匹配和景点详情。
- 内部图生图 / OpenRouter 图像增强服务。

关键路径：

- `src/database/connection.py`：MySQL 异步连接池。
- `src/database/models.py`：工作流、扩展字段等模型。
- `src/database/*dao.py`：DAO 层。
- `src/database/*service.py`：数据库 service 层。
- `src/service/obs_service.py`：OBS 上传、下载、URL 处理。
- `src/service/asr_service.py`：火山 ASR 提交任务和轮询结果。
- `src/service/image_score.py`：图片质量评分封装，当前主链路未使用。
- `src/service/xhs_hot_keyword_service.py`：小红书热词向量检索。
- `src/service/xhs_hot_leaderboard.py`：小红书热榜接口。

## 3. 顶层目录结构

```text
wangwei/
  README.md
  requirements.txt
  conf/
  data/
  deploy_scripts/
  logs/
  source/
  src/
```

### 3.1 `README.md`

`README.md` 已经比较完整地描述了“视频转小红书笔记”的主流程。里面的 Mermaid 图可以视为业务流程图。当前源码实现基本围绕这条流程展开。

### 3.2 `requirements.txt`

依赖能反映项目特点：

- Web：`fastapi`、`uvicorn`、`starlette`
- AI 编排：`langgraph`、`langchain`、`langchain-openai`、`langchain-mcp-adapters`
- 模型观测：`langfuse`、`langsmith`、`opentelemetry`
- 多媒体：`opencv-python-headless`、`ffmpeg-python`、`scenedetect`、`pillow`
- 数据库：`aiomysql`、`pymysql`、`SQLAlchemy`、`psycopg2-binary`
- 工具：`json_repair`、`aiohttp`、`requests`

### 3.3 `src/`

这是核心源码目录。可以按职责分成：

- `src/main.py`：主 API 入口。
- `src/api/`：部分业务路由拆分。
- `src/graph/`：AI 工作流、节点、状态、事件、模型。
- `src/service/`：外部服务和业务服务封装。
- `src/database/`：数据库模型、DAO、service、连接池。
- `src/prompts/`：prompt 模板。
- `src/utils/`：拼图、文件、状态序列化等工具。
- `src/config/`：本地动态配置，如热词和热榜 mock / 默认数据。

## 4. API 层设计

主入口是：

```text
src/main.py
```

这个文件承担的职责比较多：

1. 创建 FastAPI 应用。
2. 注册认证、用户、工作流、聊天消息路由。
3. 暴露核心 SSE 接口。
4. 暴露文件上传、拼图、热词、热榜、图像增强、封面增强、小红书发布等业务接口。

重要接口：

- `POST /chat/stream`  
  主工作流入口。它接收用户消息、视频路径、会话 ID、旧 state 等信息，构造 `State`，然后把执行交给 `event_manager.event_generator(state)`。

- `POST /chat/test`  
  测试版 SSE 工作流入口。

- `POST /upload/file`  
  上传文件到本地和 OBS。

- `GET /chat/basicData`  
  返回小红书风格映射数据。

- `GET /collage/templates`  
  返回拼图模板元数据。

- `POST /chat/collage`  
  对指定 URL 列表执行拼图。

- `POST /chat/updateXhsContentStream`  
  流式更新小红书标题或正文。

- `POST /chat/publishXhsNote`  
  通过 MCP 工具发布小红书笔记。

- `POST /xhs/hot_keywords/search_by_embedding`  
  用 embedding 检索小红书热词。

- `POST /xhsPostScore`  
  对小红书帖子做评分。

- `POST /imageEnhancement`、`POST /xhsCoverImageEnhancement`  
  图片增强和封面增强。

补充路由：

- `src/api/auth.py`：注册、登录、改密码。
- `src/api/user.py`：用户信息查询、更新、搜索。
- `src/api/chat_message.py`：会话消息查询。
- `src/api/video_workflow.py`：工作流记录查询和笔记更新。

## 5. SSE 事件机制

关键路径：

```text
src/graph/event/manager.py
```

核心类是 `EventQueueManager`。它的设计是：

1. 每个 `session_id` 对应一个 `asyncio.Queue`。
2. `/chat/stream` 建立 SSE 连接后，创建队列。
3. 后台启动 LangGraph 工作流。
4. 工作流节点执行时调用 `event_manager.send_event(...)` 写入队列。
5. `event_generator` 从队列读事件，转换成 SSE 格式推给前端。
6. 工作流结束后发送 `done` 事件并清理队列。

这个设计的好处：

- 节点内部可以随时推送进度，不需要等整个任务结束。
- 前端可以显示细粒度状态，比如“正在识别语音”“已选择第 N 张图片”“正在优化封面”。
- 工作流和网络输出解耦，节点只关心发事件，SSE 生成器只关心读队列。

需要注意的点：

- 队列保存在进程内存中，服务重启后会丢失。
- 多进程部署时，同一个 `session_id` 的队列必须落在同一个进程，否则事件可能找不到。
- `send_event` 同时会尝试把 AI 消息写入数据库，所以事件推送和消息持久化有一定耦合。

## 6. LangGraph 工作流设计

关键路径：

```text
src/graph/graph_builder.py
src/graph/state/types.py
src/graph/node/node.py
```

### 6.1 State 设计

`src/graph/state/types.py` 里的 `State` 继承自 `MessagesState`，它是整个工作流的共享上下文。

State 中包含：

- 会话信息：`session_id`、`workflow_id`、`message_id`
- 视频信息：`video_url`、`video_path`、`video_full_transcript`
- 节点结果：
  - `key_frame_detect_node_result`
  - `asr_node_result`
  - `text_and_image_combine_node_result`
  - `vlm_choose_result`
  - `poi_extract_node_result`
  - `xhs_hot_content_node_result`
  - `generate_node_result`
  - `image_processing_result`
  - `collage_node_result`
  - `xhs_final_text_node_result`
  - `xhs_post_scoring_node_result`
- 参考风格：`xhs_note_from_content`、`xhs_note_from_style`
- 成本记录：
  - `token_usage_records`
  - `img2img_usage_records`
- 调试控制：`debug`、`jump_node`

这个 State 设计体现了典型 LangGraph 思路：每个节点只读自己需要的字段，把结果写回 State，然后通过 `goto` 控制下一步。

### 6.2 节点注册

`src/graph/graph_builder.py` 中注册了所有节点：

- `status_router`
- `key_frame_detect_node`
- `asr_node`
- `text_and_image_combine_node`
- `xhs_style_node`
- `vlm_choose`
- `poi_extract_node`
- `xhs_hot_content_node`
- `image_processing_node`
- `generate`
- `collage_node`
- `xhs_final_text_node`
- `xhs_cover_opt_node`
- `xhs_note_scoring_node`
- `xhs_note_publish_node`

虽然 `graph_builder.py` 只显式设置了入口节点，没有写固定边，但节点内部通过 `Command(goto=...)` 动态决定下一跳。这说明项目使用的是“节点内路由”的风格。

### 6.3 主流程

核心流程可以理解为：

```text
POST /chat/stream
  -> EventQueueManager.event_generator
  -> run_workflow
  -> LangGraph status_router
  -> 并行：key_frame_detect_node + asr_node
  -> text_and_image_combine_node
  -> xhs_style_node
  -> 前端选择 / jump_node 继续
  -> vlm_choose
  -> 并行：poi_extract_node + xhs_hot_content_node + image_processing_node
  -> generate_node
  -> collage_node
  -> xhs_final_text_node
  -> xhs_cover_opt_node
  -> xhs_note_scoring_node
  -> done
```

这里有一个很重要的交互设计：

`xhs_style_node` 执行完后会把 `jump_node` 设置成 `vlm_choose`，并把当前 state 序列化后通过 SSE 返回给前端。这意味着风格分析后可能需要前端让用户选择风格，再把 state 带回来继续执行后续节点。

## 7. 核心 AI 节点拆分

### 7.1 路由节点：`status_router_node`

路径：

```text
src/graph/node/node.py
```

职责：

- 如果 state 里有 `jump_node`，直接跳到指定节点。
- 如果状态是 `init`，走简单 LLM 节点。
- 默认并行启动：
  - `key_frame_detect_node`
  - `asr_node`

这个节点是整个工作流的入口路由器。

### 7.2 关键帧检测：`key_frame_detect_node`

路径：

```text
src/graph/node/node.py
src/service/key_frame_service.py
```

职责：

- 根据 `video_path` 创建输出目录。
- 使用 `key_frame_service.find_best_keyframe_in_scenes_k` 提取关键帧。
- 上传关键帧到 OBS。
- 把本地路径和 OSS URL 的映射写入 State。
- 通过 SSE 推送开始、进度和结束事件。

底层关键帧逻辑在 `src/service/key_frame_service.py`：

- PySceneDetect 做场景切分。
- OpenCV 读取视频帧。
- 使用拉普拉斯方差计算清晰度。
- 根据场景时长动态调整采样率。
- 只保留清晰度达标的帧。

更细地说，“提取视频关键帧”可以简化成下面几步：

1. 先把视频按“场景”切开  
   比如一个旅行视频里，前 5 秒是火车站，后面是街道，再后面是景点、美食、夜景。代码会用 PySceneDetect 检测画面变化，把视频拆成多个场景片段。

   对应文件：

   ```text
   src/service/key_frame_service.py
   ```

2. 每个场景里抽样一些帧  
   一个场景可能有几百帧，不会每一帧都看。代码会按一定采样率抽帧。如果场景很短，就采样密一点；如果场景很长，就采样稀一点。

3. 给抽出来的帧算清晰度  
   代码用 OpenCV 读取视频帧，然后用“拉普拉斯方差”计算画面清晰度。简单理解：画面边缘越清楚、细节越明显，分数越高；模糊、虚焦、运动拖影的分数就低。

4. 每个场景选最清晰的一帧  
   对同一个场景里的候选帧，选清晰度最高的那一张作为这个场景的代表图。

5. 过滤太糊的图  
   如果某个场景里最清晰的帧仍然低于阈值，就不要这张，避免后面拿模糊图做笔记素材。

6. 保存图片并上传到 OBS  
   选出来的关键帧会保存成本地 jpg，同时上传到对象存储，后续节点主要使用图片 URL。

关键参数如下：

```text
SCENE_DETECTION_CONFIG = {
    initial_threshold: 27.0,
    min_threshold: 10.0,
    threshold_step: 5.0,
    target_scene_count: 20,
    min_scene_length: 15
}
```

这些参数的含义：

| 参数 | 含义 |
|---|---|
| `initial_threshold = 27.0` | 初始场景切换阈值。阈值越高，只有画面变化很明显才会切场景。 |
| `min_threshold = 10.0` | 最低阈值。场景数太少时会逐步降低阈值，但最低降到 10。 |
| `threshold_step = 5.0` | 每次降低阈值的步长，例如 27 -> 22 -> 17 -> 12。 |
| `target_scene_count = 20` | 目标场景数。不是强制输出 20 张图，而是希望至少检测到约 20 个场景。 |
| `min_scene_length = 15` | 最短场景长度，单位是帧。太短的片段会被忽略，避免抖动或闪屏造成误切。 |

采样和清晰度参数如下：

```text
SAMPLING_CONFIG = {
    base_sampling_rate: 10,
    short_scene_threshold: 3.0,
    long_scene_threshold: 10.0,
    short_scene_rate: 5,
    long_scene_rate: 7,
    sharpness_threshold: 80.0
}
```

这些参数的含义：

| 参数 | 含义 |
|---|---|
| `base_sampling_rate = 10` | 普通场景每 10 帧取一帧。 |
| `short_scene_threshold = 3.0` | 小于 3 秒的场景认为是短场景。 |
| `long_scene_threshold = 10.0` | 大于 10 秒的场景认为是长场景。 |
| `short_scene_rate = 5` | 短场景每 5 帧取一帧，采样更密，避免漏掉关键画面。 |
| `long_scene_rate = 7` | 长场景每 7 帧取一帧。 |
| `sharpness_threshold = 80.0` | 清晰度阈值。每个场景最清晰的一帧如果低于 80，就丢弃。 |

所以这个节点最终做的是：

```text
视频
  -> PySceneDetect 切场景
  -> 每个场景按 5 / 7 / 10 帧间隔抽候选帧
  -> OpenCV 读取候选帧
  -> 对每帧计算拉普拉斯方差
  -> 每个场景选最高分帧
  -> 低于 80 的帧丢弃
  -> 保存图片并上传 OBS
```

### 7.3 ASR 节点：`asr_node`

路径：

```text
src/graph/node/node.py
src/service/asr_service.py
src/service/main_service.py
```

职责：

- 从视频中提取音频。
- 上传音频到 OBS。
- 调用火山引擎 ASR。
- 轮询识别结果。
- 把分段字幕和完整字幕写入 State。

这里的 ASR 指的是 Automatic Speech Recognition，也就是自动语音识别。项目用的是火山引擎的 ASR 服务，模型名是 `bigmodel`，可以理解为“火山引擎大模型 ASR 做语音转文字”。

对应接口在 `src/service/asr_service.py`：

```text
提交任务：
https://openspeech-direct.zijieapi.com/api/v3/auc/bigmodel/submit

查询结果：
https://openspeech-direct.zijieapi.com/api/v3/auc/bigmodel/query
```

请求参数里使用：

```text
model_name: bigmodel
```

这一步的基本流程是：

1. 从本地视频里抽出音频  
   视频文件同时包含画面和声音，代码用 ffmpeg 把声音轨道单独提取出来，生成音频文件。

2. 把音频上传到 OBS  
   火山 ASR 服务运行在远端，不能直接访问本机路径，所以需要先把本地音频上传到对象存储。

3. 得到 `audio_url`  
   音频上传后会得到一个远端可访问的 URL，后续提交给火山 ASR 的就是这个 URL。

4. 提交 `audio_url` 给火山 ASR  
   当前项目使用的是 URL 模式，请求体里传的是：

   ```text
   audio: {
       url: audio_url
   }
   ```

5. 轮询 query 接口拿识别结果  
   ASR 不是立即返回完整字幕，而是先提交任务，再反复调用 query 接口查询任务状态。任务完成后，接口返回识别结果。

6. 转换成项目内部字幕格式  
   火山返回的是较复杂的 JSON，项目会转换成更简单的字幕数组，并写入 `asr_node_result` 和 `video_full_transcript`。

整体链路可以概括为：

```text
本地视频
  -> ffmpeg 抽出音频
  -> 上传音频到 OBS
  -> 得到 audio_url
  -> 提交 audio_url 给火山 ASR bigmodel
  -> 轮询 query 接口拿识别结果
  -> 转成后续节点可用的字幕数据
```

ASR 输出不只是文本，还会保留：

- `start_time`
- `end_time`
- `text`
- `emotion`
- `emotion_degree`
- `emotion_score`
- `speaker`

这为后面的图文对齐和内容理解提供了时间轴基础。

### 7.4 图文合并：`text_and_image_combine_node`

路径：

```text
src/graph/node/node.py
src/utils/file_handle_util.py
```

职责：

- 读取关键帧列表。
- 读取 ASR 字幕块。
- 从关键帧文件名解析时间戳。
- 找到时间戳落在哪段 ASR 文本中。
- 生成 `combined_narrative`。

输出结构大致包含：

- `frame_time`
- `frame_text`
- `image_url`
- `emotion`
- `text_start_time`
- `text_end_time`

这个节点是后续 VLM 选图的基础，因为它把“画面”和“字幕语义”绑定起来了。

### 7.5 小红书风格分析：`xhs_style_node`

路径：

```text
src/graph/node/node_by_xhs_style.py
src/prompts/xhs_style_analysis.md
```

职责：

- 读取完整视频字幕。
- 使用 prompt 分析原视频的语言风格、内容特点、情绪基调。
- 返回风格分析结果和可选风格列表。
- 把 state 序列化给前端，等待后续继续执行。

这是一个典型的“AI 中间决策节点”：它不直接产出最终内容，而是给后续文案生成提供风格依据。

### 7.6 VLM 选图：`vlm_choose_node`

路径：

```text
src/graph/node/node.py
src/prompts/vlm_choose.md
src/service/vlm_service.py
```

职责：

- 读取完整字幕和 `combined_narrative`。
- 把所有候选关键帧图片作为多模态输入发给 VLM。
- 让模型选择适合小红书笔记的关键图片。
- 返回每张图的：
  - index
  - description
  - reason
  - content_tags
  - keywords
  - search_keywords
  - processing_operations
- 给每张选中的图补充 `original_url` 和 `frame_time`。

设计亮点：

- 不是简单按清晰度选图，而是让 VLM 结合字幕、叙事逻辑和图片内容选图。
- 对 LLM JSON 输出做校验，如果 index 超出范围会过滤。
- 有 fallback 方案：模型失败时按时间线默认选择关键帧。

### 7.7 POI 景点提取：`poi_extract_node`

路径：

```text
src/graph/node/node_by_poi_extract.py
src/prompts/poi_extract.md
```

职责：

- 用 LLM 从字幕中提取城市、景点关键词。
- 调内部 POI Top-K 匹配接口。
- 对匹配分数足够高的 POI，再调详情接口。
- 输出结构化景点列表。

这个节点体现了“LLM + 传统业务服务”的组合：

- LLM 负责从自然语言里提取候选景点。
- 内部 POI 服务负责标准化和补全真实景点数据。
- 代码用分数阈值过滤低置信度匹配，避免把模型误识别直接放进最终内容。

### 7.8 小红书热词 / 热点匹配：`xhs_hot_content_node`

路径：

```text
src/graph/node/xhs_note_text_node.py
src/service/xhs_hot_keyword_service.py
src/service/xhs_hot_leaderboard.py
src/graph/llm/embedding_model.py
```

职责：

- 先用本地热词和热榜样例做流式预览。
- 对完整字幕生成 M3E embedding。
- 用向量检索匹配小红书热词。
- 调热榜接口获取实时热点。
- 输出 Top 热词和热点标题，给文案生成节点使用。

这里的 AI 设计不是 LLM 生成，而是 embedding 检索：

- `M3EEmbeddingModel` 调内部 embedding API。
- `XhsHotKeywordService.search_by_text` 先生成 query embedding，再调用 DAO 做相似检索。
- 从注释看底层是 pgvector cosine 检索。

### 7.9 图片处理：`image_processing_node`

路径：

```text
src/graph/node/node.py
src/service/img2img_service.py
src/service/image_enhancement_service.py
src/service/image_search_service.py
```

职责：

- 读取 VLM 选出的图片。
- 并发处理每张图片。
- 默认做图像质量增强。
- 如果 VLM 给出的 `processing_operations` 里包含 `image_search`，则用关键词搜索替换图片。
- 输出每张图的处理日志和最终 URL。

图片增强链路：

- `img2img_service.enhance_image_and_upload`
- 实际转给 `image_enhancement_service.enhance_image_and_upload`
- `image_enhancement_service` 使用 `create_llm_by_biz("image_enhancement")` 调图像模型。

这里有一个设计特点：VLM 不只选图，还给后续图片处理提供操作建议，比如是否搜索替换、用什么关键词。

### 7.10 文案生成：`generate_node`

路径：

```text
src/graph/node/node.py
src/prompts/xhs_caption_generate.md
```

职责：

- 等待 `poi_extract_node_result` 和 `xhs_hot_content_node_result` 都存在。
- 读取 VLM 选图结果。
- 读取 POI 景点信息。
- 读取小红书热词和热点。
- 读取用户选择的小红书风格或参考文案。
- 调 LLM 生成标题、正文、hashtags、完整文案。

输入来源比较丰富：

- 视频画面理解结果。
- 景点结构化信息。
- 小红书热点。
- 用户指定或系统推荐的风格参考。

所以这个节点是内容生成的核心节点。

### 7.11 拼图节点：`collage_node`

路径：

```text
src/graph/node/node.py
src/utils/collage_util.py
src/utils/collage_scheme.py
```

职责：

- 下载处理后的关键帧图片到本地。
- 收集 POI 图片。
- 调 LLM 为关键帧图片生成拼图方案。
- 调 LLM 为 POI 图片生成拼图方案。
- 根据方案调用本地拼图函数。
- 上传拼图结果到 OBS。
- 过滤失败结果，保留成功图片。

这里的 LLM 不是直接生成图片，而是生成“拼图函数调用方案”。真正图片合成由本地 PIL / 模板函数完成。这种设计比完全交给生图模型更可控。

### 7.12 最终汇总：`xhs_final_text_node`

路径：

```text
src/graph/node/node.py
```

职责：

- 读取 `generate_node_result` 的文案。
- 读取 `collage_node_result` 的拼图 URL。
- 组装最终小红书笔记对象：
  - `title`
  - `full_caption`
  - `hashtags`
  - `images`
  - `image_count`
  - `uploaded_count`
  - `image_tips`

这是从“工作流中间态”转成“前端可展示 / 可发布笔记”的节点。

### 7.13 封面优化：`xhs_cover_opt_node`

路径：

```text
src/graph/node/node_by_xhs_cover.py
src/prompts/xhs_cover_optimization.md
```

职责：

- 读取最终笔记。
- 取第一张图作为封面图。
- 根据标题、正文、hashtags 构造封面优化 prompt。
- 调图生图服务优化封面。
- 成功后替换 `images[0]`。
- 失败则保留原图并写入提示。

这个节点专门处理“小红书第一张图”的转化率问题，是内容平台场景里很关键的 AI 设计。

### 7.14 笔记评分：`xhs_note_scoring_node`

路径：

```text
src/graph/node/node.py
src/service/vlm_service.py
src/prompts/xhs_post_scoring.md
```

职责：

- 读取最终文案和图片。
- 调 VLM 对图文笔记做多维度评分。
- 推送模拟进度。
- 把评分结果写入 State。
- 创建或更新工作流记录。

这属于一个简单的 LLM-as-Judge / VLM-as-Judge 节点，用来评价生成结果质量。

### 7.15 小红书发布：`xhs_note_publish_node` 和 `/chat/publishXhsNote`

路径：

```text
src/graph/node/node.py
src/main.py
src/graph/tool/xhs_mcp.py
```

职责：

- 连接 `xiaohongshu-mcp` 服务。
- 获取 MCP tools。
- 使用 LangGraph prebuilt `create_react_agent` 创建 ReAct Agent。
- 让 Agent 调工具发布笔记。

这是一个工具调用型 Agent：LLM 不只是生成文本，还会通过 MCP 工具执行发布动作。

## 8. Prompt 管理

prompt 统一放在：

```text
src/prompts/
```

关键 prompt：

- `vlm_choose.md`：VLM 选图。
- `xhs_style_analysis.md`：视频文案风格分析。
- `poi_extract.md`：景点提取。
- `xhs_caption_generate.md`：小红书文案生成。
- `xhs_cover_optimization.md`：封面图优化。
- `xhs_post_scoring.md`：笔记评分。
- `image_enhancement.md`：图片增强。
- `key_frame_assembler.md`：关键帧拼图方案。
- `poi_assembler.md`：POI 图片拼图方案。
- `xhs_content_title_update.md`：标题 / 正文更新。

模板加载逻辑在：

```text
src/prompts/template.py
```

它支持两种方式：

- `get_prompt_template_local(prompt_name)`：直接读取本地 prompt。
- `get_prompt_template_formatted(prompt_name, **kwargs)`：读取本地 prompt 并替换 `<<VAR>>` 变量。

当前远程 prompt 配置逻辑被注释掉了，所以项目主要依赖本地 prompt 文件。

## 9. 模型配置设计

### 9.1 固定模型工厂

路径：

```text
src/graph/llm/config.py
```

这里定义了：

- `LLMStrategy`
- `OpenAIStrategy`
- `LLMFactory`

用途：

- 根据模型名创建 `ChatOpenAI`。
- 设置 base_url。
- 支持 streaming。
- 附加 Langfuse callback。

风险点：

- 文件中存在硬编码 API key 和 Langfuse key。正式项目应该改为环境变量或密钥管理服务。

### 9.2 按业务名选择模型

路径：

```text
src/graph/llm/openrouter.py
```

这是更核心的模型工厂。它根据 `biz_name` 读取环境变量：

```text
LLM_MODEL_CONFIG_MODEL_NAME_{BIZ}
LLM_MODEL_CONFIG_API_KEY_{BIZ}
LLM_MODEL_CONFIG_BASE_URL_{BIZ}
LLM_MODEL_CONFIG_TEMPERATURE_{BIZ}
LLM_MODEL_CONFIG_MAX_TOKENS_{BIZ}
LLM_MODEL_CONFIG_MODEL_TYPE_{BIZ}
```

支持的模型类型包括：

- `CHAT`：普通对话模型。
- `IMAGE`：OpenRouter 图像模型。
- `QUNAR_IMAGE`：去哪儿内部图像模型。
- `THINKING`：带 reasoning 风格参数的模型。

这说明项目希望不同节点使用不同模型，例如：

- 文案生成用文本模型。
- 选图 / 评分用多模态模型。
- 图像增强用图像模型。
- 某些复杂节点可以用 thinking 模型。

### 9.3 统一 VLMService

路径：

```text
src/service/vlm_service.py
```

`VLMService` 是业务节点最常用的模型入口：

- `call_llm_with_messages`：按业务名调用模型，返回文本和 token usage。
- `score_xhs_post`：封装图文评分。
- `analyze_keyframe`：分析单张关键帧。
- `analyze_keyframes_batch`：批量分析关键帧。

它还会读取模型返回的 usage metadata，写入 `TokenUsage`，供节点记录成本。

## 10. 数据库设计

数据库相关路径：

```text
src/database/
```

主要分层：

- `connection.py`：MySQL 连接池，基于 `aiomysql.create_pool`。
- `config.py`：数据库连接配置。
- `models.py`：Pydantic 数据模型。
- `*_dao.py`：直接执行 SQL。
- `*_service.py`：业务 service 层。

核心数据对象：

- 用户：`user_dao.py`、`user_service.py`
- 聊天消息：`chat_message_dao.py`、`chat_message_service.py`
- 视频工作流记录：`video_workflow_record_dao.py`、`video_workflow_record_service.py`
- 小红书热词：`xhs_hot_keyword_dao.py`

`VideoWorkflowRecord` 的 `ext` 字段比较重要，它存储 JSON 字符串，可以塞入完整 state、进度、元数据和最终 note。这个设计适合保存复杂工作流中间态，但也会带来问题：

- ext 可能很大。
- 查询 ext 内部字段不方便。
- 如果 State 结构变动，历史 ext 的兼容性需要额外处理。

## 11. 外部服务封装

### 11.1 OBS 存储

路径：

```text
src/service/obs_service.py
```

用途：

- 上传本地文件。
- 从 URL 上传。
- 下载对象。
- 给关键帧、音频、拼图、增强图提供统一存储。

### 11.2 ASR

路径：

```text
src/service/asr_service.py
```

用途：

- 提交火山 ASR 任务。
- 轮询任务结果。
- 转换返回结构。

### 11.3 图片质量评分

路径：

```text
src/service/image_score.py
```

说明：

- 代码中保留了 Everypixel `quality_ugc` 图片评分封装。
- `src/graph/node/node.py` 中也保留了 `key_frame_filter_node`，会调用 `image_score_service.score_image_from_file`。
- 但当前主流程没有实际走这个节点：`status_router_node` 默认并行进入 `key_frame_detect_node` 和 `asr_node`，而 `key_frame_detect_node` 完成后直接进入 `text_and_image_combine_node`。
- 所以当前关键帧质量主要由 `src/service/key_frame_service.py` 内部的场景检测、采样和拉普拉斯清晰度阈值控制，不是 Everypixel 评分控制。

### 11.4 图片搜索

路径：

```text
src/service/image_search_service.py
```

用途：

- 根据 VLM 生成的 `search_keywords` 搜索更合适图片。
- 根据评分选择最佳图片。

### 11.5 图像增强 / 图生图

路径：

```text
src/service/img2img_service.py
src/service/image_enhancement_service.py
```

用途：

- 历史上 `img2img_service` 直接对接内部图生图任务。
- 当前 `process_image` 和 `enhance_image_and_upload` 更多转向 `image_enhancement_service`。
- `image_enhancement_service` 通过 `create_llm_by_biz("image_enhancement")` 调图像增强模型。

### 11.6 热词和热榜

路径：

```text
src/service/xhs_hot_keyword_service.py
src/service/xhs_hot_leaderboard.py
src/config/local_dynamic_config.py
```

用途：

- 热词：embedding 检索。
- 热榜：实时接口。
- 本地配置：给流式过程提供预览数据，避免实时接口慢时前端无反馈。

## 12. 这个项目的 AI 设计特点

### 12.1 多节点 AI Pipeline，而不是单 Prompt

项目没有用一个大 prompt 直接“视频转笔记”，而是拆成多个节点：

- 字幕识别
- 关键帧提取
- 图文对齐
- 风格分析
- VLM 选图
- POI 提取
- 热词检索
- 文案生成
- 图片处理
- 拼图
- 封面优化
- 评分

这种设计更工程化。每个节点的输入输出相对明确，失败时也更容易定位。

### 12.2 LLM / VLM 与传统算法结合

传统算法负责稳定计算：

- PySceneDetect 做场景切分。
- OpenCV 做清晰度计算。
- ASR 服务做语音识别。
- POI 服务做标准化匹配。
- pgvector 做相似检索。
- PIL 做拼图。

LLM / VLM 负责语义判断：

- 哪些画面适合小红书。
- 视频文案是什么风格。
- 字幕中有哪些景点。
- 生成什么标题和正文。
- 封面图怎么优化。
- 最终笔记质量如何。

这个边界划分是合理的：让模型做语义判断，让代码做确定性计算。

### 12.3 State 驱动的工作流

所有节点通过 `State` 协作，而不是互相直接调用。这样便于：

- 并行执行。
- 前端中断后恢复。
- 节点跳转。
- 保存工作流记录。
- 记录 token 和图生图成本。

### 12.4 SSE 强化用户感知

AI 视频处理耗时长，如果只等最终结果，用户体验会差。项目用 SSE 把每个节点状态推出来：

- 开始关键帧检测。
- 正在识别语音。
- 正在分析风格。
- 已选择第几张图。
- 正在匹配热点。
- 正在优化封面。

这让长任务看起来可解释、可等待。

### 12.5 LLM 输出容错

项目多处使用：

```text
json_repair
```

并对返回字段做校验，比如：

- VLM 选图必须有 `selected_images` 和 `story_flow`。
- 图片 index 必须在有效范围。
- 文案生成必须有 `title`、`content`、`hashtags`、`full_caption`。

这说明开发者意识到了 LLM 输出不稳定的问题。

## 13. 工程上值得注意的问题

### 13.1 `src/main.py` 职责偏重

`src/main.py` 同时承担：

- 应用初始化。
- 主工作流接口。
- 文件上传。
- 拼图接口。
- 热词接口。
- 图像增强接口。
- 登录和用户信息接口。
- 小红书发布接口。

后续如果继续维护，建议把这些拆到 `src/api/` 下：

- `chat.py`
- `upload.py`
- `xhs.py`
- `image.py`
- `collage.py`
- `health.py`

### 13.2 密钥硬编码风险

多个文件中可以看到硬编码的 key、token、password 或内部服务地址，例如：

- `src/graph/llm/config.py`
- `src/service/asr_service.py`
- `src/service/img2img_service.py`

建议：

- 全部迁移到环境变量。
- 本地用 `.env`。
- 生产用密钥管理系统。
- 代码仓库中不要出现真实 key。

### 13.3 节点文件过大

`src/graph/node/node.py` 承载了大量节点逻辑，后续维护成本会升高。

建议按领域拆分：

- `video_nodes.py`
- `xhs_text_nodes.py`
- `image_nodes.py`
- `score_nodes.py`
- `publish_nodes.py`

### 13.4 异步代码中存在阻塞调用

部分 async 函数里有 `time.sleep(...)`，例如热词节点和图片处理节点附近。异步服务中使用 `time.sleep` 会阻塞事件循环，建议改成：

```text
await asyncio.sleep(...)
```

### 13.5 工作流恢复能力还比较粗

State 可以序列化给前端，也可以写入工作流记录，但当前看起来还不是完整的 checkpoint 机制。依赖前端带回 state 时，需要注意：

- State 体积可能变大。
- 旧版本 State 兼容问题。
- messages 中有不可序列化对象，所以项目已经做了 `serialize_state_for_event`。

### 13.6 进程内队列不适合多实例部署

`EventQueueManager` 的 queue 存在内存中。如果部署多个 worker，SSE 连接和工作流任务必须在同一个进程内。否则节点发事件可能找不到队列。

如果后续生产化，可以考虑：

- Redis Stream
- 消息队列
- WebSocket gateway
- sticky session

### 13.7 LLM 观测已有雏形

项目已经接入：

- Langfuse
- token usage 记录
- img2img usage 记录
- 工作流记录表

但目前 token 记录主要存在 State 内，是否持久化和如何分析还需要进一步确认。

## 14. 可以怎么向别人介绍这个后端

可以这样概括：

这是一个基于 FastAPI + LangGraph 的 AI 内容生成后端，核心目标是把旅行 / 探店视频自动转成小红书图文笔记。系统把视频处理拆成多个 AI 和非 AI 节点：先并行做关键帧提取和 ASR，再对齐图文时间线；之后用 VLM 选择适合发布的关键图片，用 LLM 分析文案风格、提取景点、生成标题正文；同时结合 embedding 检索小红书热词和实时热榜，提高内容的平台适配度。图片侧会做增强、搜索替换和拼图，最后生成完整笔记，并用 VLM 对图文质量打分。整个过程通过 SSE 实时推送节点进度，前端可以展示 AI 工作流的执行过程。

如果强调 AI 设计，可以说：

项目不是一个单 prompt 应用，而是多节点 AI pipeline。LLM / VLM 主要负责语义理解、选图、风格分析、内容生成和质量评估；传统算法和业务服务负责视频解析、ASR、POI 标准化、向量检索、图片拼接和对象存储。这样的拆分让系统比单次大模型调用更可控，也更容易做节点级优化、失败兜底和效果评估。

## 15. 关键文件速查

| 关注点 | 文件路径 |
|---|---|
| 主服务入口 | `src/main.py` |
| 简单上传 demo | `src/app/app.py` |
| LangGraph 构建 | `src/graph/graph_builder.py` |
| 全局 State | `src/graph/state/types.py` |
| SSE 事件队列 | `src/graph/event/manager.py` |
| 核心节点集合 | `src/graph/node/node.py` |
| 风格分析节点 | `src/graph/node/node_by_xhs_style.py` |
| POI 提取节点 | `src/graph/node/node_by_poi_extract.py` |
| 封面优化节点 | `src/graph/node/node_by_xhs_cover.py` |
| 热词热点节点 | `src/graph/node/xhs_note_text_node.py` |
| LLM 工厂 | `src/graph/llm/config.py` |
| 按业务名创建模型 | `src/graph/llm/openrouter.py` |
| VLM 服务封装 | `src/service/vlm_service.py` |
| Embedding 模型 | `src/graph/llm/embedding_model.py` |
| Prompt 模板加载 | `src/prompts/template.py` |
| Prompt 文件目录 | `src/prompts/` |
| 关键帧服务 | `src/service/key_frame_service.py` |
| ASR 服务 | `src/service/asr_service.py` |
| 图像增强服务 | `src/service/image_enhancement_service.py` |
| 图生图兼容服务 | `src/service/img2img_service.py` |
| 图片搜索 | `src/service/image_search_service.py` |
| OBS 服务 | `src/service/obs_service.py` |
| 拼图工具 | `src/utils/collage_util.py` |
| 数据库连接 | `src/database/connection.py` |
| 数据库模型 | `src/database/models.py` |
| 工作流记录 API | `src/api/video_workflow.py` |
| 聊天消息 API | `src/api/chat_message.py` |
