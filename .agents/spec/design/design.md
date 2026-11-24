# trading 界面设计规范

本文件是 trading 前端界面的**设计与组件基线**，后续所有界面任务（含首页九块重构）以它和
`.agents/spec/design/prototypes/home.html` 为准。工程分层、提交与测试约定仍以仓库根
`AGENTS.md` 为准，本文件不重复那些内容。

原型是**视觉基线**，本文件是**可执行的实现约束**：原型里哪些写法能直接抄、哪些必须换掉、
哪些类名在本项目里根本不存在，都写在这里。

---

## 1. 令牌来源

### 1.1 颜色：`frontend/src/index.css` 的 CSS 变量

颜色只有一处来源——`frontend/src/index.css` 里的 HSL 三元组（不带 `hsl()` 包裹）。浅色在
`:root`，深色在 `.dark`，两套必须成对；**不要**在组件里写死十六进制或 `rgb()`。

| 变量 | 浅色（`:root`） | 深色（`.dark`） | 用途 |
| --- | --- | --- | --- |
| `--background` | `0 0% 100%` | `240 10% 6%` | 页面底色 |
| `--foreground` | `240 10% 8%` | `0 0% 96%` | 正文 |
| `--card` | `0 0% 100%` | `240 8% 9%` | 卡片底色 |
| `--card-foreground` | `240 10% 8%` | `0 0% 96%` | 卡片文字 |
| `--primary` | `240 10% 8%` | `0 0% 96%` | 主按钮底色 |
| `--primary-foreground` | `0 0% 98%` | `240 10% 8%` | 主按钮文字 |
| `--secondary` | `240 5% 96%` | `240 6% 14%` | 次级按钮底色 |
| `--muted` | `240 5% 96%` | `240 6% 14%` | 弱化底块 |
| `--muted-foreground` | `240 4% 46%` | `240 5% 64%` | 说明文字、表头 |
| `--accent` | `240 5% 96%` | `240 6% 16%` | 悬停底色 |
| `--destructive` | `0 72% 51%` | `0 62% 50%` | 错误 |
| `--border` / `--input` | `240 6% 90%` | `240 5% 18%` | 边框、输入框边框 |
| `--ring` | `240 5% 65%` | `240 5% 40%` | 焦点环 |
| `--radius` | `0.75rem` | 同左 | 圆角基准 |

### 1.2 语义类：`frontend/tailwind.config.ts`

上表通过 `tailwind.config.ts` 的 `colors` 映射成语义类，组件里**只用语义类**，不直接写
`hsl(var(--...))`（唯一的例外是需要内联样式的场景，见 §2.3）：

| 场景 | 底色 | 文字 | 边框 |
| --- | --- | --- | --- |
| 页面 | `bg-background` | `text-foreground` | — |
| 卡片 | `bg-card` | `text-card-foreground` | `border` |
| 弱化块 / 说明 | `bg-muted` / `bg-muted/40` | `text-muted-foreground` | `border-border` |
| 悬停 | `bg-accent` | `text-accent-foreground` | — |
| 主按钮 | `bg-primary` | `text-primary-foreground` | — |
| 次级按钮 | `bg-secondary` | `text-secondary-foreground` | — |
| 错误 | `bg-destructive/…` | `text-destructive` | `border-destructive/40` |
| 焦点 | — | — | `focus-visible:ring-2 focus-visible:ring-ring` |

**语义色之外的状态色**（涨跌、提醒严重度）没有变量，按调色板成对使用，见 §4。

### 1.3 圆角

`--radius: 0.75rem` 是基准，`tailwind.config.ts` 里派生：

- `rounded-lg` = `var(--radius)` = **12px**（卡片、弹窗面板）
- `rounded-md` = `calc(var(--radius) - 2px)` = **10px**（按钮、输入框、列表行）
- `rounded-sm` = `calc(var(--radius) - 4px)` = **8px**
- `rounded-full` = **9999px**（状态徽标、标签）

### 1.4 字号（构建产物里的实际档位）

