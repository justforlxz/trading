/**
 * 可复用弹窗：全屏遮罩 + 居中面板。
 *
 * 无障碍契约（其它页面复用它时不必再各写一份）：
 * - 面板是 `role="dialog"` + `aria-modal="true"` + `aria-labelledby`，标题由组件生成 id；
 * - Esc 关闭、点遮罩关闭，面板内部的点击与按键不关闭；
 * - 打开时焦点移进面板里的第一个可聚焦元素，关闭后回到打开前的元素（触发按钮）。
 *
 * 不引第三方依赖：项目只装了 Radix 的 Slot，没有弹窗原语。
 *
 * 遮罩透明度、面板宽度与列表高度用内联样式而不是 Tailwind 类：构建产物是按需生成
 * 的，只有源码里真的用到的类才会进 CSS，写一个没有生成的类名不会报错、只会静默
 * 失效。`docs` 与 `.agents` 里的说明文字同样会被 Tailwind 的文本扫描当成用法，
 * 所以在注释里写类名会把它凭空生成出来——要判断某个类存不存在，看构建产物，别看
 * 注释。
 */

import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from "react";

import { cn } from "../../lib/utils";

export type DialogProps = {
  open: boolean;
  title: string;
  description?: ReactNode;
  /** 底部操作区，通常是取消 / 确认两个按钮；左对齐的内容由调用方自己放进 children 之外。 */
  footer?: ReactNode;
  className?: string;
  onClose: () => void;
  children: ReactNode;
};

const FOCUSABLE = "input:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";

export function Dialog({
  open,
  title,
  description,
  footer,
  className,
  onClose,
  children,
}: DialogProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  // 回调只存进 ref：父组件每次渲染都会给出新函数，若把它放进依赖，弹窗会在父组件
  // 重渲染时重复执行「焦点移入 / 恢复」，用户正在输入时焦点会被抢走。
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const target = panel?.querySelector<HTMLElement>(FOCUSABLE) ?? panel;
    target?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeRef.current();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      trigger?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const closeOnOverlay = (event: MouseEvent<HTMLDivElement>) => {
    // 只认「按下点就在遮罩上」：从面板里按下、拖到遮罩上松开不算点击遮罩。
    if (event.target !== event.currentTarget) return;
    // 必须拦掉按下事件的默认行为：遮罩不可聚焦，浏览器的默认动作会把焦点移回 body，
    // 刚好盖掉上面「关闭时把焦点还给触发按钮」的恢复，键盘用户就此丢掉位置。
    event.preventDefault();
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.5)" }}
      onMouseDown={closeOnOverlay}
      data-dialog-overlay=""
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "flex w-full flex-col rounded-lg border bg-card text-card-foreground shadow-sm outline-none",
          className,
        )}
        style={{ maxWidth: "28rem" }}
      >
        <div className="flex flex-col gap-1.5 p-6">
          <h3 id={titleId} className="text-base font-semibold tracking-tight">
            {title}
          </h3>
          {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
        </div>
        {children}
        {footer ? (
          <div className="flex items-center justify-between gap-3 p-6 pt-4">{footer}</div>
        ) : null}
      </div>
    </div>
  );
}
