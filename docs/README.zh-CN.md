<div align="center">

# canvasgrade

**直接用你现成的 Excel/csv 成绩表格在 Canvas 上建 rubric，然后把分数、评语和总分一次推上去。**

[![PyPI](https://img.shields.io/pypi/v/canvasgrade?color=1f4ea1)](https://pypi.org/project/canvasgrade/)
[![Python](https://img.shields.io/pypi/pyversions/canvasgrade)](https://pypi.org/project/canvasgrade/)
[![CI](https://github.com/4rthurCai/canvasgrade/actions/workflows/ci.yml/badge.svg)](https://github.com/4rthurCai/canvasgrade/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/4rthurCai/canvasgrade/blob/master/LICENSE)

[English](https://github.com/4rthurCai/canvasgrade/blob/master/README.md) · 简体中文

</div>

---

不用去 Chrome DevTools 里找 rubric ID，不用把成绩表裁成只剩学号和分数的 csv，也不用先去 Canvas 上新建的 rubric。

```bash
pip3 install "canvasgrade[all]"
canvasgrade push grades.xlsx --create-rubric --dry-run   # 先看
canvasgrade push grades.xlsx --create-rubric             # 再推
```

## 解决的问题

canvasgrade 能直接读你现有的表，并且在写任何东西之前，告诉你它把每一列理解成了什么。

`canvasgrade inspect grades.xlsx`：

| 列 | 识别为 | 满分 | 依据 |
|---|---|---:|---|
| `Student` | name | | 表头是学生姓名 |
| `ID` | canvas_id | | 表头是 Canvas 用户 ID |
| `Design (10)` | **criterion** | 10 | 表头声明了满分 10 |
| `Tests (20)` | **criterion** | 20 | 表头声明了满分 20 |
| `Code Quality (35)` | **criterion** | 35 | 表头声明了满分 35 |
| `Docs (5)` | **criterion** | 5 | 表头声明了满分 5 |
| `Total (70)` | total | 70 | 表头含 'total' |

> 44 名学生，44 人表里有总分，文件共 44 行
> 4 个 criteria 合计 70 分

**每个判断都附带理由，每个判断都能改。** `inspect` 完全离线，不需要 token。

## 写之前先看

`--dry-run` 会把整个方案算出来——包括**将要创建**的那个 rubric——但什么都不发送：

```bash
canvasgrade push grades.xlsx --create-rubric --dry-run
```

> Project 1 (id 418271)，满分 70
> 将创建 rubric「Project 1 rubric」，含 4 个 criteria

**将要创建的 rubric**

| # | Criterion | 满分 | Canvas id |
|---:|---|---:|---|
| 1 | Design | 10 | `_preview_1` |
| 2 | Tests | 20 | `_preview_2` |
| 3 | Code Quality | 35 | `_preview_3` |
| 4 | Docs | 5 | `_preview_4` |
| | **合计** | **70** | |

**将要推送的分数**

| 学生 | Canvas id | 总分 | 各项 | 评语 |
|---|---:|---:|---|---:|
| Student 01 | 1001 | **66** | 7.8 · 19.8 · 34.4 · 4 | |
| Student 02 | 1002 | **52.6** | 8.3 · 9.9 · 32.2 · 2.2 | |
| *…还有 42 人* | | | | |

> **44 名学生就绪** ｜ 总分 43.6-66，均分 54.7

criterion ID 显示成 `_preview_N`，是因为还什么都没创建。确认之后它们会变成 Canvas 返回的真实 ID。

## 它做什么

| | |
|---|---|
| **替你建 rubric** | 表头变成 criteria。API 直接返回 criterion ID，所以没有 ID 要查。 |
| **读你真实的表** | 身份列、队名分隔行、ratio、阶段小计、打分人姓名列全都能识别——不是分数的那些不会混进 rubric。 |
| **一次批量推送** | 走 Canvas 的异步批量接口：每批一次请求，而不是每个学生两次。 |
| **逐条评语** | `Design comment` 这样的列会变成挂在该 criterion 上的反馈。 |
| **闭环** | `pull` 生成填空模板，学生和 criteria 都已就位；填完直接把同一份文件推回去。 |
| **安全稳定** | 学生按 Canvas ID → SIS/登录 ID → 姓名依次匹配，两个人同样像的时候宁可停下来也不猜。 |
| **允许纠正** | 每个识别出的角色、criterion 名称和满分都能覆盖，命令行和 GUI 都可以，在创建任何东西之前。 |

## 安装

```bash
pip3 install "canvasgrade[all]"       # 命令行 + 网页 GUI + 绘图
pip3 install canvasgrade              # 只要命令行
pip3 install "canvasgrade[web]"       # 命令行 + 网页 GUI
```

需要 Python 3.11 或更高。

> **项目刚刚开启** 创建 rubric、批量推送分数和评语、拉取填空模板都已对真实 Canvas 端到端验证过，但使用者还很少。每次写入前都有预览和确认，`--dry-run` 什么都不发送——请先用它。

## 配置

在 **账户 → 设置 → 新建访问令牌** 生成 token，然后：

```bash
canvasgrade config init     # 生成 ~/.canvasgrade.toml，权限 600
canvasgrade config show     # 查看解析结果，token 会脱敏显示
canvasgrade courses         # 课程 ID
canvasgrade assignments     # 作业 ID，以及哪些已挂 rubric
canvasgrade rubrics         # rubric ID，供 --rubric-id 使用
```

**任何 ID 都不需要从浏览器开发者工具里扒。**

```toml
# ~/.canvasgrade.toml
api_url = "https://oc.sjtu.edu.cn/"
api_key = "你的 token"

[profiles.vv186]
course_id = 786
assignment_id = 7081
```

然后 `canvasgrade push grades.xlsx -p vv186`。`$CANVAS_API_KEY` 和 `--api-key` 也可以，优先级是：命令行参数 > 环境变量 > 配置文件。

## 表头怎么被识别

**表头声明了满分，这一列就是一个 rubric criterion：**

| 表头 | 识别为 |
|---|---|
| `Code Quality (35)` | criterion「Code Quality」，满分 35 |
| `Design [10]` | criterion「Design」，满分 10 |
| `设计 （10分）`、`【设计 10分】` | criterion「设计」，满分 10 |
| `题目一 [10']` | criterion「题目一」，满分 10——撇号是装饰，不算进数字 |
| `Student`、`ID`、`SIS Login ID` | 学生身份 |
| `P1 Total (70)` | 作业总分 |
| `Ratio`、`Weight`、`系数` | 乘数，除非加 `--apply-ratio` 否则忽略 |
| `Code Quality comment` | 该 criterion 上的逐人评语 |
| `Joe`、`Vonda` | 忽略——是数值列，但没声明满分 |

几条值得知道的规则：

- **只有明确声明满分的表头才会成为 criterion。** 圆括号或方括号、半角或全角，可以带单位（`分`、`pts`）和末尾的撇号。正是这条规则把打分人姓名、ratio、小计挡在 rubric 外面。如果**整张表**都没有任何表头声明满分，才会退而从数据里推断。
- **声明了满分就压过除总分外的一切。** `Bug reports (team) [5]` 是一个 criterion，不是队伍列。
- **末尾光秃秃的数字永远不算分数。** `Milestone 2` 保持原样。
- **多个列看起来都像总分时，取最后一个**——用 `--total-column` 覆盖。
- **有姓名但没有 ID 也没有分数的行是队名行**，下面的行继承这个队名。

`canvasgrade inspect <文件>` 会显示每一列命中了哪条规则，**以及将要建出的 rubric**——criterion 名称、满分、合计——不需要 token、作业 ID 或任何网络访问。

## 一张表对应多个作业

```bash
canvasgrade push "p1.xlsx" --create-rubric -I 'P1M1 *' --total sum -a 7081
canvasgrade push "p1.xlsx" --create-rubric -I 'P1M2 *' --total sum -a 7082
```

**筛选改变的是 criteria，不是总分。** 用默认的 `--total auto` 时，分数仍然来自表格最后那个总分列——对三个里程碑的表来说那是整个项目的总分。所以推单个里程碑通常要同时加 `--total sum`，或者 `--total-column 'P1M1 Total'`。`--dry-run` 会同时显示两者，推之前就能看出对不上。

## 学生匹配不上时

成绩表里通常同时有 Canvas 用户 ID 和学号，而**光看数字分不出哪个是哪个**——两者都是整数，Canvas ID 有几位只取决于那个实例有多老。所以工具去问Canvas名单：

> `'ID'` 匹配到 0 名学生，但 `'CanvasID'` 这列有 82 个值在本课程的选课名单里。如果那才是 Canvas 用户 ID，请改用 `'CanvasID'` 作为 ID 列。

用 `--id-column 'CanvasID'` 即可，GUI 里在角色下拉框中同样能改。

## 用哪个 rubric

| 参数 | 行为 |
|---|---|
| *(不传)* | 用作业上已挂的 rubric |
| `--create-rubric` | 从表头新建一个 |
| `--rubric-id 7457` | 用某个已有 rubric（`canvasgrade rubrics` 可列出） |
| `--no-rubric` | 只推总分 |

同时传多个会被拒绝，而不是静默排序取其一。

## 总分从哪来

| 参数 | 行为 |
|---|---|
| `--total auto`（默认） | 表里有总分列就用它，否则用各项之和 |
| `--total sum` | 一律用各项之和 |
| `--total sheet` | 一律用总分列，为空则报错 |
| `--total-column 'P1M1 Total'` | 指定哪一列**是**总分 |
| `--rename 'Q1 (10)=设计'` | 改 criterion 在 rubric 上显示的名字 |
| `--describe 'Q1 (10)=…'` | 学生点开该 criterion 时看到的详细说明 |
| `--apply-ratio` | 总分乘以 ratio 列 |

`--apply-ratio` 默认关闭，因为总分列通常已经把 ratio 算进去了。`--use-for-grading` 让 Canvas 用 rubric 合计来重算成绩，默认也关闭——开了会覆盖你表里的总分。

## 拉模板、填分数、推回去

```bash
canvasgrade pull -c 786 -a 7081 -o p2.xlsx --with-grades
```

每个选课学生一行，Canvas ID 已经填好，每个 rubric criterion 一列，还可以预填 Canvas 上已有的分数。填完数字，把同一份文件推回去——不用手抄任何 ID。

批改到一半名单变了（有人加退课），用 `--merge`：

```bash
canvasgrade pull -o p2.xlsx --merge
```

它以当前名单为准，但**保留你已经填好的分数**（按 Canvas ID 匹配，所以调整行序或改姓名都不会丢分），并告诉你都变了什么：保留了多少个分数、谁是新来的、谁已退课、哪些列不在 rubric 里了。

## 网页 GUI

```bash
canvasgrade gui
```

选课程和作业、拖入表格、纠正识别错的地方、预览、推送。只监听 `127.0.0.1`，**你的 token 始终留在服务端进程里，不会发给网页**。

## 绘图

```bash
canvasgrade plot grades.xlsx -o dist.pdf --by-criterion
```

<div align="center">
  <img src="https://raw.githubusercontent.com/4rthurCai/canvasgrade/master/docs/grade-distribution.png" alt="成绩分布图与分项拆解" width="720">
</div>

总分的直方图，配上拟合正态分布和核密度估计；`--by-criterion` 会加一个分项面板，显示每个 criterion 的均分占满分的比例——这个视图最能看出 rubric 哪里需要调整。

## 安全性

- `-n/--dry-run` 完整显示会改什么，一个字节都不发送。
- **回答 `y` 之前不会写入任何东西。** 提示默认为「否」，会说明是否要创建 rubric，并重复一遍警告数量。拒绝之后不留任何痕迹：rubric 是在你确认**之后**才创建的。
- **错误会阻止推送，警告不会**——因为有些警告在正常批改时也会出现（只批了半个班、某些项留空）。想让警告也阻止，用 `--strict`，脚本里推荐这么用。
- 超过 criterion 满分的分数会被截断并警告（`--no-clamp` 改为直接报错）。负分、以及两行指向同一个学生，永远是错误。

## 完整命令参考

[docs/commands.md](https://github.com/4rthurCai/canvasgrade/blob/master/docs/commands.md)（英文）列出了每个命令和参数。也可以直接问工具：

```bash
canvasgrade help             # 命令列表
canvasgrade help push        # 单个命令的详情
```

## 更新日志

见 [CHANGELOG.md](https://github.com/4rthurCai/canvasgrade/blob/master/CHANGELOG.md)（英文）。

## 参与开发

```bash
git clone https://github.com/4rthurCai/canvasgrade && cd canvasgrade
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check canvasgrade tests
```

**永远不要在git上提交真实成绩表。** `tests/fixtures/` 下的测试数据全部是合成的，必须保持如此；`.gitignore` 挡住了常见情况，但那不能替代你自己看一眼将要提交什么。

## 许可

MIT
