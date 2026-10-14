**关键要求：你必须按顺序完成以下步骤。不要跳过前置步骤直接编写代码。**

如果需要填写 PDF 表单，首先检查 PDF 是否包含可填写表单字段。在本文件所在目录运行：
 `python scripts/check_fillable_fields <file.pdf>`，然后根据结果进入“可填写字段”或“不可填写字段”部分，并遵循相应说明。

# 可填写字段
如果 PDF 包含可填写表单字段：
- 在本文件所在目录运行：`python scripts/extract_form_field_info.py <input.pdf> <field_info.json>`。该脚本会创建一个 JSON 文件，其中的字段列表采用以下格式：
```
[
  {
    "field_id": (unique ID for the field),
    "page": (page number, 1-based),
    "rect": ([left, bottom, right, top] bounding box in PDF coordinates, y=0 is the bottom of the page),
    "type": ("text", "checkbox", "radio_group", or "choice"),
  },
  // Checkboxes have "checked_value" and "unchecked_value" properties:
  {
    "field_id": (unique ID for the field),
    "page": (page number, 1-based),
    "type": "checkbox",
    "checked_value": (Set the field to this value to check the checkbox),
    "unchecked_value": (Set the field to this value to uncheck the checkbox),
  },
  // Radio groups have a "radio_options" list with the possible choices.
  {
    "field_id": (unique ID for the field),
    "page": (page number, 1-based),
    "type": "radio_group",
    "radio_options": [
      {
        "value": (set the field to this value to select this radio option),
        "rect": (bounding box for the radio button for this option)
      },
      // Other radio options
    ]
  },
  // Multiple choice fields have a "choice_options" list with the possible choices:
  {
    "field_id": (unique ID for the field),
    "page": (page number, 1-based),
    "type": "choice",
    "choice_options": [
      {
        "value": (set the field to this value to select this option),
        "text": (display text of the option)
      },
      // Other choice options
    ],
  }
]
```
- 使用以下脚本将 PDF 转换为 PNG（每页一张图像；在本文件所在目录运行）：
`python scripts/convert_pdf_to_images.py <file.pdf> <output_directory>`
然后分析图像，确定每个表单字段的用途（务必将边界框的 PDF 坐标转换为图像坐标）。
- 创建 `field_values.json` 文件，按以下格式提供每个字段要填写的值：
```
[
  {
    "field_id": "last_name", // Must match the field_id from `extract_form_field_info.py`
    "description": "The user's last name",
    "page": 1, // Must match the "page" value in field_info.json
    "value": "Simpson"
  },
  {
    "field_id": "Checkbox12",
    "description": "Checkbox to be checked if the user is 18 or over",
    "page": 1,
    "value": "/On" // If this is a checkbox, use its "checked_value" value to check it. If it's a radio button group, use one of the "value" values in "radio_options".
  },
  // more fields
]
```
- 在本文件所在目录运行 `fill_fillable_fields.py` 脚本，创建已填写的 PDF：
`python scripts/fill_fillable_fields.py <input pdf> <field_values.json> <output pdf>`
该脚本会验证所提供的字段 ID 和值是否有效；如果打印错误消息，请修正相应字段后重试。

# 不可填写字段
如果 PDF 不包含可填写表单字段，则需要添加文本批注。首先尝试从 PDF 结构中提取坐标（更准确）；如有需要，再回退到视觉估算。

## 第 1 步：优先尝试结构提取

运行以下脚本，提取文本标签、线条和复选框及其精确 PDF 坐标：
`python scripts/extract_form_structure.py <input.pdf> form_structure.json`

该脚本会创建一个 JSON 文件，其中包含：
- **labels**：每个文本元素及其精确坐标（PDF 点单位下的 x0、top、x1、bottom）
- **lines**：界定行边界的水平线
- **checkboxes**：表示复选框的小正方形矩形（含中心坐标）
- **row_boundaries**：根据水平线计算出的行顶部/底部位置