| 类 | 字号 / 行高 | 用途 |
| --- | --- | --- |
| `text-[10px]` | 10px | 原型里的极小标签；正文**不要**用 |
| `text-[11px]` | 11px | 脚注、表格副行、候选副标题 |
| `text-xs` | 12px / 16px | 表头、数值单元格、按钮 `size="sm"` |
| `text-sm` | 14px / 20px | 正文、说明文字 |
| `text-base` | 16px / 24px | 卡片标题 |
| `text-lg` | 18px / 28px | 区块标题 |
| `text-2xl` | 24px / 32px | 汇总数字 |
| `text-3xl` | 30px / 36px | 账户权益等主数字 |

数值一律加 `font-mono tabular-nums`，避免逐帧跳动时宽度抖动。

### 1.5 间距

实际使用的档位（px）：`p-6` = 24（卡片内边距）、`px-3` = 12（按钮/输入框横向）、
`py-3` = 12（表格单元格纵向）、`py-2` = 8（表头纵向）、`gap-1` = 4、`gap-2` = 8、
`gap-3` = 12、`gap-4` = 16、`gap-6` = 24、`space-y-2/3/4` = 8/12/16。

卡片之间的栅格间距固定 `gap-4`；页面纵向区块间距 `mb-4` / `gap-4`。

### 1.6 字体

`font-sans`：`-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "PingFang SC",
"Hiragino Sans GB", "Microsoft YaHei", Inter, system-ui, sans-serif`。

`font-mono`：`"SF Mono", ui-monospace, SFMono-Regular, Menlo, monospace`。

---

## 2. 组件契约

组件都在 `frontend/src/components/ui/`（基础件）与 `frontend/src/components/layout/`（外壳）。
本文件只约束「允许怎么用」，不重复组件的实现细节。

### 2.1 卡片：`Card` 与 `ModuleCard`

`Card`（`components/ui/card.tsx`）是唯一允许的卡片外壳，类组合固定为
`rounded-lg border bg-card text-card-foreground shadow-sm`；四段结构各自的内边距固定：

| 段 | 类 | 说明 |
| --- | --- | --- |
| `CardHeader` | `flex flex-col gap-1.5 p-6` | 标题 + 描述 |
| `CardTitle` | `text-base font-semibold tracking-tight` | 卡片标题，`h3` |
| `CardDescription` | `text-sm text-muted-foreground` | 元信息行 |
| `CardContent` | `p-6 pt-0` | 主体 |

**不要**给卡片加自定义阴影、渐变或第二层边框；卡片之间的区分只靠 `border` 与 `gap-4`。

`ModuleCard`（`pages/overview/module-card.tsx`）是首页九个模块共用的卡片，结构固定为：

```
Card(id=name, data-module=name, data-status=module.status)
├─ CardHeader
│  ├─ 标题行：CardTitle + 右侧 [StatusBadge] [actions?] [跳转箭头?]
│  └─ 元信息行：meta? · 数据时间：… · HTTP 快照 / N 条记录含推送字段
└─ CardContent：模块不可用时是降级提示，否则是 children
```

| 入参 | 含义 |
| --- | --- |
| `name` / `title` | 模块 id（`data-module` 断言依赖它）与中文标题 |
| `summary` / `module` / `pushedFields` | 整页汇总、本模块信封、推送覆盖的记录数 |
| `to` | 跳转入口；省略则不渲染箭头 |
| `actions` | 标题行里状态徽标与箭头之间的操作位（如「编辑」按钮），必须 `size="sm"` |
| `meta` | 元信息行的第一项（如「已选 3/5」），只放短文本 |

`StatusBadge` 的四种色调固定（成对写，暗色不另写）：

| 状态 | 类 |
| --- | --- |
| `ok`（正常） | `border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400` |
| `stale`（陈旧） | `border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400` |
| `unavailable`（不可用） | `border-rose-600/40 bg-rose-500/10 text-rose-700 dark:text-rose-400` |
| 其它（未知 / 未配置） | `border-border text-muted-foreground` |

### 2.2 按钮：`Button` 变体

`components/ui/button.tsx`，由 `class-variance-authority` 生成。**只允许**用这五个变体与四个
尺寸，不新增变体、不手写按钮类：

