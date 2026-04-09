# Structure Schema 固定接口规范

## 1. 设计目的

`structure_schema` 是 SlopeRA3D 的结构建模统一输入协议，用于连接以下两类模块：

- 上游生成端
  - 人工编写
  - 大模型读取三视图、设计说明、工程表格后自动生成
- 下游执行端
  - Path A：FLAC3D structure 元素建模
  - Path B：Gmsh 实体 zone 建模

为保证程序稳定消费与后续自动生成可控，建议将 `structure_schema` 固定为一套受约束的 JSON 接口，而不是自由格式描述。

## 2. 顶层结构

推荐固定为四个顶层字段：

```json
{
  "meta": {},
  "primitives": [],
  "operations": [],
  "outputs": {
    "final_objects": []
  }
}
```

含义：

- `meta`
  - 元信息
- `primitives`
  - 原始几何对象定义
- `operations`
  - 布尔运算或组合运算
- `outputs.final_objects`
  - 最终进入建模流程的对象列表

## 3. 顶层字段说明

### 3.1 `meta`

建议字段：

```json
{
  "unit": "m",
  "description": "project description",
  "confidence": 0.95,
  "assumptions": [
    "optional note 1",
    "optional note 2"
  ]
}
```

约束建议：

- `unit`
  - 当前建议固定为 `m`
- `description`
  - 简要描述结构方案来源
- `confidence`
  - 可选，范围建议 `0~1`
- `assumptions`
  - 可选，记录大模型生成时的假设

### 3.2 `primitives`

`primitives` 为对象数组，每个对象至少包含：

```json
{
  "id": "unique_name",
  "type": "primitive_type"
}
```

通用约束：

- `id`
  - 必须唯一
- `type`
  - 必须来自受支持集合
- 所有坐标统一使用三维数组 `[x, y, z]`
- 所有长度单位统一为米
- 所有尺寸字段必须为正数

### 3.3 `operations`

用于定义几何布尔或组合关系。当前项目中该部分仍然偏轻量使用，但建议保留接口位，便于后续扩展。

推荐形式：

```json
{
  "id": "op_1",
  "type": "boolean_union",
  "objects": ["obj_a", "obj_b"]
}
```

建议约束：

- `id` 必须唯一
- `objects` 中的引用必须存在
- `type` 应来自明确枚举，不要自由命名

### 3.4 `outputs.final_objects`

用于指定最终参与建模的对象：

```json
{
  "final_objects": ["pile_1", "anchor_1"]
}
```

约束：

- 必须为字符串数组
- 每个值必须引用已存在的 primitive 或 operation 结果

## 4. 当前支持的 primitive

### 4.1 `cylinder`

适用于：

- Path A 的 pile 语义对象
- Path B 的实体桩体

格式：

```json
{
  "id": "pile_1",
  "type": "cylinder",
  "center": [380933.0, 2835468.0, 335.0],
  "radius": 0.75,
  "height": 15.0
}
```

必填字段：

- `center`
- `radius`
- `height`

### 4.2 `box`

适用于：

- Path B 实体挡墙、承台、基础块体等

格式：

```json
{
  "id": "cap_1",
  "type": "box",
  "origin": [0.0, 0.0, 0.0],
  "size": [5.0, 2.0, 1.5]
}
```

### 4.3 `polyline_extrude`

适用于：

- Path B 的任意截面挤出实体

格式：

```json
{
  "id": "wall_1",
  "type": "polyline_extrude",
  "profile": [
    [0.0, 0.0],
    [2.0, 0.0],
    [2.0, 1.0],
    [0.0, 1.0]
  ],
  "z0": 330.0,
  "height": 6.0
}
```

### 4.4 `line_segment`

适用于：

- Path A 的 beam / cable

格式：

```json
{
  "id": "anchor_1",
  "type": "line_segment",
  "start": [380940.0, 2835468.0, 346.0],
  "end": [380955.0, 2835465.0, 341.0],
  "radius": 0.06
}
```

注意：

- Path B 当前不支持 `line_segment`

### 4.5 `member`

适用于：

- Path A 的结构语义扩展

注意：

- 当前不建议作为 Path B 输入

## 5. Path A 与 Path B 的输入子集

### 5.1 Path A

适用对象：

- pile
- beam
- cable

推荐 primitive：

- `cylinder`
- `line_segment`
- `member`

说明：

- Path A 的重点是“结构语义正确”
- 可以包含 1D 构件
- 更适合带锚索、梁、结构单元响应分析的场景

### 5.2 Path B

适用对象：

- 实体化支护结构

推荐 primitive：

- `cylinder`
- `box`
- `polyline_extrude`

不推荐或不支持：

- `line_segment`
- `member`

说明：

- Path B 的重点是“几何实体化与体网格稳定”
- 结构对象必须可以转为三维实体

## 6. 最小示例

### 6.1 Path A 示例

```json
{
  "meta": {
    "unit": "m",
    "description": "Path A example"
  },
  "primitives": [
    {
      "id": "pile_1",
      "type": "cylinder",
      "center": [380933.0, 2835468.0, 335.0],
      "radius": 0.75,
      "height": 15.0
    },
    {
      "id": "beam_1",
      "type": "line_segment",
      "start": [380933.0, 2835468.0, 350.0],
      "end": [380949.0, 2835468.0, 350.0],
      "radius": 0.25
    }
  ],
  "operations": [],
  "outputs": {
    "final_objects": ["pile_1", "beam_1"]
  }
}
```

### 6.2 Path B 示例

```json
{
  "meta": {
    "unit": "m",
    "description": "Path B example"
  },
  "primitives": [
    {
      "id": "pile_1",
      "type": "cylinder",
      "center": [380933.0, 2835468.0, 335.0],
      "radius": 0.75,
      "height": 15.0
    },
    {
      "id": "pile_2",
      "type": "cylinder",
      "center": [380937.0, 2835468.0, 335.0],
      "radius": 0.75,
      "height": 15.0
    }
  ],
  "operations": [],
  "outputs": {
    "final_objects": ["pile_1", "pile_2"]
  }
}
```

## 7. 上游大模型生成建议

如果后续由大模型自动生成 `structure_schema`，建议遵循以下策略：

- 先识别目标路线是 Path A 还是 Path B
- Path A 优先输出结构语义完整的结果
- Path B 优先输出可实体化 primitive
- 缺失关键尺寸时，不要臆造不合理结构
- 对不确定项写入 `meta.assumptions`
- 必须保证 `final_objects` 的引用闭合

## 8. 常见错误

### 8.1 `id` 重复

错误：

```json
[
  {"id": "pile_1", "type": "cylinder"},
  {"id": "pile_1", "type": "cylinder"}
]
```

### 8.2 Path B 输入了 1D 构件

错误：

```json
{
  "id": "anchor_1",
  "type": "line_segment"
}
```

说明：

- 该对象应改走 Path A，或改写为可实体化对象

### 8.3 `final_objects` 引用了未定义对象

错误：

```json
{
  "outputs": {
    "final_objects": ["pile_99"]
  }
}
```

## 9. 推荐实践

- 把 `structure_schema` 当成正式接口协议维护
- README 中保留概览，详细约束统一落到本文件
- 后续若接入大模型自动生成，建议同步增加自动校验器和示例库
