import { PageHeading, PendingPanel } from "../../components/layout/page-parts";

/**
 * 策略页占位。v6 的策略与版本接口已由 B6 提供，页面由 S4-2 交付；
 * 旧的模板目录与实例管理页面已随旧接口一起删除。
 */
export default function StrategiesPage() {
  return (
    <>
      <PageHeading
        eyebrow="Strategies"
        title="策略"
        description="用户策略、不可变版本、规则 JSON 与标的关联由 B6 的后端接口提供，页面在 S4-2 交付。"
      />
      <PendingPanel
        stage="S4-2"
        title="策略页计划交付"
        items={[
          "策略列表：名称、类别、状态、当前版本、标的数量与最近回测摘要。",
          "策略详情：版本目录、规则 JSON、参数、仓位规则与标的集合。",
          "新建策略草稿：创建策略与第一个草稿版本，新版本不复写旧版本。",
          "标的关联：按策略版本替换标的集合，旧版本保持不可修改。",
        ]}
      />
    </>
  );
}