| 变体 | 类 | 何时用 |
| --- | --- | --- |
| `default`（主按钮） | `bg-primary text-primary-foreground hover:bg-primary/90` | 一个操作区里唯一的确认动作（保存、提交） |
| `secondary` | `bg-secondary text-secondary-foreground hover:bg-secondary/80` | 次要但需要实底的动作 |
| `outline` | `border bg-transparent hover:bg-accent hover:text-accent-foreground` | 页面级工具动作（刷新） |
| `ghost` | `hover:bg-accent hover:text-accent-foreground` + 默认文字色 `text-muted-foreground` | 卡片内的轻量动作（编辑、取消） |
| `link` | `text-primary underline-offset-4 hover:underline` | 行内跳转 |

幽灵按钮的默认文字色要说清楚，这是浅色外观与原型对齐的关键一条：

- **卡片标题行与弹窗底部的幽灵按钮**（「编辑」「取消」这类轻量动作）默认带
  `text-muted-foreground`，与原型 `GHOST` 常量的写法一致（原型实测 `rgb(113,113,122)`）。
  `Button` 的 `ghost` 变体本身**不带**文字色，因为同一个变体还用在侧边导航、主题切换、
  工具条上，那些位置需要的是前景色；因此这两处由调用方显式加 `className="text-muted-foreground"`。
  新增同类位置时照此处理，不要改共享变体。

尺寸：`default` = 36px 高、`sm` = 32px 高（卡片内一律 `sm`）、`lg` = 40px、`icon` = 36×36。
图标按钮必须带 `aria-label`；图标本身 `aria-hidden="true"`，尺寸 `h-3.5 w-3.5`（按钮内）或
`h-4 w-4`（独立图标）。

### 2.3 弹窗：`Dialog`（本单新增，后续页面复用）

`frontend/src/components/ui/dialog.tsx`。项目里原本没有任何弹窗组件，这是**唯一**的弹窗实现；
新页面需要弹窗时复用它，不要各写一份遮罩 + `role="dialog"`。

| 入参 | 含义 |
| --- | --- |
| `open` | 受控开关；`false` 时不渲染任何 DOM |
| `title` | 标题文本，组件内部用 `useId()` 生成 id 挂在 `aria-labelledby` 上 |
| `description` | 标题下的说明（可选） |
| `children` | 面板主体，放在标题与底部之间 |
| `footer` | 底部操作区：左轻右重，左边放计数/提示，右边放「取消 / 确认」 |
| `onClose` | Esc、点遮罩、调用方主动关闭都走它 |

无障碍契约（AC7 按这些验收）：

- 面板：`role="dialog"`、`aria-modal="true"`、`aria-labelledby` 指向标题；
- `Escape` 关闭；点遮罩关闭；面板内部点击不关闭（只认「按下点就在遮罩上」）；
- 打开时焦点移进面板里第一个可聚焦元素，关闭后焦点回到打开前的元素（触发按钮）；
- `onClose` 存进 ref，不放进 effect 依赖：父组件每次渲染都会给出新函数，否则每次重渲染
  都会重跑「移入 / 恢复焦点」，用户正在输入时焦点会被抢走。
- 点遮罩关闭时必须 `preventDefault()`：遮罩不可聚焦，浏览器的默认按下行为会把焦点移回
  `body`，正好盖掉上面的焦点恢复（Esc 与「取消」不受影响，所以只在这一条路径上暴露）。

**遮罩透明度、面板宽度、列表高度用内联样式**（`rgba(0,0,0,0.5)` / `maxWidth: 28rem` /
`maxHeight: 20rem`），因为对应的 Tailwind 类在本项目的构建产物里不存在，见 §3。

```tsx
<Dialog open={open} title="编辑首页关注列表" description="从自选里选择，最多 5 个"
        onClose={close} footer={<><span className="text-xs text-muted-foreground">已选 3/5</span>
        <div className="flex items-center gap-2">…取消 / 保存…</div></>}>
  {/* 主体 */}
</Dialog>
```

### 2.4 列表与表格

- 表格：`w-full text-sm`；表头 `border-b text-xs text-muted-foreground`，单元格
  `py-2`（表头）/ `py-3`（数据行），数值列 `text-right font-mono tabular-nums`。
