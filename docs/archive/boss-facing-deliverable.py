#!/usr/bin/env python3
"""Convert boss-facing-deliverable.md to styled HTML with embedded images."""

import base64
import os

DOCS_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(DOCS_DIR, "assets")


def embed_image(filename):
    path = os.path.join(ASSETS_DIR, filename)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{b64}"


arch_img = embed_image("boss-presentation-architecture.png")
workflow_img = embed_image("boss-presentation-workflow.png")
mobile_img = embed_image("boss-presentation-mobile-mockup.png")

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>投研信息流与判断过程数字化：可落地效果说明</title>
<style>
  @page {{
    size: A4;
    margin: 20mm 18mm;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB",
                 "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    font-size: 14px;
    line-height: 1.8;
    color: #1a1a2e;
    background: #fff;
    padding: 40px 56px;
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 26px;
    font-weight: 700;
    color: #0f3460;
    text-align: center;
    margin-bottom: 8px;
    padding-bottom: 16px;
    border-bottom: 3px solid #0f3460;
  }}
  .subtitle {{
    text-align: center;
    color: #666;
    font-size: 13px;
    margin-bottom: 36px;
  }}
  h2 {{
    font-size: 18px;
    font-weight: 700;
    color: #16213e;
    margin-top: 36px;
    margin-bottom: 14px;
    padding-left: 12px;
    border-left: 4px solid #e94560;
  }}
  h3 {{
    font-size: 15px;
    font-weight: 600;
    color: #333;
    margin-top: 24px;
    margin-bottom: 10px;
  }}
  p {{
    margin-bottom: 12px;
    text-align: justify;
  }}
  ol, ul {{
    margin: 8px 0 14px 24px;
  }}
  li {{
    margin-bottom: 4px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0 20px;
    font-size: 13px;
  }}
  th {{
    background: #0f3460;
    color: #fff;
    font-weight: 600;
    padding: 8px 12px;
    text-align: left;
  }}
  td {{
    padding: 7px 12px;
    border-bottom: 1px solid #e0e0e0;
  }}
  tr:nth-child(even) td {{
    background: #f8f9fc;
  }}
  .code-block {{
    background: #f4f4f8;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 14px 18px;
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    font-size: 13px;
    line-height: 1.6;
    margin: 12px 0 18px;
    white-space: pre-wrap;
    color: #333;
  }}
  .img-container {{
    text-align: center;
    margin: 20px 0;
  }}
  .img-container img {{
    max-width: 100%;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  }}
  .img-caption {{
    color: #888;
    font-size: 12px;
    margin-top: 6px;
  }}
  .highlight-box {{
    background: linear-gradient(135deg, #f8f9fc 0%, #eef1f8 100%);
    border-left: 4px solid #e94560;
    padding: 16px 20px;
    margin: 16px 0 20px;
    border-radius: 0 6px 6px 0;
  }}
  .card {{
    background: #fafbfe;
    border: 1px solid #e8eaf0;
    border-radius: 8px;
    padding: 18px 22px;
    margin: 14px 0;
  }}
  .card-title {{
    font-weight: 700;
    color: #0f3460;
    margin-bottom: 6px;
  }}
  .tag {{
    display: inline-block;
    background: #e94560;
    color: #fff;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    margin-right: 4px;
  }}
  .tag-blue {{
    background: #0f3460;
  }}
  .note {{
    color: #888;
    font-size: 12px;
    font-style: italic;
    margin-top: 30px;
    padding-top: 16px;
    border-top: 1px solid #e0e0e0;
  }}
  .page-break {{
    page-break-before: always;
  }}
  .section-number {{
    color: #e94560;
    font-weight: 700;
  }}
</style>
</head>
<body>

<h1>投研信息流与判断过程数字化</h1>
<p class="subtitle">可落地效果说明 &nbsp;|&nbsp; 机密文档</p>

<!-- 1 -->
<h2><span class="section-number">1.</span> 这件事解决什么问题</h2>

<p>老板每天会收到大量来自微信个人消息、微信群、冈底斯、Alpha 派等渠道的投研信息。这些信息本身有价值，但问题是：</p>

<ol>
  <li>信息太散，分布在不同渠道。</li>
  <li>噪声太多，混有活动通知、工具介绍、私人消息。</li>
  <li>推荐表达不统一，难以比较。</li>
  <li>推荐后有没有效果，缺少系统性验证。</li>
  <li>不知道哪些推荐人长期靠谱、擅长什么板块、适合什么周期。</li>
</ol>

<p>这个系统的目标不是一上来自动交易，也不是简单做股票推荐，而是把老板每天依赖的信息流和判断过程<strong>数字化、结构化、可复盘</strong>。</p>

<p>这里真正要沉淀的是两类资产：</p>

<ol>
  <li><strong>信息流资产</strong>：谁在什么时间、什么渠道、围绕什么标的或主题说了什么。</li>
  <li><strong>判断过程资产</strong>：老板如何过滤噪声、识别有效推荐、观察观点演变、判断哪些信号值得跟。</li>
</ol>

<div class="highlight-box">
  <strong>核心闭环：</strong><br>
  投研消息 → 信息归类 → 观点链沉淀 → 推荐人/主题评价 → 决策辅助与复盘
</div>

<!-- 2 -->
<h2><span class="section-number">2.</span> 最终交付效果</h2>

<p>老板最终看到的不是一堆聊天记录，而是三个日常入口：</p>

<ol>
  <li><strong>Channel 每日 AI 简报</strong>：主动推送今天值得关注的信息和判断摘要。</li>
  <li><strong>手机 H5 今日推荐池</strong>：看今天哪些标的/主题值得观察。</li>
  <li><strong>手机 H5 推荐人排行榜</strong>：看哪些推荐人的信息长期更有参考价值。</li>
</ol>

<p>周报/月报 PDF 作为复盘材料，不作为日常主入口。</p>

<!-- 3 -->
<h2 class="page-break"><span class="section-number">3.</span> 总体架构图</h2>

<div class="img-container">
  <img src="{arch_img}" alt="总体架构图">
  <div class="img-caption">图 1：系统总体架构</div>
</div>

<p>架构分四层：</p>

<table>
  <tr><th>层级</th><th>作用</th></tr>
  <tr><td>数据源</td><td>接入微信个人消息、微信群消息、冈底斯、Alpha 派等</td></tr>
  <tr><td>数据处理/模型层</td><td>做消息清洗、分类、观点链沉淀、推荐抽取、行情回测、推荐人画像</td></tr>
  <tr><td>服务层</td><td>提供 API 服务和定时任务</td></tr>
  <tr><td>老板端输出</td><td>Channel 简报、手机 H5、周报 PDF</td></tr>
</table>

<!-- 4 -->
<h2><span class="section-number">4.</span> 工作流程图</h2>

<div class="img-container">
  <img src="{workflow_img}" alt="工作流程图">
  <div class="img-caption">图 2：数据处理工作流程</div>
</div>

<p>核心流程：</p>

<ol>
  <li><strong>拉取消息</strong>：按时间窗口拉取微信等数据源。</li>
  <li><strong>清洗去噪</strong>：过滤私人消息、活动通知、无关闲聊。</li>
  <li><strong>消息分类</strong>：区分有效推荐、研究观点、会议活动、噪声。</li>
  <li><strong>观点链沉淀</strong>：识别同一推荐人、同一主题、同一标的的前后观点变化。</li>
  <li><strong>标的识别</strong>：识别股票、行业、板块、代码。</li>
  <li><strong>推荐标准化</strong>：提取推荐人、动作、周期、强度、理由。</li>
  <li><strong>行情匹配</strong>：匹配推荐后的真实行情。</li>
  <li><strong>胜率回测</strong>：计算 1日、3日、5日、10日、20日表现。</li>
  <li><strong>推荐人评分</strong>：形成推荐人胜率、收益、回撤和擅长方向。</li>
  <li><strong>AI 简报推送</strong>：把重点结论主动推送给老板。</li>
  <li><strong>H5 查看详情</strong>：老板手机查看推荐池和排行榜。</li>
  <li><strong>原文追溯</strong>：必要时回到原始聊天内容复核。</li>
</ol>

<!-- 5 -->
<h2 class="page-break"><span class="section-number">5.</span> 手机端效果图</h2>

<div class="img-container">
  <img src="{mobile_img}" alt="手机端效果图">
  <div class="img-caption">图 3：手机端产品效果示意</div>
</div>

<h3>5.1 今日推荐池</h3>

<p>老板打开后优先看到"今天值得关注的标的和主题"，不是原始消息列表。</p>

<p>每张卡片展示：</p>

<table>
  <tr><th>信息</th><th>说明</th></tr>
  <tr><td>股票/代码</td><td>被推荐的标的</td></tr>
  <tr><td>信号强度</td><td>高、中、观察</td></tr>
  <tr><td>推荐人</td><td>哪些人推荐</td></tr>
  <tr><td>共振来源</td><td>来自个人消息、群消息或其他来源</td></tr>
  <tr><td>推荐人历史</td><td>推荐人的 5日胜率、平均收益、最大回撤</td></tr>
  <tr><td>AI 摘要</td><td>把长文本压缩成一句话逻辑</td></tr>
  <tr><td>观点状态</td><td>首次提出、持续强化、补充证据、风险提示、观点反转</td></tr>
  <tr><td>操作</td><td>看原文、加入观察、忽略</td></tr>
</table>

<h3>5.2 推荐人排行榜</h3>

<p>老板可以快速判断"谁更靠谱"。</p>

<table>
  <tr><th>信息</th><th>说明</th></tr>
  <tr><td>样本数</td><td>有效推荐数量</td></tr>
  <tr><td>5日胜率</td><td>推荐后 5日命中比例</td></tr>
  <tr><td>平均收益</td><td>推荐后平均表现</td></tr>
  <tr><td>最大回撤</td><td>历史跟踪中的风险</td></tr>
  <tr><td>擅长板块</td><td>推荐效果较好的行业/题材</td></tr>
  <tr><td>最近推荐</td><td>最近推荐过哪些标的</td></tr>
</table>

<!-- 6 -->
<h2><span class="section-number">6.</span> 老板日常使用链路</h2>

<p>建议主链路：</p>

<div class="highlight-box">
  收到 Channel 推送 → 30 秒看 AI 简报 → 点开 H5 看重点标的/重点推荐人 → 必要时查看原文 → 加入观察或忽略
</div>

<p>Channel 简报示例：</p>

<div class="card">
  <div class="card-title">【今日推荐简报】</div>
  <p>
    重点观察：<span class="tag">3 只</span><br>
    高胜率推荐人动态：<span class="tag tag-blue">5 条</span><br>
    多人共振：<span class="tag">2 只</span><br>
    风险提示：<span class="tag tag-blue">1 条</span>
  </p>
  <p style="margin-top:10px; font-size:13px; color:#0f3460;">
    [今日推荐池] &nbsp; [推荐人排行榜] &nbsp; [查看原文]
  </p>
</div>

<!-- 7 -->
<h2 class="page-break"><span class="section-number">7.</span> 分阶段落地</h2>

<div class="card">
  <div class="card-title">V0：数据看清楚</div>
  <p><strong>目标：</strong>先验证数据源和消息质量。</p>
  <p><strong>交付：</strong></p>
  <ol>
    <li>微信 API 协议确认。</li>
    <li>消息探查脚本。</li>
    <li>半小时/一天样本分析。</li>
    <li>消息分类标准。</li>
  </ol>
</div>

<div class="card">
  <div class="card-title">V1：推荐结构化</div>
  <p><strong>目标：</strong>把聊天内容变成标准推荐表。</p>
  <p><strong>交付：</strong></p>
  <ol>
    <li>原始消息库。</li>
    <li>消息分类结果。</li>
    <li>标准化推荐表。</li>
    <li>股票、板块、推荐动作、推荐周期抽取。</li>
    <li>原文追溯。</li>
  </ol>
</div>

<div class="card">
  <div class="card-title">V2：回测和推荐人排名</div>
  <p><strong>目标：</strong>验证哪些信息源、推荐人和观点链更有效。</p>
  <p><strong>交付：</strong></p>
  <ol>
    <li>行情数据接入。</li>
    <li>推荐后多周期收益计算。</li>
    <li>推荐人胜率榜。</li>
    <li>推荐人画像。</li>
    <li>个股/板块共振统计。</li>
    <li>观点演变分析。</li>
  </ol>
</div>

<div class="card">
  <div class="card-title">V3：老板端应用</div>
  <p><strong>目标：</strong>形成老板每天能用的产品形态。</p>
  <p><strong>交付：</strong></p>
  <ol>
    <li>Channel 每日 AI 简报。</li>
    <li>手机 H5 今日推荐池。</li>
    <li>手机 H5 推荐人排行榜。</li>
    <li>原文追溯页面。</li>
    <li>周报/月报 PDF。</li>
  </ol>
</div>

<!-- 8 -->
<h2><span class="section-number">8.</span> 部署方式</h2>

<h3>V0 可以本地验证</h3>

<div class="code-block">脚本拉 API → 本地 JSON/SQLite → 生成 Markdown/HTML 简报</div>

<h3>V1 之后建议上云</h3>

<div class="code-block">云服务器 → 定时任务拉数据 → 数据库保存消息和推荐 → 模型计算推荐人表现 → Channel 推送 → 手机 H5 页面</div>

<p>需要云服务器的原因：</p>
<ol>
  <li>手机 H5 需要 URL 访问。</li>
  <li>Channel 简报需要定时推送。</li>
  <li>推荐池和排行榜需要实时读取数据。</li>
  <li>原文追溯和权限控制需要服务端支持。</li>
</ol>

<!-- 9 -->
<h2><span class="section-number">9.</span> 老板需要决策的点</h2>

<p>建议先让老板决策是否进入 V0/V1，而不是一次性承诺完整系统。</p>

<p>需要确认：</p>

<ol>
  <li>是否认可"先数字化信息流和判断过程，不直接自动交易"的边界。</li>
  <li>是否先以微信个人消息和微信群作为第一批数据源。</li>
  <li>冈底斯、Alpha 派的数据获取方式是什么。</li>
  <li>是否接受第一阶段用本地验证，模型有效后再上云。</li>
  <li>日常入口是否以 Channel 简报 + 手机 H5 为主。</li>
</ol>

<!-- 10 -->
<h2><span class="section-number">10.</span> 一句话介绍</h2>

<div class="highlight-box">
  这套系统不是简单做消息展示，也不是替老板炒股，而是把老板每天依赖的信息流和判断过程数字化、结构化、可复盘，帮助老板判断：今天哪些信息值得看，来自谁，前后观点怎么变化，历史上靠不靠谱，以及是否值得进一步跟踪。
</div>

<p class="note">
  注：以上图片为效果示意图，用于说明最终呈现方式；真实上线后会接入实际推荐数据、推荐人数据和行情回测结果。
</p>

</body>
</html>
"""

output_path = os.path.join(DOCS_DIR, "boss-facing-deliverable.html")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"HTML written to: {output_path}")
print(f"Size: {len(html):,} bytes")
