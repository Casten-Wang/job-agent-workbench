"""Write this session's source-reviewed lessons once, after range validation."""

from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "outputs/understand-anything/itsdangerous-672971d66a2e/project"
OUTPUT = PROJECT / ".ua/intermediate/code-lessons.json"
PREFIX = "src/itsdangerous/"
FILES = {}


def lesson(path, order, overview, sections):
    FILES[path] = {"overview": overview,
                   "sections": [{"title": title, "lineRange": [start, end],
                                 "explanation": explanation, "tourOrder": order}
                                for title, start, end, explanation in sections]}


lesson("README.md", 1,
       "这份文档说明 ItsDangerous 如何在不可信环境之间传递带签名数据，并提供对象转令牌再还原的入门例子。先用它建立用途，再沿后续导览追踪具体实现。文档中的示例属于项目说明，本轮没有执行。", [
    ("用途与数据边界", 3, 12,
     "项目把签名用于检查传回的令牌是否被修改，同时说明序列化可定制、可加入压缩与时间戳。先把这些当作待源码核对的功能说明，尤其不要把签名解释成隐藏消息内容的加密。"),
    ("对象到令牌示例", 16, 29,
     "示例创建 URLSafeSerializer，调用 dumps 生成令牌，再用 loads 还原对象并读取字段。它给出了用户可见的往返接口，后续需要在 serializer、signer 和 url_safe 三个模块分别找到实现步骤。"),
    ("社区与贡献入口", 35, 50,
     "后两节提供捐助与贡献文档链接，描述项目的社区入口。它们不说明当前用户承担过任何实现，也不提供本轮功能或测试的执行记录。"),
])

lesson("pyproject.toml", 1,
       "这个配置文件声明包身份、Python 要求与构建后端，并列出开发工具和任务。它解释项目如何被打包以及维护者打算怎样运行检查。本轮只分析配置文本，不执行其中任务。", [
    ("包身份与版本要求", 1, 23,
     "project 段声明包名、开发版本、许可证、README 与 Python >=3.10 等元数据，随后列出项目链接。这里的版本属于固定提交中的声明，不应直接当成当前发布版本。"),
    ("依赖分组与构建后端", 25, 58,
     "dependency-groups 将文档、测试、类型检查等开发工具分组，build-system 指向 flit_core.buildapi。分组里有 pytest 只说明测试工具被声明，不能据此断定测试已经运行或通过。"),
    ("打包范围与检查配置", 60, 96,
     "Flit 配置标出 itsdangerous 模块与源码包附带文件，uv 和 pytest 段定义默认分组及测试入口。coverage 的 source 字符串包含 jinja2 与 tests，应按配置原文记录，不能未经执行核对就推导实际覆盖的模块。"),
    ("类型与风格约束", 98, 136,
     "mypy、pyright 和 ruff 段规定检查范围、目标 Python 版本及规则选择。阅读时区分这些静态检查配置与运行时业务逻辑，它们不会因为出现在文件中就自动执行。"),
    ("可执行开发任务", 138, 205,
     "tox 段定义测试、样式、类型检查、文档及依赖更新任务，部分任务还带有工作目录和依赖分组设置。它们有助于了解维护流程，但本次源码阅读没有触发任何 commands。"),
])

lesson(PREFIX + "__init__.py", 2,
       "这是包的公共导入入口，通过重新导出把多个内部模块集中在 itsdangerous 名下。它本身没有实现签名流程。导览从这里进入各类接口，避免把入口转发与真正业务实现混为一谈。", [
    ("编码与异常导出", 1, 9,
     "前三行导出字节与 Base64 工具，其后导出坏数据、签名和时间相关异常。as 同名写法保留了清晰的重新导出关系，调用者可以从包名直接访问这些类型。"),
    ("签名与序列化入口", 10, 17,
     "剩余导出覆盖基础 Serializer、算法与 Signer、带时间的实现，以及 URL-safe 组合类。要解释 dumps 或 max_age 的行为，应继续追到对应模块，而不是只根据这些公开名称判断实现。"),
])