- 横向溢出：表格外层包 `overflow-x-auto`，不要让表格把页面撑出横向滚动条。
- 可选列表（如弹窗里的复选框列表）：`<ul className="flex flex-col gap-1">`，每行
  `flex items-center gap-3 rounded-md px-2 py-2`，可点行加 `cursor-pointer hover:bg-accent`，
  禁用行用 `opacity-50`。

---

## 3. 禁用类清单（构建产物里不存在的类）

**Tailwind 只按文本扫描 `frontend/index.html` 与 `frontend/src/**/*.{ts,tsx}` 生成 CSS。**
类是「按需生成」的：只有出现在这两个范围内、以完整类名形式出现的类才会进 CSS。写成内联样式
字符串、拼出来的类名、只写在 Markdown/原型里的类名，都不会生成——**写了不报错，只是静默失效**。

### 3.1 已确认缺失（在 `frontend/dist/assets/*.css` 里查不到）

| 类 | 想做什么 | 本项目怎么写 |
| --- | --- | --- |
| `max-w-md` | 弹窗面板 28rem | 内联 `style={{ maxWidth: "28rem" }}` |
| `max-w-lg` | 面板 32rem | 内联样式 |
| `bg-black/50` | 遮罩 50% 黑 | 内联 `style={{ backgroundColor: "rgba(0,0,0,0.5)" }}` |
| `line-through` | 划掉的旧值 | 内联 `style={{ textDecoration: "line-through" }}` |
| `border-dashed` | 空状态虚线框 | 内联 `style={{ borderStyle: "dashed" }}` |
| `max-h-72` / `max-h-80` | 列表高度 18/20rem | 内联 `style={{ maxHeight: "20rem" }}` |
| `mr-1` | 1 格右外边距 | `gap-*` 或父级 `flex`，不要靠 margin 堆间距 |
| `ring-1` | 1px 焦点环 | `focus-visible:ring-2`（`ring-1` 未生成） |
| `select-none` | 禁止选中 | 内联 `userSelect` |
| `pointer-events-none` | 禁用指针 | 用 `disabled` + `opacity-50` |
| `grid-cols-3` | 三列栅格 | `sm:grid-cols-3`（带断点前缀的已生成） |
| `divide-y` | 行分隔线 | 行上用 `border-b last:border-0` |
| `pl-4` | 4 格左内边距 | `pl-3`（12px，已生成） |
| `w-8` / `w-10` | 32/40px 宽 | `h-8 w-9` 之类已生成的尺寸，或内联 |
| `leading-none` / `leading-tight` | 紧凑行高 | `leading-4` / `leading-5`（已生成） |
| `order-1` | 排序 | 调整 DOM 顺序，不用 flex order |

### 3.2 需要纠正的两条常见误解

- **`space-y-*` 并没有全部缺失**：`space-y-1`、`space-y-1.5`、`space-y-2`、`space-y-2.5`、
  `space-y-3`、`space-y-4`、`space-y-5`、`space-y-6` 都在构建产物里（组件里确实在用）。
  按具体档位查，不要按通配下结论。
- **`max-w-xl` / `max-w-2xl` 存在**，`max-w-md` / `max-w-lg` 不存在。同类名要逐个查。

### 3.3 规则

1. 用之前先在 `frontend/dist/assets/*.css` 里查这个类；查不到就用内联样式或项目已有的类。
2. 查法要精确：`.max-w-md` 会被 `.sm\:max-w-md` 骗过去，必须按「完整选择器 + 边界」判断。
   可直接用下面的判据（CSS 里的类是转义过的，`/`→`\/`、`:`→`\:`）：

   ```bash
   CSS="frontend/dist/assets/$(ls frontend/dist/assets | grep '\.css$' | head -1)"
   # 例：查 max-w-md 是否真的存在（不是 sm:max-w-md）
   grep -o '\.max-w-md[{:, ]' "$CSS" | head -1
   ```

