"""UI messages are independent of the document's language and direction."""

MESSAGES = {
    "en": {
        "success": "Created Word document: {path}",
        "failure": "Conversion failed [{code}]: {message}",
        "warning": "Warning [{code}]: {message}",
        "preview": "Preview status: {status}. {reason}",
        "doctor": "Environment diagnostics",
        "description": "Convert multilingual Markdown to Word with verified open fonts",
    },
    "zh": {
        "success": "已生成 Word 文档：{path}",
        "failure": "转换失败 [{code}]：{message}",
        "warning": "提示 [{code}]：{message}",
        "preview": "预览状态：{status}。{reason}",
        "doctor": "环境诊断",
        "description": "使用已核实的开放字体，将多语言 Markdown 转为 Word",
    },
}


def message(locale: str, key: str, **values: object) -> str:
    return MESSAGES.get(locale, MESSAGES["en"])[key].format(**values)


HELP_ZH = {
    "Input Markdown file path": "输入 Markdown 文件路径",
    "Output DOCX file path (default: input file with .docx extension)": "输出 DOCX 路径（默认与输入同名）",
    "Reference DOCX template file for styling": "可选的 DOCX 样式参考文件",
    "Create a modern DOCX template and exit": "创建 DOCX 模板后退出",
    "Include table of contents in output (use --no-toc to disable)": "生成目录（--no-toc 禁用）",
    "Table of contents depth (1-6, default from config)": "目录层级（1-6，默认使用配置）",
    "Validate output DOCX file after conversion (use --no-validate to skip)": "兼容参数；必要的结构和完整性检查始终执行",
    "Enable verbose logging output": "输出详细日志",
    "Suppress all output except errors": "仅输出错误",
    "Path to configuration file (YAML/TOML)": "配置文件路径（YAML/TOML）",
    "Document BCP 47 language; local lang spans may override it": "文档 BCP 47 语言，局部 lang 标记可以覆盖",
    "Document base direction (default: auto)": "文档基方向（默认自动判断）",
    "CLI language, independent of document language": "命令行界面语言，与文档语言独立",
    "Disable font downloads": "禁用字体下载",
    "Explicitly allow installed fonts without a verified license record": "显式允许使用授权未核实的已安装字体",
    "Emit only structured JSON on stdout": "stdout 仅输出结构化 JSON",
    "Inspect dependencies without converting a document": "检查依赖，不执行转换",
    "Render an optional PDF/page preview with LibreOffice": "可选：使用 LibreOffice 渲染 PDF 和页面预览",
    "Directory for optional rendered previews": "可选渲染预览的输出目录",
}
