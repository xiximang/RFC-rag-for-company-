"""轻量级查询改写：剥离疑问词/停用词，提取核心搜索词。

仅用于 keyword (BM25) 模式。semantic/hybrid 模式语义检索能理解疑问词，
剥离反而可能损失语义，故不改写。

权威实现，被 retrieval_service 与 eval 脚本共用，避免多份漂移。
"""
from __future__ import annotations

import re

# 完整模式优先匹配（越长越精确），均锚定句尾。
_PATTERNS: list[str] = [
    # "是什么问题" 类
    r"是什么问题$|是什么原因$|是怎么回事$|是什么$",
    # "有哪些" / "有哪几个" 类
    r"有哪些$|有哪几种$|有哪几个$|有哪些方法$|有哪些步骤$",
    # "怎么" / "如何" / "怎样" 类
    r"怎么处理$|怎么解决$|怎么操作$|怎么连接$|怎么设置$|怎么调整$|怎么更换$",
    r"如何操作$|如何解决$|如何处理$|如何设置$|如何连接$|如何更换$",
    r"怎样操作$|怎样解决$|怎样处理$",
    # "为什么" / "为何" 类
    r"为什么会出现$|为什么$|为何$",
    # 单个疑问词结尾
    r"[的]?(啥|吗|呢|呀|么)$",
]

_COMPILED = [re.compile(p) for p in _PATTERNS]
_TRAILING_PUNCT = re.compile(r"[，,、；]$")


def rewrite_query(query: str) -> str:
    """剥离句尾疑问词/停用词，返回核心搜索词。

    若改写后为空（整句都是疑问词），返回原 query，保证不会得到空串。
    """
    if not query:
        return query
    q = query.strip()
    for pat in _COMPILED:
        q = pat.sub("", q).strip()
    q = _TRAILING_PUNCT.sub("", q).strip()
    return q if q else query