3. 着急时先 `pnpm --dir frontend build` 再查，构建产物是唯一判据。
4. **注释里写类名同样会生成它**：Tailwind 是纯文本扫描，`// 不要用 max-w-md` 这样的注释
   会把 `max-w-md` 生成进 CSS，让下一次检查得出错误结论。要讨论某个类，写在文档里
   （`.agents/`、`docs/` 不在扫描范围），不要写在 `src/**` 的注释里。

---

## 4. 对比度要求

### 4.1 硬性门槛

- 正文与背景 **≥ 4.5:1**；
- 小字（≤ 11px，含 10px 标签）**同样 ≥ 4.5:1**——不因为字小就放宽；
- 大字（≥ 24px 或 ≥ 18.66px 加粗）可放宽到 3:1，但本项目的数值一般不做那么大。

状态色没有变量，必须**成对**写浅色与暗色，不能只写浅色：

| 语义 | 浅色 | 暗色 |
| --- | --- | --- |
| 上涨 / 正常 | `text-emerald-700`（文字）、`text-emerald-600`（数值） | `dark:text-emerald-400` |
| 下跌 / 不可用 | `text-rose-700` / `text-rose-600` | `dark:text-rose-400` |
| 陈旧 / 警示 | `text-amber-700` | `dark:text-amber-400` |
| 说明文字 | `text-muted-foreground` | 同一类（变量自己会换） |

### 4.2 可执行的检查方法

在浏览器控制台（或 Playwright/CDP 的 `evaluate`）里，对目标元素取 `getComputedStyle` 的
`color`，再把它的**有效背景色**算出来（半透明底色要逐层合成到第一个不透明祖先），最后
算 WCAG 相对亮度比：

```js
const parse = (s) => {
  const m = s.match(/rgba?\(([^)]+)\)/);
  const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
  return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
};
const over = (f, b) => ({
  r: f.r * f.a + b.r * (1 - f.a),
  g: f.g * f.a + b.g * (1 - f.a),
  b: f.b * f.a + b.b * (1 - f.a),
  a: 1,
});
const lum = (c) => {
  const f = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const background = (el) => {
  const layers = [];
  let n = el;
  while (n) {
    const bg = parse(getComputedStyle(n).backgroundColor);
    if (bg.a > 0) layers.push(bg);
    if (bg.a === 1) break;
    n = n.parentElement;
  }
  let base = { r: 255, g: 255, b: 255, a: 1 };
  if (layers.length && layers[layers.length - 1].a === 1) base = layers.pop();
  for (let i = layers.length - 1; i >= 0; i -= 1) base = over(layers[i], base);
  return base;
};
const contrastOf = (el) => {
  const fg = parse(getComputedStyle(el).color);
  const bg = background(el);
  return Number(ratio(over(fg, bg), bg).toFixed(2));
};
```

用法：切到暗色（`document.documentElement.classList.add("dark")` 或点右上角主题按钮），对每个
状态标签调 `contrastOf(el)`，把数值记进验收证据。

### 4.3 本单实测基线（暗色，1440px）

| 元素 | 字号 | 前景 / 有效背景 | 对比度 |
| --- | --- | --- | --- |
| 状态徽标「正常」 | 11px | `rgb(52,211,153)` / `rgb(21,37,35)` | 8.24 |
| 上涨数值 | 12px | `rgb(52,211,153)` / `rgb(21,21,25)` | 9.47 |
| 下跌数值 | 12px | `rgb(251,113,133)` / `rgb(21,21,25)` | 6.77 |
| 降级横幅 | 14px | `rgb(251,191,36)` / `rgb(26,21,17)` | 10.85 |
| 卡片元信息行 | 14px | `rgb(159,159,168)` / `rgb(21,21,25)` | 6.94 |
| 卡片脚注 | 11px | `rgb(159,159,168)` / `rgb(21,21,25)` | 6.94 |
| 弹窗提示 / 底部计数 / 候选副标题 | 12px / 12px / 11px | `rgb(159,159,168)` / `rgb(21,21,25)` | 6.94 |

这些数值是后续改动的下限参照：任何一档掉到 4.5 以下就是不达标。

---

## 5. 原型说明

`.agents/spec/design/prototypes/home.html` 是用户确认过的**设计基线，以它为准**：

