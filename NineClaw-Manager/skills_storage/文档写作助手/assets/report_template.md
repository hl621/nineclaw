# {{project_name}} 代码质量报告

**分析时间**: {{timestamp}}  
**分析范围**: {{scope}}  
**总体评级**: {{overall_grade}}

## 执行摘要

- 分析文件数: {{file_count}}
- 平均评级: {{average_grade}}
- 发现问题: {{total_issues}}
- 高复杂度函数: {{high_complexity_count}}

## 详细结果

{{#files}}
### {{file_name}}

- **评级**: {{grade}}
- **代码行**: {{lines.code}} (总计 {{lines.total}})
- **注释率**: {{lines.comment_ratio}}%
- **平均复杂度**: {{metrics.average_complexity}}

{{#issues}}
- [ ] {{.}}
{{/issues}}

{{/files}}

## 改进建议

1. {{suggestion_1}}
2. {{suggestion_2}}
3. {{suggestion_3}}

---
*由 code-quality-analyzer Skill 自动生成*