lesson(PREFIX + "encoding.py", 2,
       "编码模块为后续签名与负载处理统一 str 和 bytes，并实现 URL-safe Base64 及紧凑整数表示。它处于多个模块共享的基础层。这里的格式转换与密码学签名各有作用，不能互相代替。", [
    ("文本与编码输出", 11, 25,
     "want_bytes 只在输入是 str 时按指定编码转换；base64_encode 随后采用 URL-safe 字母表并移除末尾等号填充。这样的输出便于放入令牌，但 Base64 仍是可还原的编码，不提供消息保密性。"),
    ("解码与错误边界", 28, 38,
     "base64_decode 把输入转为 ASCII bytes，按长度补回等号后解码。遇到 TypeError 或 ValueError 时将其包装为 BadData，让上层能够按库的错误类型处理格式异常。"),
    ("字母表与时间戳字节", 41, 54,
     "字母表常量供分隔符冲突检查使用，两个整数工具用大端无符号 64 位格式打包或还原数字。编码移除前导零、解码左补零的配对行为，是时间戳紧凑表示的基础。"),
])

lesson(PREFIX + "exc.py", 2,
       "这个模块把错误分为数据、签名、时间、头部和负载问题，并在部分异常上保留上下文。后续 fallback 和限时逻辑依赖这些继承关系。异常携带的 payload 仍可能没有通过验证。", [
    ("通用坏数据基类", 7, 19,
     "BadData 保存错误消息，并让字符串转换返回该消息。其他库异常从它派生，因此调用方可选择统一捕获或进一步区分错误类别。"),
    ("签名与时间上下文", 22, 57,
     "BadSignature 可附带待检查的 payload，BadTimeSignature 再增加 date_signed。保留这些字段是为了描述失败上下文，不能把字段存在当成签名有效的证明。"),
    ("过期与头部细分", 60, 89,
     "SignatureExpired 是 BadTimeSignature 的子类，BadHeader 则属于 BadSignature 分支并携带头部和原始错误。这个继承关系影响后续 except 的匹配顺序，限时加载必须先处理更具体的过期异常。"),
    ("负载解析错误", 92, 106,
     "BadPayload 直接继承 BadData，保存反序列化阶段的原始异常。它不属于 BadSignature 子类，所以只捕获签名错误的代码不会自动捕获所有负载解析失败。"),
])

lesson(PREFIX + "signer.py", 3,
       "这个模块定义签名算法策略和基础 Signer，把密钥派生、消息签名与验签组合起来。它是序列化器所依赖的签名层，支持按顺序保留多把密钥。阅读时同时观察默认 HMAC 路径与可替换算法，避免把配置边界忽略。", [
    ("算法接口与空签名", 15, 37,
     "SigningAlgorithm 要求子类生成签名，并通过 compare_digest 比较输入与期望签名。NoneAlgorithm 明确返回空签名，因此选择该算法时不能套用默认 HMAC 路径的完整性结论。"),
    ("摘要与密钥归一化", 40, 73,
     "_lazy_sha1 把 SHA-1 的访问推迟到实际调用，注释说明这是为了允许缺少该实现的环境先完成导入并另行配置。HMACAlgorithm 使用可配置摘要生成 MAC，_make_keys_list 则把单个或多个密钥保序转换成 bytes 列表。"),
    ("签名器配置入口", 76, 173,
     "类说明与构造器约定密钥从旧到新排列，设置 salt、分隔符、派生方式和摘要，并在未传算法时创建 HMACAlgorithm。构造器检查分隔符与 Base64 字母表的冲突；这些默认值与校验不会证明任意外部使用方式都正确。"),
    ("密钥选择与派生", 175, 213,
     "secret_key 和未指定密钥时的 derive_key 都取列表末尾，派生分支包括 concat、django-concat、hmac 和 none。这里的 none 是不派生密钥，与 NoneAlgorithm 不生成签名不同；注释也明确派生步骤不是把短密码变强的口令加固函数。"),
    ("生成带签名消息", 215, 225,
     "get_signature 先派生密钥、调用所选算法，再把签名做 Base64 编码；sign 返回原 value、分隔符与该签名。原文仍在返回值中，所以这条实现不是消息加密。"),
    ("按多把密钥验签", 227, 241,
     "verify_signature 先解码签名，格式失败便返回 False，再从最新密钥向旧密钥依次派生并验证。任何一把密钥验证成功就返回 True，全部失败才返回 False，这与签名只使用最新密钥的行为相配合。"),
    ("拆分消息与布尔入口", 244, 266,
     "unsign 从最右侧分隔符拆出消息和签名，验签成功才返回消息，否则抛 BadSignature 并附带 payload。validate 将 BadSignature 转换成 False，保留了异常式接口和布尔式接口两种调用方式。"),
])

