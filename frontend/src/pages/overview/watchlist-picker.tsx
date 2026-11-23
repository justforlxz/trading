/**
 * 首页「关注列表」的置顶编辑弹窗。
 *
 * 弹窗里只有一件事：从当前自选里挑最多 5 个标的，按勾选顺序置顶到首页卡片。
 * 草稿存在本地，点「保存」才写服务端；取消、Esc、点遮罩都只丢弃草稿。
 *
 * 草稿的初始值是**整份已保存的置顶清单**（含那些已经不在自选里、因此不显示的项）：
 * 弹窗只列当前自选，但保存时不能把看不见的项一起丢掉——用户只是打开弹窗加一个标的，
 * 不该让「从自选删掉的置顶项」就此永久消失（AC6 承诺的「加回自选后恢复显示」会失效）。
 * 这类项会在列表下方单独点名，让「已选 n/5」的计数不至于莫名其妙。
 */

import { useState } from "react";

import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import {
  isPinnedFull,
  pinnedCountText,
  submittablePinned,
  togglePinned,
  type PinnedCandidate,
} from "../../lib/home-pinned";
import { cn } from "../../lib/utils";

export type WatchlistPickerProps = {
  open: boolean;
  /** 当前自选的完整清单：弹窗里可勾的全部候选。 */
  items: readonly PinnedCandidate[];
  /** 已保存的置顶清单（服务端值，可能含已从自选删掉的标识）。 */
  pinned: readonly string[];
  /** 保存成功后调用：由调用方关闭弹窗。保存失败时本组件自己显错，不关闭。 */
  onClose: () => void;
  onSave: (next: string[]) => Promise<void>;
};

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "保存置顶失败";
}

export function WatchlistPicker({ open, items, pinned, onClose, onSave }: WatchlistPickerProps) {
  const seeded = [...pinned];
  const [draft, setDraft] = useState<string[]>(seeded);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);

  // 只在「关闭 → 打开」这一刻重置草稿：行情推送会不断替换 `items` 数组，若跟着
  // 每次变化重置，用户正在勾选时草稿会被悄悄打回原样。用渲染期的状态调整而不是
  // effect，弹窗第一帧就带着正确的勾选，不会闪一下空清单。
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setDraft(seeded);
      setQuery("");
      setError(null);
      setSaving(false);
    }
  }

  const full = isPinnedFull(draft);
  // 置顶清单里、但当前自选里已经没有的项：它们不在这里显示，保存时仍会原样写回。
  const hiddenPinned = draft.filter(
    (instId) => !items.some((item) => item.inst_id === instId),
  );
  // 没有候选就不允许保存：候选还没读到时草稿是空的，点保存会把库里已有的置顶清单清空。
  const canSave = items.length > 0;
  const keyword = query.trim().toLowerCase();
  const visible = keyword
    ? items.filter(
        (item) =>
          item.inst_id.toLowerCase().includes(keyword) ||
          item.display_symbol.toLowerCase().includes(keyword) ||
          item.detail.toLowerCase().includes(keyword),
      )
    : items;

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      // 只提交弹窗里看得见的勾选项：看不见的那些由服务端按原位置补回。
      await onSave(submittablePinned(draft, items));
      onClose();
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="编辑首页关注列表"
      description="从自选里选择，最多 5 个"
      onClose={onClose}
      footer={
        <>
          <span className="text-xs text-muted-foreground">{pinnedCountText(draft.length)}</span>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={onClose}
              disabled={saving}
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void submit()}
              disabled={saving || !canSave}
            >
              {saving ? "保存中…" : "保存"}
            </Button>
          </div>
        </>
      }
    >
      <div className="px-6">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索标的或分组"
          aria-label="搜索标的"
          className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <ul
          className="mt-3 flex flex-col gap-1 overflow-y-auto"
          style={{ maxHeight: "20rem" }}
          aria-label="自选标的"
        >
          {visible.length === 0 ? (
            <li className="px-2 py-6 text-center text-xs text-muted-foreground">
              {items.length === 0 ? "自选中还没有标的" : "没有匹配的标的"}
            </li>
          ) : (
            visible.map((item) => {
              const checked = draft.includes(item.inst_id);
              const disabled = !checked && full;
              return (
                <li key={item.inst_id}>
                  <label
                    className={cn(
                      "flex items-center gap-3 rounded-md px-2 py-2",
                      disabled ? "opacity-50" : "cursor-pointer hover:bg-accent",
                    )}
                    title={disabled ? "最多选择 5 个标的" : undefined}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0"
                      style={{ accentColor: "hsl(var(--primary))" }}
                      checked={checked}
                      disabled={disabled}
                      onChange={() => setDraft(togglePinned(draft, item.inst_id))}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-xs">{item.inst_id}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {item.detail ? `${item.display_symbol} · ${item.detail}` : item.display_symbol}
                      </span>
                    </span>
                    <span className="shrink-0 text-right font-mono text-xs tabular-nums">
                      {item.last_price ?? "—"}
                    </span>
                  </label>
                </li>
              );
            })
          )}
        </ul>
        {full ? (
          <p className="mt-2 text-xs text-muted-foreground">已选满 5 个，取消一个才能再选</p>
        ) : null}
        {hiddenPinned.length > 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">
            已不在自选的置顶项不在这里显示，保存后仍会保留：{hiddenPinned.join("、")}
            。要彻底去掉，先把它加回自选再取消置顶
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
