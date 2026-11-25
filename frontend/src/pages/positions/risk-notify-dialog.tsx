import { useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import {
  changedRules,
  draftFromConfig,
  NOTIFY_CHANNELS,
  ruleCopy,
  saveRiskNotifyConfig,
  toggleChannel,
  type NotifyDraft,
  type RiskNotifyRule,
} from "../../lib/risk-notify";
import { cn } from "../../lib/utils";

export type RiskNotifyDialogProps = {
  open: boolean;
  rules: readonly RiskNotifyRule[];
  onClose: () => void;
  onSaved: (rules: RiskNotifyRule[]) => void;
};

/**
 * 「风控通知设置」弹窗：五条规则的开关、阈值与通知渠道。
 *
 * 保存只写通知配置——权益、名义、保证金占用都来自账户快照，与这里无关。关掉一条
 * 规则后后端不再评估它，因此页面的命中条会跟着变，这是同一份计算结果，不是两套。
 */
export function RiskNotifyDialog({ open, rules, onClose, onSaved }: RiskNotifyDialogProps) {
  const [draft, setDraft] = useState<Record<string, NotifyDraft>>(() => draftFromConfig(rules));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 每次打开都以最新配置为草稿：上一次没保存的临时改动不该留到下一次。
  useEffect(() => {
    if (open) {
      setDraft(draftFromConfig(rules));
      setError(null);
    }
  }, [open, rules]);

  const patch = (ruleId: string, next: Partial<NotifyDraft>) => {
    setDraft((current) => ({
      ...current,
      [ruleId]: { ...current[ruleId], ...next } as NotifyDraft,
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await saveRiskNotifyConfig(changedRules(rules, draft));
      onSaved(updated.rules);
      onClose();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="风控通知设置"
      description="规则命中后按选中的渠道通知；关掉的规则不再评估，也不影响持仓页上的数字。"
      maxWidth="36rem"
      onClose={onClose}
      footer={
        <>
          <span className="text-[11px] text-muted-foreground">配置只影响通知，不改变持仓页数字</span>
          <div className="flex items-center gap-2">
            {error === null ? null : (
              <span className="text-[11px] text-destructive" role="alert">
                {error}
              </span>
            )}
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={onClose}>
              取消
            </Button>
            <Button size="sm" disabled={saving} onClick={() => void handleSave()}>
              {saving ? "保存中…" : "保存"}
            </Button>
          </div>
        </>
      }
    >
      <div className="px-6 pb-2" style={{ maxHeight: "26rem", overflowY: "auto" }}>
        <div className="space-y-2.5">
          {rules.map((rule) => {
            const copy = ruleCopy(rule.rule_id);
            const current = draft[rule.rule_id] ?? {
              enabled: rule.enabled,
              channels: [...rule.channels],
              threshold: rule.threshold ?? "",
            };
            return (
              <div key={rule.rule_id} className="rounded-md border px-3 py-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{copy.title}</p>
                    <p className="text-[11px] text-muted-foreground">{copy.description}</p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={current.enabled}
                    aria-label={`${copy.title}开关`}
                    onClick={() => patch(rule.rule_id, { enabled: !current.enabled })}
                    className={cn(
                      "relative h-4 w-8 shrink-0 rounded-full transition-colors",
                      current.enabled ? "bg-emerald-600" : "bg-muted-foreground/40",
                    )}
                  >
                    <span
                      className={cn(
                        "absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform",
                        current.enabled ? "translate-x-4" : "translate-x-0.5",
                      )}
                    />
                  </button>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  {copy.unit === null ? null : (
                    <>
                      <span>{copy.comparator}</span>
                      <input
                        className="h-7 w-16 rounded border border-input bg-transparent px-2 text-xs"
                        value={current.threshold}
                        aria-label={`${copy.title}阈值`}
                        onChange={(event) =>
                          patch(rule.rule_id, { threshold: event.target.value })
                        }
                      />
                      <span>{copy.unit}</span>
                    </>
                  )}
                  <span className="ml-auto flex flex-wrap items-center gap-2">
                    {NOTIFY_CHANNELS.map((channel) => (
                      <label key={channel.key} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          checked={current.channels.includes(channel.key)}
                          onChange={() =>
                            patch(rule.rule_id, {
                              channels: toggleChannel(current.channels, channel.key),
                            })
                          }
                        />
                        {channel.label}
                      </label>
                    ))}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Dialog>
  );
}

export default RiskNotifyDialog;
