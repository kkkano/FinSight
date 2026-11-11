# 本地上下文分词资源

`cl100k_base.tiktoken` 来源于 https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken ，SHA-256 为 `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`。

通过项目既有 `tiktoken==0.12.0` 依赖在本地加载，许可见 `LICENSE.tiktoken`。此词表用于跨模型预算估算并预留 30% 余量，不声称与所有供应商分词器完全一致。实际费用/用量继续按供应商 usage 结算；请求路径不下载词表或写系统缓存。
