import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

/** 手动持仓占位：具体创建、买卖与流水由 S2-2 交付。 */
export default function ManualSection() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>手动持仓</CardTitle>
        <CardDescription>手动持仓由 S2-2 交付。</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          本区域暂不提供创建、买卖或流水查看，也不展示任何演示数值。
        </p>
      </CardContent>
    </Card>
  );
}