lesson(PREFIX + "serializer.py", 4,
       "Serializer 把对象编解码与可配置签名器接成面向调用者的 dumps 和 loads。它还负责文本或 bytes 的适配、旧配置回退和 unsafe 调试读取。这个模块提供编排顺序，具体签名和 URL-safe 负载处理来自其他模块。", [
    ("序列化类型接口", 13, 37,
     "泛型变量与 Protocol 描述 loads、dumps 的最低接口，is_text_serializer 通过序列化空字典检查返回类型。类型检查分支中的默认泛型参数与运行时分支不同，不应把类型注解本身当成数据校验流程。"),
    ("默认策略与参数约定", 40, 107,
     "类说明列出 serializer、signer 和 fallback_signers 的职责，默认数据序列化器为 json、默认签名器为 Signer。fallback 允许按旧签名器或参数继续尝试兼容读取，但不会取消正常加载先验签的步骤。"),
    ("重载声明与实际初始化", 109, 241,
     "多个 overload 描述不同输入下的静态返回类型，真正初始化由后面的一个 __init__ 完成。它规范密钥和 salt，选择默认序列化器与签名器，并保存备用配置；阅读时不能把重载声明数当成多套运行时构造逻辑。"),
    ("负载编解码边界", 243, 276,
     "load_payload 根据文本或字节序列化器选择解码方式，并把反序列化异常包装成 BadPayload。dump_payload 则调用配置的 dumps 再归一为 bytes，这一层负责格式转换而非签名验证。"),
    ("构造与遍历签名器", 278, 307,
     "make_signer 把密钥集合、salt 和参数交给配置的签名器类，iter_unsigners 首先产出当前签名器。之后它根据备用项的字典、元组或类形式确定参数，再按密钥构造备用尝试，形成兼容读取的迭代顺序。"),
    ("对象与令牌往返", 309, 347,
     "dumps 先取得负载再签名，并按序列化器类型返回 str 或 bytes；loads 则逐个签名器验签后才调用 load_payload。文件版本 dump／load 只是把同样的流程接到文件句柄，正常解码的次序没有因此改变。"),
    ("unsafe 恢复与捕获范围", 349, 404,
     "unsafe 帮助函数先尝试正常 loads，捕获 BadSignature 后才从异常 payload 尝试恢复，并用 False 标记未通过该加载流程。它不是可信数据入口，且不能把文档中的 never fails 扩成任意配置不抛异常的保证：此处只捕获列出的异常，正常验签后出现的 BadPayload 不在第一层捕获范围内。"),
])

lesson(PREFIX + "_json.py", 4,
       "这个内部包装器保留 JSON loads／dumps 风格，调整默认输出格式以减少负载体积。URL-safe 混入类把它作为默认数据序列化器。它只处理 JSON 表示，不做消息签名或时效检查。", [
    ("JSON 解码转发", 7, 12,
     "_CompactJSON 的 loads 是静态方法，直接把文本或字节交给标准库 json.loads。包装器没有在这个分支增加签名检查，调用顺序仍由外层 Serializer 决定。"),
    ("紧凑输出默认值", 14, 18,
     "dumps 用 setdefault 设置 ensure_ascii=False 和紧凑 separators，再委托标准库输出 JSON。setdefault 允许调用方显式覆盖这些选项，不能把默认行为描述成不可配置的格式限制。"),
])

