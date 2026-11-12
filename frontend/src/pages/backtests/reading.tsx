import { signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";

export type Reading = {
  label: string;
  value: string;
  /** 带正负号的盈亏类数值：按契约原值染色并补 `+`。 */
  tone?: boolean;
};

/** 一个只读读数：标签在上、数值在下。数值原样呈现，不做换算。 */
export function ReadingItem({ reading }: { reading: Reading }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{reading.label}</dt>
      <dd
        className={cn(
          "font-mono text-sm tabular-nums",
          reading.tone && signedTone(reading.value),
        )}
      >
        {reading.tone ? signedValue(reading.value) : reading.value}
      </dd>
    </div>
  );
}

export function ReadingGrid({
  readings,
  className = "sm:grid-cols-3 lg:grid-cols-6",
}: {
  readings: Reading[];
  className?: string;
}) {
  return (
    <dl className={cn("grid gap-4", className)}>
      {readings.map((reading) => (
        <ReadingItem key={reading.label} reading={reading} />
      ))}
    </dl>
  );
}
