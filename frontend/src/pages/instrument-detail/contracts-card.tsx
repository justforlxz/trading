import { Link } from "react-router-dom";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { InstrumentDetailResponse } from "../../lib/api";
import { instTypeLabel, signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";

const NOT_PROVIDED = "未提供";

type InstrumentInfo = InstrumentDetailResponse["instrument"];
type SiblingQuote = InstrumentDetailResponse["siblings"][number];

type InstrumentContractsCardProps = {
  instrument: InstrumentInfo;
  siblings: SiblingQuote[] | null;
  siblingsLoading?: boolean;
  siblingsError?: string | null;
};

/** 详情页的合约元数据与同一产品另一形态；字段原样来自后端。 */
export function InstrumentContractsCard({
  instrument,
  siblings,
  siblingsLoading = false,
  siblingsError = null,
}: InstrumentContractsCardProps) {
  const fields = [
    { label: "最小价格变动 tick_size", value: instrument.tick_size },
    { label: "下单数量精度 lot_size", value: instrument.lot_size },
    { label: "最小下单量 min_order_size", value: instrument.min_order_size },
    { label: "最大杠杆 max_leverage", value: instrument.max_leverage },
  ];

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>合约元数据</CardTitle>
          <CardDescription>
            字段与取值原样来自标的接口，不做前端换算；后端没有同步的字段写「未提供」。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {fields.map((field) => (
              <div key={field.label} className="grid gap-1">
                <dt className="text-xs text-muted-foreground">{field.label}</dt>
                <dd className="font-mono text-sm tabular-nums">
                  {field.value ?? NOT_PROVIDED}
                </dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>同一产品的另一形态</CardTitle>
          <CardDescription>
            现货与永续的报价和交易规则分别维护；价差由后端按两条腿的最近日线收盘价计算。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {siblingsError ? (
            <p className="mb-3 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
              {siblingsError}
            </p>
          ) : null}
          {siblings && siblings.length > 0 ? (
            <ul className="divide-y">
              {siblings.map((sibling) => (
                <li key={sibling.inst_id}>
                  <Link
                    to={`/watchlist/${sibling.inst_id}`}
                    className="flex flex-wrap items-center gap-3 py-3 text-sm underline-offset-4 hover:underline"
                  >
                    <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                      {instTypeLabel(sibling.inst_type)}
                    </span>
                    <span className="font-mono">{sibling.inst_id}</span>
                    <span className="ml-auto font-mono tabular-nums">{sibling.last_price}</span>
                    <span
                      className={cn(
                        "font-mono text-xs tabular-nums",
                        signedTone(sibling.price_spread_pct),
                      )}
                    >
                      价差 {signedValue(sibling.price_spread_pct)}%
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : siblingsLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (
            <p className="text-sm text-muted-foreground">
              同产品另一形态的报价暂不可用，价差未提供。
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