- 单文件、CSS 内联、直接双击打开即可（本单入库的那份与用户上传的文件 sha256 一致）；
- 里面用 `<style>` 内嵌了一份 Tailwind 构建产物，**:root / .dark 的变量与
  `frontend/src/index.css` 完全一致**，所以原型里的尺寸、间距、字号可以直接映射到工程代码；
- 原型的交互用原生 JS 写在文件末尾（只用于演示，不进生产代码）。

### 5.1 必须换掉的两处

| 项 | 原型 | 实现 |
| --- | --- | --- |
| 置顶持久化 | `localStorage` 的 `trading.homePinned` | 服务端 `settings.display.homepage_pinned`（换浏览器不丢，和项目其它显示设置一致） |
| 颜色 | 51 条规则写死十六进制（如 `#047857`），无暗色 | 成对 `dark:` 变体（如 `text-emerald-700 dark:text-emerald-400`），浅色外观不变 |

原型里写死颜色的标签在暗色下实测只有 3.03:1 与 3.37:1，**不能照抄**；换成成对写法后见 §4.3。

### 5.2 已实现的部分（MKACG-965）

- 首页「关注列表」卡片：标题行（标题 + 状态徽标 + 「编辑」+ 跳转箭头）、元信息行
  （`已选 n/5` · 数据时间 · HTTP 快照/推送覆盖数）、图形空状态（虚线框 + 「选择标的」）、
  五行表格（标的 / 价格 / 日涨跌 / RSI / 趋势）。
- 「编辑首页关注列表」弹窗：搜索框、复选框列表、`已选满 5 个` 提示、`已选 n/5` + 取消/保存；
  草稿是**整份已保存的置顶清单**，已不在自选里的置顶项不显示但会被点名
  （「已不在自选的置顶项不在这里显示，保存后仍会保留：…；要彻底去掉，先把它加回自选再取消置顶」）。
- 置顶清单的写入口径（前后端各一半，改动时必须一起看）：**请求只带弹窗里看得见的勾选项**
  （接口要求元素必须在自选里，否则 400），服务端在写库前把库里那些「已不在自选」的项按
  **原位置**补回去、新选的追加到末尾——于是「什么都不改直接保存」写回的数组与库中逐字节相同，
  加回自选后原样恢复显示。前端过滤器是 `submittablePinned()`（`lib/home-pinned.ts`），
  后端是 `_pinned_for_save()`（`api/routes/settings.py`）。
- 可复用 `Dialog`（§2.3）。

### 5.3 本单与原型的三处已知差异（有意为之）

1. **卡片主体摘要行**不再显示「日线覆盖率」：卡片行现在只是自选的子集，而后端只给整份自选的
   覆盖率；把整体数字挂在局部行上会误导。改为只给 `共 n 个 · 偏多 x · 偏空 y`。
2. **弹窗候选行的副标题**是 `展示名 · 自选分组`，不是原型里的 `分组 · ATR`：首页汇总与自选
   接口都不带 ATR 百分比，不为了对齐原型去编一个数。
3. **元信息行的第三段**是项目既有的 `HTTP 快照` / `N 条记录含推送字段`（真实数据来源标注），
   原型没有这一段。数据来源是项目硬约束，保留。

---

## 6. 范围边界

本文件随 MKACG-965 交付，**只承诺该单实现的东西**。原型里其它区块属于后续的首页九块重构单
（B 单），当前代码里**没有**这些区块，不要按原型以为它们已经存在：

| 原型区块 | 当前状态 |
| --- | --- |
| 市场速览 / 账户状态 / 值得再看一眼 / 市场观察 / 当前持仓 / 账户检查 / 提醒 / 策略与回测 / 系统状态 | 未实现（B 单） |
| 关注列表卡片 + 编辑弹窗 | 已实现（本单） |
| 顶部导航、页面外框、主题切换 | 已实现（既有） |

后续界面任务按以下顺序取用依据：**原型（视觉）→ 本文件（令牌与组件契约）→ `AGENTS.md`
（工程约定）**。原型与本文件冲突时，以本文件为准并在 PR 里写明原因；需要改本文件时，同一个
PR 里改。
