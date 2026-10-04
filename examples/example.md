# Multilingual Markdown to DOCX Conversion Example

This is a comprehensive example document showcasing **multilingual** and complex Markdown features for testing conversion to modern DOCX standards. It demonstrates the converter's ability to handle international content, bidirectional text, and complex formatting scenarios.

这是一个展示**多语言**和复杂Markdown功能的综合示例文档，用于测试转换到最新DOCX标准的功能。

## Multilingual Text Formatting

### Basic Formatting

**English Bold** | **中文粗体** | **Texto en Negrita** | **Texte Gras** | **Жирный текст** | **太字** | **نص عريض**

*English Italic* | *中文斜体* | *Texto en Cursiva* | *Texte Italique* | *Курсивный текст* | *斜体* | *نص مائل*

~~English Strikethrough~~ | ~~中文删除线~~ | ~~Texto Tachado~~ | ~~Texte Barré~~ | ~~Зачеркнутый текст~~ | ~~取り消し線~~ | ~~نص مشطوب~~

### Superscript & Subscript Examples

- Chemical formulas: H~2~O, CO~2~, C~6~H~12~O~6~ (化学公式)
- Mathematical expressions: E=mc^2^, x^2^+y^2^=z^2^ (数学公式)
- Ordinal numbers: 1^st^, 2^nd^, 3^rd^ (序数)
- Arabic-Indic numerals: ١^٢^ + ٣^٤^ (阿拉伯数字)

### Block Quotes

> This is an English quote block with important information.
>
> 这是中文引用块，包含重要信息。

> هذا اقتباس باللغة العربية يحتوي على معلومات مهمة.
> (This is an Arabic quote block containing important information.)

> Ceci est une citation en français avec des informations importantes.
> (This is a French quote block with important information.)

> これは日本語の引用ブロックで、重要な情報が含まれています。
> (This is a Japanese quote block containing important information.)

> Это цитата на русском языке с важной информацией.
> (This is a Russian quote with important information.)

## Multilingual Lists

### Mixed Language Unordered Lists

- 🇺🇸 English Item (主要语言)
- 🇨🇳 Chinese Item - 中文项目
- 🇪🇸 Spanish Item - Elemento Español
- 🇫🇷 French Item - Élément Français
- 🇷🇺 Russian Item - Русский элемент
- 🇯🇵 Japanese Item - 日本語項目
- 🇸🇦 Arabic Item - عنصر عربي
  - Nested English item
  - 嵌套中文项目
  - Elemento anidado en español
    - Deeper nesting level
    - 更深层嵌套
    - عنصر متداخل أعمق

### Multilingual Ordered Lists

1. **First Step** - Initialize converter (初始化转换器)
2. **Second Step** - Configure options (配置选项)
3. **Third Step** - Execute conversion (执行转换 / Ejecutar conversión)
4. **Fourth Step** - Verify results (验证结果 / Vérifier les résultats)
5. **Fifth Step** - Complete processing (完成处理 / Завершить обработку)
6. **Sixth Step** - Clean up resources (清理资源 / リソースをクリーンアップ)
7. **Seventh Step** - Generate report (生成报告 / إنشاء التقرير)

### Multilingual Task Lists

- [x] ✅ Complete English documentation (主要文档)
- [x] ✅ Finish Chinese documentation (完成中文文档)
- [ ] 📝 Complete Spanish documentation (Completar documentación en español)
- [ ] 📝 Finish French documentation (Terminer la documentation française)
- [ ] 📝 Complete Russian documentation (Завершить русскую документацию)
- [ ] 📝 Finish Japanese documentation (日本語ドキュメントを完成させる)
- [ ] 📝 Complete Arabic documentation (إكمال الوثائق العربية)

## Multilingual Code Examples

### Python Code

```python
def convert_multilingual_markdown(input_file, output_file, languages=None):
    """
    Multilingual Markdown conversion function
    多语言Markdown转换函数
    Función de conversión de Markdown multilingüe
    """
    if languages is None:
        languages = ['en', 'zh', 'es', 'fr', 'ru', 'ja', 'ar']

    converter = MarkdownToDocxConverter()

    # English comment: Set language support
    # 中文注释：设置语言支持
    # Comentario en español: Configurar soporte de idiomas
    for lang in languages:
        converter.add_language_support(lang)

    return converter.convert(input_file, output_file)

# Usage example (使用示例)
result = convert_multilingual_markdown("multilingual_example.md", "output.docx")
print(f"Conversion completed (转换完成): {result}")
```

### JavaScript Code

```javascript
// Multilingual configuration object (多语言配置对象)
const multilingualConfig = {
    "English": { direction: "ltr", encoding: "utf-8" },
    "中文": { direction: "ltr", encoding: "utf-8" },
    "Español": { direction: "ltr", encoding: "utf-8" },
    "Français": { direction: "ltr", encoding: "utf-8" },
    "Русский": { direction: "ltr", encoding: "utf-8" },
    "日本語": { direction: "ltr", encoding: "utf-8" },
    "العربية": { direction: "rtl", encoding: "utf-8" }
};

function processMultilingualText(text, language) {
    const config = multilingualConfig[language];
    return {
        content: text,
        direction: config.direction,
        encoding: config.encoding
    };
}
```

