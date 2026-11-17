"""Render this session's source-reviewed Chinese semantics over official UA structure.

This is a deterministic renderer of hand-authored LLM analysis, not a replacement
structural extractor or an unattended semantic-generation service.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "outputs/understand-anything/itsdangerous-672971d66a2e/project"
INTERMEDIATE = PROJECT / ".ua/intermediate"
PREFIX = "src/itsdangerous/"

FILE_SEMANTICS = {
    "README.md": ("介绍库用于在不可信环境之间传递带签名数据，并以 URLSafeSerializer 展示对象到令牌再还原对象的用法。还提供捐助和贡献入口；示例不是本轮执行结果。", ["文档", "入口点", "使用示例"], "simple"),
    "pyproject.toml": ("声明包元数据、Python 版本要求和 Flit 构建入口，并配置开发依赖分组、测试、类型检查、格式检查及文档任务。本轮只读取这些配置，没有执行其中命令或验证其效果。", ["配置", "构建系统", "开发工具"], "moderate"),
    PREFIX + "__init__.py": ("作为包的公共导入入口，重新导出编码工具、异常、签名器以及普通、限时和 URL-safe 序列化器。调用者可从 itsdangerous 导入这些接口，而不必直接依赖内部模块路径。", ["入口点", "barrel", "公共接口"], "simple"),
    PREFIX + "_json.py": ("用静态方法包装标准库 JSON 编解码，默认关闭非 ASCII 转义并移除多余分隔空白。URL-safe 序列化器把这个紧凑实现作为默认负载序列化器。", ["序列化", "JSON", "内部帮助"], "simple"),
    PREFIX + "encoding.py": ("统一文本与 bytes 转换，提供去掉填充的 URL-safe Base64 编码、补齐填充的解码，以及时间戳整数的字节转换。解码错误封装为库定义的 BadData，编码本身不承担消息签名或加密。", ["工具函数", "Base64", "字节编码"], "simple"),
    PREFIX + "exc.py": ("定义库的异常层次，区分普通坏数据、签名错误、时间签名错误、过期以及负载或头部错误。部分异常携带待检查负载、签名时间或原始错误，携带这些信息不表示数据已通过验证。", ["异常", "错误边界", "错误上下文"], "moderate"),
    PREFIX + "serializer.py": ("将对象序列化与可配置签名器组合成 dumps／loads 接口，并支持多密钥和备用签名器。正常 loads 先验签再反序列化，unsafe 路径则另外暴露有效性与可能未可信的负载，供受控调试使用。", ["序列化", "签名编排", "兼容回退"], "complex"),
    PREFIX + "signer.py": ("提供可配置签名算法、密钥派生和按分隔符组合的消息签名及验签，默认算法为 HMAC。签名使用最新密钥，验签可尝试历史密钥；返回数据保留原始消息，并非消息加密，NoneAlgorithm 还可显式关闭签名。", ["签名", "密钥轮换", "完整性校验"], "complex"),
    PREFIX + "timed.py": ("在基础签名器中加入参与签名的时间戳，并在传入 max_age 时检查年龄上限和未来时间。限时序列化器把该行为接到对象解码流程；已验证但过期时直接抛异常，不继续尝试备用签名器。", ["时间戳", "过期检查", "签名编排"], "complex"),
    PREFIX + "url_safe.py": ("通过 mixin 为负载增加 URL-safe Base64 和可选 zlib 压缩，再与普通或限时序列化器组合。只有压缩节省空间足以覆盖标记开销时才采用压缩，并用前导点标记；解码依次还原编码和可选压缩。", ["URL-safe", "负载压缩", "mixin"], "moderate"),
}

SYMBOL_SEMANTICS = {
    ("encoding.py", "want_bytes"): ("将 str 按指定编码转为 bytes，已有 bytes 原样返回，为签名和序列化路径统一输入类型。", ["工具函数", "文本转换", "bytes"], "simple"),
    ("encoding.py", "base64_encode"): ("把输入转换成 bytes 后做 URL-safe Base64 编码并移除尾部等号填充。该转换不提供加密保密性。", ["Base64", "URL-safe", "编码"], "simple"),
    ("encoding.py", "base64_decode"): ("将输入作为 ASCII bytes，补足四字节对齐所需填充后解码；捕获 TypeError 或 ValueError 并转换成 BadData。", ["Base64", "解码", "异常转换"], "simple"),
    ("encoding.py", "int_to_bytes"): ("按大端无符号 64 位整数打包，再移除前导零字节，为签名时间戳提供紧凑字节表示。", ["时间戳", "整数编码", "大端"], "simple"),
    ("encoding.py", "bytes_to_int"): ("给时间戳字节左侧补零到八字节，再按大端无符号整数解包。", ["时间戳", "整数解码", "大端"], "simple"),
    ("exc.py", "BadData"): ("作为库定义错误的基类，保存消息并通过字符串转换返回该消息。", ["异常", "基类", "错误消息"], "simple"),
    ("exc.py", "BadSignature"): ("表示签名校验失败，可保留待检查的 payload；该负载可能已被修改，不能因异常携带它而视为可信。", ["异常", "签名失败", "未可信负载"], "simple"),
    ("exc.py", "BadTimeSignature"): ("在签名错误基础上附带可选的签名时间，供时间格式或时效相关错误使用。", ["异常", "时间签名", "错误上下文"], "simple"),
    ("exc.py", "SignatureExpired"): ("标记时间签名的时效检查失败；TimestampSigner 也用它表示传入 max_age 后出现的未来时间。", ["异常", "过期", "时间边界"], "simple"),
    ("exc.py", "BadHeader"): ("在签名错误中保存可选头部与原始错误信息，为带签名头部的序列化场景提供错误上下文。", ["异常", "头部", "错误上下文"], "simple"),
    ("exc.py", "BadPayload"): ("表示负载格式或反序列化错误，保存导致失败的原始异常以便诊断。", ["异常", "负载解析", "错误上下文"], "simple"),
    ("serializer.py", "_PDataSerializer"): ("以泛型 Protocol 描述 loads 与 dumps 的最低接口，用于表达文本或字节序列化器的静态类型约束。", ["Protocol", "泛型", "序列化接口"], "simple"),
    ("serializer.py", "is_text_serializer"): ("通过序列化空字典并检查返回值是否为 str，判断序列化器输出文本还是 bytes。", ["类型判断", "序列化", "文本输出"], "simple"),
    ("serializer.py", "Serializer"): ("负责对象与签名令牌之间的编排：dump_payload 处理序列化，make_signer 创建可配置签名器，loads 验签后还原对象。还支持备用签名器及保留签名有效性标记的 unsafe 调试路径。", ["序列化", "签名编排", "兼容回退"], "complex"),
    ("signer.py", "SigningAlgorithm"): ("定义签名生成接口，并用 hmac.compare_digest 比较输入签名与按相同参数重新生成的签名。具体签名生成由子类实现。", ["算法接口", "签名校验", "可替换策略"], "simple"),
    ("signer.py", "NoneAlgorithm"): ("作为显式不签名的算法实现，始终生成空签名；使用它时不能推导出默认 HMAC 路径的防篡改性质。", ["算法策略", "不签名", "配置边界"], "simple"),
    ("signer.py", "_lazy_sha1"): ("延迟到调用时才访问 hashlib.sha1，避免仅导入模块时就因缺少 SHA-1 实现而失败；不构成对特定合规环境的验证。", ["延迟求值", "摘要函数", "兼容性"], "simple"),
    ("signer.py", "HMACAlgorithm"): ("按可配置摘要函数使用 hmac.new 生成消息认证码，默认摘要通过延迟包装的 SHA-1 提供。", ["HMAC", "签名算法", "可配置摘要"], "simple"),
    ("signer.py", "_make_keys_list"): ("将单个密钥或密钥迭代集合统一转换为 bytes 列表，保留调用方提供的顺序。", ["密钥列表", "输入归一化", "bytes"], "simple"),
    ("signer.py", "Signer"): ("对原始 bytes 与签名进行组合和分解，提供可配置密钥派生与算法。签名使用列表末尾的最新密钥，验签反向尝试密钥；不隐藏原文，且是否实际签名受算法配置影响。", ["签名", "密钥轮换", "完整性校验"], "complex"),
    ("timed.py", "TimestampSigner"): ("把编码后的时间戳拼入消息再签名，验签后提取时间戳。仅在给定 max_age 时检查年龄，超出上限或小于零均抛 SignatureExpired，并可返回带时区的签名时间。", ["时间签名", "过期检查", "时间边界"], "complex"),
    ("timed.py", "TimedSerializer"): ("默认使用 TimestampSigner，将 max_age 与可选时间戳返回值接入对象加载。过期异常直接传播，普通签名错误才继续备用签名器迭代。", ["限时令牌", "序列化", "兼容回退"], "moderate"),
    ("_json.py", "_CompactJSON"): ("提供与 JSON loads／dumps 兼容的静态方法，默认省去额外空白并保留非 ASCII 字符，使 URL-safe 负载更紧凑。", ["JSON", "紧凑表示", "静态方法"], "simple"),
    ("url_safe.py", "URLSafeSerializerMixin"): ("重写负载编解码，组合紧凑 JSON、按收益选择的 zlib 压缩和 URL-safe Base64。前导点表示压缩负载，解码异常统一包装为 BadPayload；该层不负责签名验证。", ["mixin", "负载压缩", "Base64"], "moderate"),
    ("url_safe.py", "URLSafeSerializer"): ("通过多重继承将 URL-safe 负载编解码与基础 Serializer 的签名编排组合起来，不额外加入时效检查。", ["URL-safe", "多重继承", "序列化"], "simple"),
    ("url_safe.py", "URLSafeTimedSerializer"): ("通过多重继承组合 URL-safe 负载编解码与 TimedSerializer，允许在加载时使用 max_age 检查时效。", ["URL-safe", "限时令牌", "多重继承"], "simple"),
}


def symbol_id(filename, name):
    kind = "function" if name in {"want_bytes", "base64_encode", "base64_decode", "int_to_bytes", "bytes_to_int", "is_text_serializer", "_lazy_sha1", "_make_keys_list"} else "class"
    return f"{kind}:{PREFIX}{filename}:{name}"


INHERITANCE = [
    ("exc.py", "BadSignature", "exc.py", "BadData"),
    ("exc.py", "BadTimeSignature", "exc.py", "BadSignature"),
    ("exc.py", "SignatureExpired", "exc.py", "BadTimeSignature"),
    ("exc.py", "BadHeader", "exc.py", "BadSignature"),
    ("exc.py", "BadPayload", "exc.py", "BadData"),
    ("signer.py", "NoneAlgorithm", "signer.py", "SigningAlgorithm"),
    ("signer.py", "HMACAlgorithm", "signer.py", "SigningAlgorithm"),
    ("timed.py", "TimestampSigner", "signer.py", "Signer"),
    ("timed.py", "TimedSerializer", "serializer.py", "Serializer"),
    ("url_safe.py", "URLSafeSerializerMixin", "serializer.py", "Serializer"),
    ("url_safe.py", "URLSafeSerializer", "url_safe.py", "URLSafeSerializerMixin"),
    ("url_safe.py", "URLSafeSerializer", "serializer.py", "Serializer"),
    ("url_safe.py", "URLSafeTimedSerializer", "url_safe.py", "URLSafeSerializerMixin"),
    ("url_safe.py", "URLSafeTimedSerializer", "timed.py", "TimedSerializer"),
]


def render():
    batches = json.loads((INTERMEDIATE / "batches.json").read_text(encoding="utf-8"))["batches"]
    all_paths = {f["path"] for b in batches for f in b["files"]}
    all_ids = set()
    generated = []
    for batch in batches:
        index = batch["batchIndex"]
        extraction = json.loads((INTERMEDIATE / f"structure-batch-{index}.json").read_text(encoding="utf-8"))
        if not extraction["scriptCompleted"] or extraction["filesUnreadable"] or extraction["filesSkipped"]:
            raise ValueError("Official extraction was incomplete")
        nodes, edges = [], []

        def edge(source, target, kind, weight, description=None):
            row = {"source": source, "target": target, "type": kind, "direction": "forward", "weight": weight}
            if description:
                row["description"] = description
            edges.append(row)

        for item in extraction["results"]:
            path = item["path"]
            summary, tags, complexity = FILE_SEMANTICS[path]
            kind = {"docs": "document", "config": "config"}.get(item["fileCategory"], "file")
            file_id = f"{kind}:{path}"
            nodes.append({"id": file_id, "type": kind, "name": Path(path).name,
                          "filePath": path, "lineRange": [1, item["totalLines"]],
                          "summary": summary, "tags": tags, "complexity": complexity})
            exported = {s["name"] for s in item.get("exports", [])}
            for symbol_kind, field in (("function", "functions"), ("class", "classes")):
                for symbol in item.get(field, []):
                    name = symbol["name"]
                    summary, tags, complexity = SYMBOL_SEMANTICS[(Path(path).name, name)]
                    node_id = f"{symbol_kind}:{path}:{name}"
                    nodes.append({"id": node_id, "type": symbol_kind, "name": name,
                                  "filePath": path, "lineRange": [symbol["startLine"], symbol["endLine"]],
                                  "summary": summary, "tags": tags, "complexity": complexity})
                    edge(file_id, node_id, "contains", 1.0)
                    if name in exported:
                        edge(file_id, node_id, "exports", 0.8)
            for imported in batch["batchImportData"].get(path, []):
                edge(file_id, f"file:{imported}", "imports", 0.7)
        local_ids = {n["id"] for n in nodes}
        for source_file, source_name, target_file, target_name in INHERITANCE:
            source, target = symbol_id(source_file, source_name), symbol_id(target_file, target_name)
            if source in local_ids:
                edge(source, target, "inherits", 0.9)
        if index == 1:
            for source_name in ("base64_encode", "base64_decode"):
                edge(symbol_id("encoding.py", source_name), symbol_id("encoding.py", "want_bytes"), "calls", 0.8)
            edge(symbol_id("serializer.py", "Serializer"), symbol_id("signer.py", "Signer"), "depends_on", 0.6,
                 "Serializer 创建可配置签名器，默认类为 Signer；调用方可替换该默认实现。")
            edge(symbol_id("signer.py", "Signer"), symbol_id("signer.py", "HMACAlgorithm"), "depends_on", 0.6,
                 "未传 algorithm 时创建 HMACAlgorithm；NoneAlgorithm 等配置具有不同语义。")
        if index == 2:
            edge("document:README.md", symbol_id("url_safe.py", "URLSafeSerializer"), "documents", 0.5)
            edge("config:pyproject.toml", f"file:{PREFIX}__init__.py", "configures", 0.6,
                 "声明打包模块、Python 版本和开发任务；未执行这些任务。")
            edge(symbol_id("url_safe.py", "URLSafeSerializerMixin"), symbol_id("_json.py", "_CompactJSON"), "depends_on", 0.6,
                 "mixin 将紧凑 JSON 包装器作为默认数据序列化器。")
        if sum(e["type"] == "imports" for e in edges) != sum(len(p) for p in batch["batchImportData"].values()):
            raise ValueError("Import counts do not match official batch data")
        if len(local_ids) != len(nodes):
            raise ValueError("Duplicate node IDs")
        # Both batches are intentionally below the official split threshold.
        if len(nodes) > 60 or len(edges) > 120:
            raise ValueError("Batch requires multipart output")
        (INTERMEDIATE / f"batch-{index}.json").write_text(json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        all_ids.update(local_ids)
        generated.append((index, nodes, edges))
    for index, nodes, edges in generated:
        for e in edges:
            if e["source"] not in all_ids or e["target"] not in all_ids or e["source"] == e["target"]:
                raise ValueError(f"Batch {index} has an unresolved edge")
        for n in nodes:
            if n["filePath"] not in all_paths:
                raise ValueError("Unknown source path")
        print(json.dumps({"batch": index, "nodes": len(nodes), "edges": len(edges),
                          "imports": sum(e["type"] == "imports" for e in edges)}, ensure_ascii=False))


if __name__ == "__main__":
    render()