lesson(PREFIX + "timed.py", 5,
       "限时模块在基础签名与对象加载上加入时间戳和可选时效检查。时间戳属于参与签名的消息内容，max_age 则控制是否检查年龄。它还通过异常捕获顺序区分验证失败与已经过期。", [
    ("时间戳进入签名", 22, 51,
     "TimestampSigner 取整数时间并提供 UTC 时间转换，在 sign 中把编码后的时间戳先拼到 value，再对整个结果计算签名。时间信息因此位于被签名的数据内，而不是签名后额外附加的无保护字段。"),
    ("类型重载与基础验签", 56, 93,
     "两条 overload 根据 return_timestamp 描述返回类型，实际 unsign 实现先调用父类验签。签名错误被暂存，异常携带的 payload 只用于继续组织时间相关错误上下文，不会因此成为可信消息。"),
    ("拆分与验证时间表示", 95, 135,
     "实现从已拆出的内容中取时间戳，尝试 Base64 和整数转换，并根据原签名错误或时间表示错误抛出相应的 BadTimeSignature。即使能够解析日期，原签名不匹配仍会继续抛错，解析成功不等于验签成功。"),
    ("可选年龄检查", 137, 167,
     "只有 max_age 不为 None 时才计算 age，大于上限或小于零都抛 SignatureExpired；未传 max_age 就不进入这段年龄检查。validate 复用 unsign 并把签名异常转为 False，因此不能把未设置时效的调用解释成已经限制有效期。"),
    ("默认限时签名器", 170, 180,
     "TimedSerializer 将默认签名器改为 TimestampSigner，并在类型层面收窄 iter_unsigners 的返回类型。它继续复用基础序列化器的配置与备用签名器机制，而非重写全部对象编解码。"),
    ("过期与备用尝试边界", 185, 228,
     "loads 把 max_age 交给各签名器，成功后才解码负载，并按参数决定是否附带时间返回。SignatureExpired 被先捕获并立即抛出，普通 BadSignature 才继续备用尝试；loads_unsafe 只是把 max_age 转交基础 unsafe 帮助函数，不把过期数据变成可信数据。"),
])

lesson(PREFIX + "url_safe.py", 6,
       "这个模块把 URL-safe 负载表示叠加到普通或限时序列化器上。它负责紧凑 JSON、压缩选择、Base64 与压缩标记，签名编排和时效检查仍由继承链中的其他层完成。最后一站可据此串起对象到令牌再还原的完整路径。", [
    ("混入类与默认 JSON", 15, 21,
     "URLSafeSerializerMixin 基于 Serializer[str] 并选择 _CompactJSON 作为默认数据序列化器。这个默认值影响负载表示，而不是替换签名算法或取消外层验签。"),
    ("还原编码与压缩", 23, 53,
     "load_payload 先识别并去掉压缩标记点，再做 Base64 解码，并仅在有标记时进行 zlib 解压。两种格式失败分别包装为 BadPayload，随后才通过 super 交给下一层反序列化。"),
    ("按收益选择压缩", 55, 69,
     "dump_payload 先取得父层 JSON bytes，尝试压缩，仅当压缩结果比原数据至少少两字节时采用，再做 Base64 编码。若采用压缩就添加前导点，条件中的一个字节开销与该标记相对应，不能说所有负载都会压缩。"),
    ("组合普通与限时版本", 72, 83,
     "URLSafeSerializer 组合 mixin 与普通 Serializer，URLSafeTimedSerializer 则组合 mixin 与 TimedSerializer。阅读 super 调用时要沿各自继承链区分负载格式、签名校验和时效检查，URL-safe 名称本身不代表负载被加密。"),
])


def main():
    expected = {"README.md", "pyproject.toml"} | {PREFIX + n for n in
               ("__init__.py", "_json.py", "encoding.py", "exc.py", "serializer.py", "signer.py", "timed.py", "url_safe.py")}
    if set(FILES) != expected:
        raise ValueError("Detailed file inventory differs from dispatch")
    section_count = 0
    for path, data in FILES.items():
        text = (PROJECT / path).read_bytes().decode("utf-8")
        line_count = len(text.split("\n")) - int(text.endswith("\n"))
        if not 2 <= len(data["sections"]) <= 10:
            raise ValueError("Section count outside role limits")
        previous_end = 0
        for section in data["sections"]:
            start, end = section["lineRange"]
            if not previous_end < start <= end <= line_count:
                raise ValueError(f"Invalid or overlapping range in {path}")
            previous_end = end
            section_count += 1
    document = {"version": 1, "generatedAt": datetime.now(timezone.utc).isoformat(), "files": FILES}
    if OUTPUT.exists():
        raise FileExistsError("Lesson scratch output already exists; do not overwrite another invocation")
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"detailed_files": len(FILES), "sections": section_count,
                      "line_ranges_valid": True, "sections_nonoverlapping": True}))


if __name__ == "__main__":
    main()