**检查结果**：如果 `form_structure.json` 中有有意义的标签（即与表单字段对应的文本元素），请使用**方案 A：基于结构的坐标**。如果 PDF 是扫描件/基于图像，且标签很少或完全没有，请使用**方案 B：视觉估算**。

---

## 方案 A：基于结构的坐标（首选）

当 `extract_form_structure.py` 在 PDF 中找到了文本标签时使用此方案。

### A.1：分析结构

读取 form_structure.json 并识别：

1. **标签组**：共同组成单个标签的相邻文本元素（例如 "Last" + "Name"）
2. **行结构**：`top` 值相近的标签位于同一行
3. **字段列**：输入区域从标签末端之后开始（x0 = label.x1 + gap）
4. **复选框**：直接使用结构中提供的复选框坐标

**坐标系**：PDF 坐标以页面顶部为 y=0，y 向下递增。

### A.2：检查缺失元素

结构提取可能无法检测全部表单元素。常见情况包括：
- **圆形复选框**：只有正方形矩形会被识别为复选框
- **复杂图形**：装饰元素或非标准表单控件
- **褪色或浅色元素**：可能无法提取

如果 PDF 图像中存在 form_structure.json 未包含的表单字段，则需要对这些特定字段使用**视觉分析**（参阅下文“混合方案”）。

### A.3：使用 PDF 坐标创建 fields.json

对于每个字段，根据提取出的结构计算输入坐标：

**文本字段：**
- entry x0 = label x1 + 5（标签后留出小间隙）
- entry x1 = 下一个标签的 x0，或行边界
- entry top = 与标签 top 相同
- entry bottom = 下方的行边界线，或 label bottom + row_height

**复选框：**
- 直接使用 form_structure.json 中的复选框矩形坐标
- entry_bounding_box = [checkbox.x0, checkbox.top, checkbox.x1, checkbox.bottom]

使用 `pdf_width` 和 `pdf_height` 创建 fields.json（表示采用 PDF 坐标）：
```json
{
  "pages": [
    {"page_number": 1, "pdf_width": 612, "pdf_height": 792}
  ],
  "form_fields": [
    {
      "page_number": 1,
      "description": "Last name entry field",
      "field_label": "Last Name",
      "label_bounding_box": [43, 63, 87, 73],
      "entry_bounding_box": [92, 63, 260, 79],
      "entry_text": {"text": "Smith", "font_size": 10}
    },
    {
      "page_number": 1,
      "description": "US Citizen Yes checkbox",
      "field_label": "Yes",
      "label_bounding_box": [260, 200, 280, 210],
      "entry_bounding_box": [285, 197, 292, 205],
      "entry_text": {"text": "X"}
    }
  ]
}
```

**重要**：使用 `pdf_width`/`pdf_height`，并直接采用 form_structure.json 中的坐标。

### A.4：验证边界框

填写前，检查边界框是否有误：
`python scripts/check_bounding_boxes.py fields.json`

该脚本会检查相交的边界框，以及相对于字号而言过小的输入框。填写前请修复所有报告的错误。

---

## 方案 B：视觉估算（回退方案）

当 PDF 是扫描件/基于图像，且结构提取未找到可用文本标签时使用此方案（例如所有文本都显示为 "(cid:X)" 模式）。

### B.1：将 PDF 转换为图像

`python scripts/convert_pdf_to_images.py <input.pdf> <images_dir/>`

### B.2：初步识别字段

检查每个页面图像，识别表单各部分，并对字段位置作出**粗略估算**：
- 表单字段标签及其大致位置
- 输入区域（用于文本输入的线条、框或空白区域）
- 复选框及其大致位置

记录每个字段的大致像素坐标（此时无需精确）。

### B.3：放大细化（准确性至关重要）

对每个字段，围绕估算位置裁剪一块区域，以精确细化坐标。

**使用 ImageMagick 创建放大裁剪图：**
```bash
magick <page_image> -crop <width>x<height>+<x>+<y> +repage <crop_output.png>
```

