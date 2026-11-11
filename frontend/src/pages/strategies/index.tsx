import { useEffect, useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import {
  createStrategyInstance,
  deleteStrategyInstance,
  fetchStrategies,
  fetchStrategyInstances,
  updateStrategyInstance,
  type StrategyDefinition,
  type StrategyInstance,
  type StrategyInstanceCreateRequest,
} from "../../lib/api";
import { InstanceList } from "./instance-list";
import { StrategyForm } from "./strategy-form";
import { StrategyReplayPanel } from "./strategy-replay";
import { TemplateCatalog } from "./template-catalog";

/**
 * 策略页：模板列表 → 建实例 → 改参 / 启停 → 目标组合回放。
 *
 * 页面只负责取数与组织交互：参数默认值、状态取值、目标组合与净敞口全部来自后端，
 * 前端不做派生计算，也不提供审批入口（阶段推进在审批流程里）。
 */
export default function StrategiesPage() {
  const [templates, setTemplates] = useState<StrategyDefinition[] | null>(null);
  const [instances, setInstances] = useState<StrategyInstance[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([fetchStrategies(), fetchStrategyInstances()])
      .then(([catalog, listing]) => {
        if (!active) return;
        setTemplates(catalog.items);
        setInstances(listing.items);
        setSelectedTemplateId(catalog.items[0]?.strategy_id ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "策略数据加载失败");
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedTemplate =
    templates?.find((item) => item.strategy_id === selectedTemplateId) ?? null;
  const selectedInstance =
    instances.find((item) => item.instance_id === selectedInstanceId) ?? null;

  const run = (action: Promise<void>) => {
    setBusy(true);
    setError(null);
    action
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "操作失败");
      })
      .finally(() => setBusy(false));
  };

  const handleCreate = (payload: StrategyInstanceCreateRequest) =>
    run(
      createStrategyInstance(payload).then((created) => {
        setInstances((current) => [created, ...current]);
        setSelectedInstanceId(created.instance_id);
      }),
    );

  const handleToggle = (instance: StrategyInstance) =>
    run(
      updateStrategyInstance(instance.instance_id, { enabled: !instance.enabled }).then((updated) => {
        setInstances((current) =>
          current.map((item) => (item.instance_id === updated.instance_id ? updated : item)),
        );
      }),
    );

  const handleDelete = (instance: StrategyInstance) => {
    if (!window.confirm(`删除策略实例「${instance.name}」及其回放记录？`)) return;
    run(
      deleteStrategyInstance(instance.instance_id).then(() => {
        setInstances((current) =>
          current.filter((item) => item.instance_id !== instance.instance_id),
        );
        setSelectedInstanceId((current) =>
          current === instance.instance_id ? null : current,
        );
      }),
    );
  };

  return (
    <>
      <PageHeading
        eyebrow="Strategies"
        title="策略"
        description="组合模板是只读定义，实例是用户配置：参数、标的与启停都在这里维护。回放按历史行情重算目标组合，同一区间两次回放得到同一份结果。"
      />

      {error ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {!templates ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-6">
          <TemplateCatalog
            templates={templates}
            selectedId={selectedTemplateId}
            onSelect={setSelectedTemplateId}
          />

          {selectedTemplate ? (
            <StrategyForm
              key={selectedTemplate.strategy_id}
              template={selectedTemplate}
              busy={busy}
              onSubmit={handleCreate}
            />
          ) : null}

          <InstanceList
            instances={instances}
            selectedId={selectedInstanceId}
            busy={busy}
            onReplay={(instance) => setSelectedInstanceId(instance.instance_id)}
            onToggle={handleToggle}
            onDelete={handleDelete}
          />

          {selectedInstance ? (
            <StrategyReplayPanel
              key={selectedInstance.instance_id}
              instance={selectedInstance}
            />
          ) : null}
        </div>
      )}
    </>
  );
}
