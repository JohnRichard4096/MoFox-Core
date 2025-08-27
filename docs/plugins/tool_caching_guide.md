# 自动化工具缓存系统使用指南

为了提升性能并减少不必要的重复计算或API调用，MMC内置了一套强大且易于使用的自动化工具缓存系统。该系统同时支持传统的**精确缓存**和先进的**语义缓存**。工具开发者无需编写任何手动缓存逻辑，只需在工具类中设置几个属性，即可轻松启用和配置缓存行为。

## 核心概念

- **精确缓存 (KV Cache)**: 当一个工具被调用时，系统会根据工具名称和所有参数生成一个唯一的键。只有当**下一次调用的工具名和所有参数与之前完全一致**时，才会命中缓存。
- **语义缓存 (Vector Cache)**: 它不要求参数完全一致，而是理解参数的**语义和意图**。例如，`"查询深圳今天的天气"` 和 `"今天深圳天气怎么样"` 这两个不同的查询，在语义上是高度相似的。如果启用了语义缓存，第二个查询就能成功命中由第一个查询产生的缓存结果。

## 如何为你的工具启用缓存

为你的工具（必须继承自 `BaseTool`）启用缓存非常简单，只需在你的工具类定义中添加以下一个或多个属性即可：

### 1. `enable_cache: bool`

这是启用缓存的总开关。

- **类型**: `bool`
- **默认值**: `False`
- **作用**: 设置为 `True` 即可为该工具启用缓存功能。如果为 `False`，后续的所有缓存配置都将无效。

**示例**:
```python
class MyAwesomeTool(BaseTool):
    # ... 其他定义 ...
    enable_cache: bool = True
```

### 2. `cache_ttl: int`

设置缓存的生存时间（Time-To-Live）。

- **类型**: `int`
- **单位**: 秒
- **默认值**: `3600` (1小时)
- **作用**: 定义缓存条目在被视为过期之前可以存活多长时间。

**示例**:
```python
class MyLongTermCacheTool(BaseTool):
    # ... 其他定义 ...
    enable_cache: bool = True
    cache_ttl: int = 86400  # 缓存24小时
```

### 3. `semantic_cache_query_key: Optional[str]`

启用语义缓存的关键。

- **类型**: `Optional[str]`
- **默认值**: `None`
- **作用**:
    - 将此属性的值设置为你工具的某个**参数的名称**（字符串）。
    - 自动化缓存系统在工作时，会提取该参数的值，将其转换为向量，并进行语义相似度搜索。
    - 如果该值为 `None`，则此工具**仅使用精确缓存**。

**示例**:
```python
class WebSurfingTool(BaseTool):
    name: str = "web_search"
    parameters = [
        ("query", ToolParamType.STRING, "要搜索的关键词或问题。", True, None),
        # ... 其他参数 ...
    ]
    
    # --- 缓存配置 ---
    enable_cache: bool = True
    cache_ttl: int = 7200  # 缓存2小时
    semantic_cache_query_key: str = "query" # <-- 关键！
```
在上面的例子中，`web_search` 工具的 `"query"` 参数值（例如，用户输入的搜索词）将被用于语义缓存搜索。

## 完整示例

假设我们有一个调用外部API来获取股票价格的工具。由于股价在短时间内相对稳定，且查询意图可能相似（如 "苹果股价" vs "AAPL股价"），因此非常适合使用缓存。

```python
# in your_plugin/tools/stock_checker.py

from src.plugin_system import BaseTool, ToolParamType

class StockCheckerTool(BaseTool):
    """
    一个用于查询股票价格的工具。
    """
    name: str = "get_stock_price"
    description: str = "获取指定公司或股票代码的最新价格。"
    available_for_llm: bool = True
    parameters = [
        ("symbol", ToolParamType.STRING, "公司名称或股票代码 (e.g., 'AAPL', '苹果')", True, None),
    ]

    # --- 缓存配置 ---
    # 1. 开启缓存
    enable_cache: bool = True
    # 2. 股价信息缓存10分钟
    cache_ttl: int = 600
    # 3. 使用 "symbol" 参数进行语义搜索
    semantic_cache_query_key: str = "symbol"
    # --------------------

    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        symbol = function_args.get("symbol")
        
        # ... 这里是你调用外部API获取股票价格的逻辑 ...
        # price = await some_stock_api.get_price(symbol)
        price = 123.45 # 示例价格
        
        return {
            "type": "stock_price_result",
            "content": f"{symbol} 的当前价格是 ${price}"
        }

```

通过以上简单的三行配置，`StockCheckerTool` 现在就拥有了强大的自动化缓存能力：

- 当用户查询 `"苹果"` 时，工具会执行并缓存结果。
- 在接下来的10分钟内，如果再次查询 `"苹果"`，将直接从精确缓存返回结果。
- 更智能的是，如果另一个用户查询 `"AAPL"`，语义缓存系统会识别出 `"AAPL"` 和 `"苹果"` 在语义上高度相关，大概率也会直接返回缓存的结果，而无需再次调用API。

---

现在，你可以专注于实现工具的核心逻辑，把缓存的复杂性交给MMC的自动化系统来处理。