### SQL Queries

```sql
-- Multilingual database query example (多语言数据库查询示例)
SELECT
    id,
    title_en AS 'English Title',
    title_zh AS 'Chinese Title (中文标题)',
    title_es AS 'Spanish Title (Título Español)',
    title_fr AS 'French Title (Titre Français)',
    title_ru AS 'Russian Title (Русский заголовок)',
    title_ja AS 'Japanese Title (日本語タイトル)',
    title_ar AS 'Arabic Title (العنوان العربي)'
FROM multilingual_documents
WHERE status = 'published'
ORDER BY created_date DESC;
```

## Complex Multilingual Tables

### Language Features Comparison

| Language | Direction | Character Set | Complexity | Support Status |
|:---------|:---------:|:-------------:|:----------:|:--------------:|
| English | Left-to-Right (LTR) | Latin | Medium | ✅ Full Support |
| 中文 (Chinese) | Left-to-Right (从左到右) | CJK Unified (CJK统一汉字) | High (高) | ✅ Full Support (完全支持) |
| Español | Left-to-Right (LTR) | Extended Latin (Latino Extendido) | Medium (Medio) | ✅ Full Support (Soporte Completo) |
| Français | Left-to-Right (LTR) | Extended Latin (Latin Étendu) | Medium (Moyen) | ✅ Full Support (Support Complet) |
| Русский | Left-to-Right (LTR) | Cyrillic (Кириллица) | Medium (Средний) | ✅ Full Support (Полная поддержка) |
| 日本語 | Left-to-Right (LTR) | Hiragana/Katakana/Kanji | Very High (非常に高い) | ✅ Full Support (完全サポート) |
| العربية | Right-to-Left (RTL) | Arabic Script (العربية) | High (عالي) | ✅ Full Support (دعم كامل) |

### Number Systems Comparison

| Number System | 1-10 | Example | Usage |
|:--------------|:-----|:--------|:------|
| Arabic Numerals | 1 2 3 4 5 6 7 8 9 10 | Year 2024 | International (国际通用) |
| Chinese Numerals (中文数字) | 一 二 三 四 五 六 七 八 九 十 | 二〇二四年 (Year 2024) | Chinese Documents (中文文档) |
| Roman Numerals | I II III IV V VI VII VIII IX X | MMXXIV (Year 2024) | Formal Documents (正式文档) |
| Arabic-Indic (阿拉伯-印度数字) | ١ ٢ ٣ ٤ ٥ ٦ ٧ ٨ ٩ ١٠ | ٢٠٢٤ (Year 2024) | Arabic Documents (阿拉伯文档) |
| Japanese Numerals (日文数字) | 一 二 三 四 五 六 七 八 九 十 | 二千二十四年 (Year 2024) | Japanese Documents (日文文档) |

### Currency and Units Table

| Country/Region | Currency | Symbol | Example Price | Unit System |
|:---------------|:---------|:-------|:--------------|:------------|
| United States | US Dollar | $ | $15.99 | Imperial |
| China (中国) | Chinese Yuan (人民币) | ¥ | ¥100.00 | Metric (公制) |
| Spain (España) | Euro (欧元) | € | €12.50 | Metric (Métrico) |
| France | Euro | € | 12,50 € | Metric (Métrique) |
| Russia (Россия) | Russian Ruble (Российский рубль) | ₽ | 1000₽ | Metric (Метрическая) |
| Japan (日本) | Japanese Yen (日本円) | ¥ | ¥1,500 | Metric (メートル法) |
| Saudi Arabia (السعودية) | Saudi Riyal (ريال سعودي) | ﷼ | ﷼60.00 | Metric (متري) |

## Complex Text Direction Examples

### Mixed Direction Text

This English text contains Arabic: **البرمجة ممتعة** (Programming is fun), and continues in English.

这是一段包含阿拉伯语的中文文本：**مرحبا بكم في عالم البرمجة** (Welcome to the programming world)，然后继续中文内容。

### Right-to-Left Language Examples

**Arabic Paragraph:**

