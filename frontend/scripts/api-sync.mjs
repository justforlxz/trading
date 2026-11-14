#!/usr/bin/env node
/**
 * 从 `backend/contracts/openapi.json` 同步前端的三份生成物：
 *
 *   1. `src/api/types.ts`       —— openapi-typescript 生成的前端类型
 *   2. `src/mocks/fixtures/**`  —— 每个 2xx 响应的 example（MSW 的唯一数据来源）
 *   3. `src/mocks/handlers.ts`  —— 与端点一一对应的 MSW handler
 *
 * 校验（任一不满足即非 0 退出）：
 *   - 每个 path 都出现在生成的 types.ts 里；
 *   - 每个 2xx JSON 响应都有 example（否则 MSW 无从取值）；
 *   - 九个业务域都至少生成了一条 handler。
 *
 * 生成物禁止手改：契约只改后端 schema，再跑一次本脚本。
 * 用法：`pnpm --dir frontend api:sync`（或 `make api`）。
 */

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(SCRIPT_DIR, "..");
const CONTRACT_PATH = path.resolve(FRONTEND_DIR, "../backend/contracts/openapi.json");
const TYPES_PATH = path.join(FRONTEND_DIR, "src/api/types.ts");
const MOCKS_DIR = path.join(FRONTEND_DIR, "src/mocks");
const FIXTURES_DIR = path.join(MOCKS_DIR, "fixtures");
const HANDLERS_PATH = path.join(MOCKS_DIR, "handlers.ts");

const HTTP_METHODS = ["get", "post", "put", "patch", "delete"];
const DOMAINS = [
  "watchlist",
  "indicators",
  "strategy",
  "backtest",
  "settings",
  "dashboard",
  "correlation",
  "opportunity",
  "approval",
];

/** v6 删除的旧页面所属业务域，不再生成前端 MSW handler 与 fixture。 */
const REMOVED_DOMAINS = new Set(["trades", "relations", "portfolio"]);

const contract = JSON.parse(await readFile(CONTRACT_PATH, "utf8"));

/** `$ref` → 组件里真实的 schema 对象。 */
function dereference(schema) {
  if (!schema?.$ref) return schema;
  const name = schema.$ref.split("/").pop();
  return contract.components.schemas[name];
}

/** 取响应模型的第一个 example；没有 example 直接失败（契约不合格）。 */
function exampleOf(schema, label) {
  const resolved = dereference(schema);
  const examples = resolved?.examples ?? (resolved?.example === undefined ? [] : [resolved.example]);
  if (examples.length === 0) {
    throw new Error(`${label} 的响应模型没有 example，无法生成 fixture`);
  }
  return examples[0];
}

/** 每个域目录下的 fixture 文件名：`get-watchlist-inst_id-related`。 */
function fixtureName(method, route) {
  const slug = route
    .replace(/^\/api\//, "")
    .replace(/[/{}]/g, "-")
    .replace(/-+/g, "-")
    .replace(/-$/, "");
  return `${method}-${slug}`;
}

function identifierOf(fileName) {
  const parts = fileName.split(/[-_]/).filter(Boolean);
  return parts[0] + parts.slice(1).map((part) => part[0].toUpperCase() + part.slice(1)).join("");
}

/** OpenAPI 的 `{param}` → MSW 的 `:param`；`*` 前缀让 handler 与来源 origin 无关。 */
function mswPath(route) {
  return `*${route.replace(/\{([^}]+)\}/g, ":$1")}`;
}

const generated = [];
for (const [route, item] of Object.entries(contract.paths)) {
  for (const method of HTTP_METHODS) {
    const operation = item[method];
    if (!operation) continue;

    const domain = operation.tags?.[0];
    if (!domain) throw new Error(`${method.toUpperCase()} ${route} 缺少 tags，无法归域`);
    if (REMOVED_DOMAINS.has(domain)) continue;

    const statuses = Object.keys(operation.responses ?? {})
      .filter((status) => status.startsWith("2"))
      .sort();
    if (statuses.length === 0) throw new Error(`${method.toUpperCase()} ${route} 没有 2xx 响应`);
    const status = Number(statuses[0]);
    const response = operation.responses[statuses[0]];
    const schema = response.content?.["application/json"]?.schema;

    let fixture = null;
    if (schema) {
      const label = `${method.toUpperCase()} ${route} (${statuses[0]})`;
      fixture = { name: fixtureName(method, route), domain, data: exampleOf(schema, label) };
    }
    generated.push({ route, method, status, domain, fixture });
  }
}

// 1. 类型
const ast = await openapiTS(contract);
const typeSource =
  "// 由 `pnpm --dir frontend api:sync` 生成，勿手改。契约源：backend/contracts/openapi.json\n" +
  astToString(ast);

// 2. fixture
await rm(FIXTURES_DIR, { recursive: true, force: true });
for (const entry of generated) {
  if (!entry.fixture) continue;
  const dir = path.join(FIXTURES_DIR, entry.fixture.domain);
  await mkdir(dir, { recursive: true });
  await writeFile(
    path.join(dir, `${entry.fixture.name}.json`),
    `${JSON.stringify(entry.fixture.data, null, 2)}\n`,
    "utf8",
  );
}

// 3. handler
const imports = [];
const handlers = [];
for (const entry of generated) {
  const call = `http.${entry.method}("${mswPath(entry.route)}", () => `;
  if (entry.fixture) {
    const id = identifierOf(entry.fixture.name);
    imports.push(
      `import ${id} from "./fixtures/${entry.fixture.domain}/${entry.fixture.name}.json";`,
    );
    const init = entry.status === 200 ? "" : `, { status: ${entry.status} }`;
    handlers.push(`  ${call}HttpResponse.json(${id}${init})),`);
  } else {
    handlers.push(`  ${call}new HttpResponse(null, { status: ${entry.status} })),`);
  }
}

const handlerSource = [
  "// 由 `pnpm --dir frontend api:sync` 生成，勿手改。",
  "// 数据一律来自 backend/contracts/openapi.json 的 example，handler 里不写业务常量。",
  'import { HttpResponse, http } from "msw";',
  "",
  ...imports,
  "",
  "export const handlers = [",
  ...handlers,
  "];",
  "",
].join("\n");

await mkdir(path.dirname(TYPES_PATH), { recursive: true });
await writeFile(TYPES_PATH, typeSource, "utf8");
await writeFile(HANDLERS_PATH, handlerSource, "utf8");

// 4. 校验
const typeText = await readFile(TYPES_PATH, "utf8");
const missingPaths = Object.keys(contract.paths).filter((route) => !typeText.includes(`"${route}"`));
if (missingPaths.length > 0) {
  throw new Error(`types.ts 缺少以下 path：${missingPaths.join(", ")}`);
}

const coveredDomains = new Set(generated.map((entry) => entry.domain));
const missingDomains = DOMAINS.filter((domain) => !coveredDomains.has(domain));
if (missingDomains.length > 0) {
  throw new Error(`契约缺少业务域：${missingDomains.join(", ")}`);
}

const fixtureCount = generated.filter((entry) => entry.fixture).length;
console.log(
  `api:sync 完成 —— paths ${Object.keys(contract.paths).length} / operations ${generated.length} / ` +
    `fixtures ${fixtureCount} / domains ${coveredDomains.size}`,
);