其中：
- `<x>, <y>` = 裁剪区域左上角（用粗略估算位置减去内边距）
- `<width>, <height>` = 裁剪区域尺寸（字段区域，加上四周各约 50px 的内边距）

**示例：** 若要细化估算位置约为 (100, 150) 的 "Name" 字段：
```bash
magick images_dir/page_1.png -crop 300x80+50+120 +repage crops/name_field.png
```

（注意：如果 `magick` 命令不可用，请尝试使用参数相同的 `convert`。）

**检查裁剪后的图像**，确定精确坐标：
1. 找到输入区域开始处的精确像素（标签之后）
2. 找到输入区域结束处（下一个字段或边缘之前）
3. 找到输入线/框的顶部和底部

**将裁剪图坐标转换回完整图像坐标：**
- full_x = crop_x + crop_offset_x
- full_y = crop_y + crop_offset_y

示例：如果裁剪从 (50, 120) 开始，而输入框在裁剪图内从 (52, 18) 开始：
- entry_x0 = 52 + 50 = 102
- entry_top = 18 + 120 = 138

**对每个字段重复此过程**；在可行时，将相邻字段放入同一张裁剪图中。

### B.4：使用细化后的坐标创建 fields.json

使用 `image_width` 和 `image_height` 创建 fields.json（表示采用图像坐标）：
```json
{
  "pages": [
    {"page_number": 1, "image_width": 1700, "image_height": 2200}
  ],
  "form_fields": [
    {
      "page_number": 1,
      "description": "Last name entry field",
      "field_label": "Last Name",
      "label_bounding_box": [120, 175, 242, 198],
      "entry_bounding_box": [255, 175, 720, 218],
      "entry_text": {"text": "Smith", "font_size": 10}
    }
  ]
}
```

**重要**：使用 `image_width`/`image_height`，并采用放大分析得到的精确像素坐标。

### B.5：验证边界框

填写前，检查边界框是否有误：
`python scripts/check_bounding_boxes.py fields.json`

该脚本会检查相交的边界框，以及相对于字号而言过小的输入框。填写前请修复所有报告的错误。

---

## 混合方案：结构 + 视觉

当结构提取适用于大多数字段，但遗漏某些元素时使用此方案（例如圆形复选框、非常规表单控件）。

1. 对 form_structure.json 中检测到的字段使用**方案 A**
2. **将 PDF 转换为图像**，对缺失字段执行视觉分析
3. 对缺失字段使用**放大细化**（来自方案 B）
4. **合并坐标**：对于来自结构提取的字段，使用 `pdf_width`/`pdf_height`。对于通过视觉估算的字段，必须将图像坐标转换为 PDF 坐标：
   - pdf_x = image_x * (pdf_width / image_width)
   - pdf_y = image_y * (pdf_height / image_height)
5. 在 fields.json 中**统一使用一种坐标系**——将所有坐标转换为采用 `pdf_width`/`pdf_height` 的 PDF 坐标

---

## 第 2 步：填写前验证

**填写前务必验证边界框：**
`python scripts/check_bounding_boxes.py fields.json`

该脚本会检查：
- 相交的边界框（会造成文本重叠）
- 相对于指定字号而言过小的输入框

继续操作前，请修复 fields.json 中报告的所有错误。

## 第 3 步：填写表单

填写脚本会自动检测坐标系并处理转换：
`python scripts/fill_pdf_form_with_annotations.py <input.pdf> fields.json <output.pdf>`

## 第 4 步：验证输出

将已填写的 PDF 转换为图像，并验证文本放置位置：
`python scripts/convert_pdf_to_images.py <output.pdf> <verify_images/>`

如果文本位置不正确：
- **方案 A**：检查是否使用了 form_structure.json 中的 PDF 坐标以及 `pdf_width`/`pdf_height`
- **方案 B**：检查图像尺寸是否匹配，以及坐标是否为准确的像素值
- **混合方案**：确保视觉估算字段的坐标转换正确