هذا مثال على نص باللغة العربية يُكتب من اليمين إلى اليسار. يحتوي هذا النص على **نص عريض** و *نص مائل* و ~~نص مشطوب~~. كما يحتوي على `كود مضمن` وروابط مثل [جيت هاب](https://github.com).

*Translation: This is an example of Arabic text written from right to left. This text contains **bold text** and *italic text* and ~~strikethrough text~~. It also contains `inline code` and links like [GitHub](https://github.com).*

**Hebrew Example:**

זהו דוגמה של טקסט בעברית הנכתב מימין לשמאל. הטקסט כולל **טקסט מודגש** ו*טקסט נטוי*.

*Translation: This is an example of Hebrew text written from right to left. The text includes **bold text** and *italic text*.*

## Multilingual Mathematical Formulas

### Basic Mathematics

- English: The quadratic formula $ax^2 + bx + c = 0$ has solutions $x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$
- Chinese (中文): 二次方程 $ax^2 + bx + c = 0$ 的解为 $x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$
- Spanish: La fórmula cuadrática $ax^2 + bx + c = 0$ tiene soluciones $x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$

### Complex Formulas

$$
\begin{align}
\text{English: Euler's Formula} \quad & e^{i\pi} + 1 = 0 \\
\text{Chinese (中文): 欧拉公式} \quad & e^{i\pi} + 1 = 0 \\
\text{French: Formule d'Euler} \quad & e^{i\pi} + 1 = 0 \\
\text{Arabic: معادلة أويلر} \quad & e^{i\pi} + 1 = 0
\end{align}
$$

## Multilingual Links and References

### External Links

- English Resources: [GitHub](https://github.com) | [Stack Overflow](https://stackoverflow.com)
- Chinese Resources (中文资源): [GitHub中文社区](https://github.com) | [百度](https://baidu.com)
- Spanish Resources: [GitHub España](https://github.com) | [Wikipedia](https://es.wikipedia.org)
- French Resources: [GitHub France](https://github.com) | [Wikipédia](https://fr.wikipedia.org)
- Russian Resources: [GitHub Россия](https://github.com) | [Яндекс](https://yandex.ru)
- Japanese Resources: [GitHub Japan](https://github.com) | [Wikipedia日本語](https://ja.wikipedia.org)
- Arabic Resources: [GitHub العربية](https://github.com) | [ويكيبيديا العربية](https://ar.wikipedia.org)

### Multilingual Footnotes

This is an English footnote example[^en1], 这是中文脚注示例[^zh1], and this is a Spanish footnote[^es1].

[^en1]: This is English footnote content with detailed explanation.

[^zh1]: 这是中文脚注内容，包含详细说明。

[^es1]: Este es el contenido de la nota al pie en español con explicación detallada.

## Special Characters and Symbols

### Currency Symbols
¥ $ € £ ₽ ₹ ₩ ₪ ₦ ₡ ₨ ₫ ₱ ₵ ₴ ₸ ₼ ₾ ﷼

### Mathematical Symbols
∑ ∏ ∫ ∂ ∇ ∞ ± × ÷ ≠ ≤ ≥ ≈ ∝ ∴ ∵ ∈ ∉ ⊂ ⊃ ∪ ∩ ∧ ∨ ¬

### Special Punctuation
« » „ " " ' ' ‚ ‛ ‹ › ¿ ¡ § ¶ † ‡ • ‰ ′ ″ ‴ ※ ‼ ⁇ ⁈ ⁉

### Arrow Symbols
← → ↑ ↓ ↔ ↕ ↖ ↗ ↘ ↙ ⇐ ⇒ ⇑ ⇓ ⇔ ⇕ ⇖ ⇗ ⇘ ⇙

## Conclusion

This multilingual example document demonstrates the powerful capabilities of the Markdown to DOCX converter when handling complex internationalized content. It serves as a comprehensive test case for real-world multilingual document conversion scenarios.

这个多语言示例文档展示了Markdown到DOCX转换器在处理复杂国际化内容时的强大能力。

### Supported Features

1. **Multilingual Text Processing** - Seamless handling of multiple languages in a single document (多语言文本处理)
2. **Bidirectional Text Support** - Proper rendering of both LTR and RTL languages (双向文本支持)
3. **Complex Table Layouts** - Advanced table structures with multilingual content (复杂表格布局)
4. **Internationalized Number Systems** - Support for various numeral systems (国际化数字系统)
5. **Multilingual Code Highlighting** - Syntax highlighting with multilingual comments (多语言代码高亮)
6. **Special Character Support** - Comprehensive Unicode character support (特殊字符支持)
7. **Mathematical Formulas** - LaTeX-style formulas with multilingual descriptions (数学公式)
8. **Cultural Formatting** - Proper formatting for different cultural contexts (文化格式化)

### Testing Scenarios

This example validates the converter's ability to handle:

- **Mixed writing directions** in the same document
- **Complex table structures** with multilingual headers and content
- **International currency and number formats**
- **Code examples** with comments in multiple languages
- **Mathematical notation** with multilingual descriptions
- **Special Unicode characters** and symbols
- **Footnotes and references** in different languages

Through this comprehensive example, we verify the reliability and accuracy of the converter when processing real-world multilingual documents, ensuring it meets the needs of global users and international organizations.

通过这个综合示例，我们验证了转换器在处理真实世界多语言文档时的可靠性和准确性，确保它能满足全球用户和国际组织的需求。
