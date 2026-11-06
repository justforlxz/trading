"""标的分类：把 OKX 的合约符号映射到 `asset_class` / `exchange`。

OKX 只给 `instCategory`（1=Crypto / 3=Stocks / 4=Commodities），不区分美股正股、
ETF、海外股票与私营公司，也不给交易所。这里用**人工维护表**补齐：

- 表是按 2026-11-06 抓取的 230 个 `instCategory=3` 符号逐一核对的静态清单；
- 未命中维护表的符号（未来新增标的）标记 `unclassified`，**不猜测**类别；
- `exchange` 只在能确认时填写，否则留空（`NULL`），绝不臆造。

维护方式见 `docs/market-data.md`「标的分类」。
"""

from dataclasses import dataclass

ASSET_CLASSES: tuple[str, ...] = (
    "us_equity",
    "foreign_equity",
    "etf",
    "index",
    "private_company",
    "commodity",
    "crypto",
    "unclassified",
)

# 私营公司（无公开交易所）：exchange 必须为空。
PRIVATE_COMPANIES: frozenset[str] = frozenset(
    {
        "ANTHROPIC",
        "CXMT",
        "GIGADEV",
        "MINIMAX",
        "MOONSHOT",
        "OPENAI",
        "OURA",
        "SHEIN",
        "UNITREE",
        "ZHIPU",
        "ZHONGJI",
    }
)

# 指数合约（OKX 自建的指数标的，不是可交易的股票）。
INDEX_SYMBOLS: frozenset[str] = frozenset({"JP225", "KR200", "US100", "US500"})

# 美国上市 ETF（含 2x 杠杆 ETF）。
ETF_SYMBOLS: frozenset[str] = frozenset(
    {
        "DRAM",
        "EIDO",
        "EWJ",
        "EWT",
        "EWY",
        "EWZ",
        "EWZS",
        "IWM",
        "KORU",
        "MSTU",
        "MVLL",
        "NVDL",
        "QQQ",
        "SHLD",
        "SMH",
        "SOXL",
        "SOXS",
        "SPY",
        "SQQQ",
        "TLT",
        "TMF",
        "TQQQ",
        "TSLL",
        "URNM",
        "USO",
        "UVXY",
        "XBI",
        "XLE",
        "XLV",
    }
)

# 海外正股 / ADR：符号 → 上市交易所。
FOREIGN_EQUITIES: dict[str, str] = {
    "ARM": "XNAS",
    "ASML": "XNAS",
    "BIDU": "XNAS",
    "HANMI": "XKRX",
    "HYUNDAI": "XKRX",
    "KIOXIA": "XTKS",
    "LGELECTRONICS": "XKRX",
    "MELI": "XNAS",
    "MURATA": "XTKS",
    "NAVER": "XKRX",
    "NOK": "XNYS",
    "NVO": "XNYS",
    "PDD": "XNAS",
    "POPMART": "XHKG",
    "SAMSUNG": "XKRX",
    "SHOP": "XNYS",
    "SKHYNIX": "XKRX",
    "SOFTBANK": "XTKS",
    "SONY": "XTKS",
    "TSM": "XNYS",
    "UMC": "XNYS",
    "WUXIBIO": "XHKG",
    "XIAOMI": "XHKG",
}

# 2026-11-06 抓取批次中无法确认归属的符号：保持 unclassified，待人工复核。
UNCLASSIFIED_SYMBOLS: frozenset[str] = frozenset(
    {
        "BOT",
        "INFQ",
        "INTW",
        "LYTE",
        "MUU",
        "PENG",
        "PURR",
        "QNT",
        "RAM",
        "SECZ",
        "SHAZ",
        "SKDD",
        "SKHY",
        "SKUU",
        "SNXX",
        "SPCH",
        "SPCX",
    }
)

# 已确认的美股正股（含 2x 杠杆 ETP 清单），未列入者不臆造为美股。
US_EQUITIES: frozenset[str] = frozenset(
    {
        "AAOI",
        "AAPL",
        "ABBV",
        "ACN",
        "ADBE",
        "ADI",
        "AEHR",
        "ALAB",
        "AMAT",
        "AMC",
        "AMD",
        "AMGN",
        "AMZN",
        "APLD",
        "APP",
        "ASTS",
        "AVGO",
        "AXTI",
        "BAC",
        "BB",
        "BE",
        "BMNR",
        "BRKB",
        "BSP",
        "BWET",
        "BX",
        "CBRS",
        "CEG",
        "CGNX",
        "CIEN",
        "COHR",
        "COIN",
        "COST",
        "CRCL",
        "CRDO",
        "CRM",
        "CRML",
        "CRWD",
        "CRWV",
        "CSCO",
        "CSOPSAMSUNG2L",
        "CSOPSKHYNIX2L",
        "CVNA",
        "CYPH",
        "DDOG",
        "DELL",
        "DKNG",
        "FLEX",
        "FLNC",
        "FLY",
        "FWDI",
        "GE",
        "GEV",
        "GILD",
        "GLW",
        "GME",
        "GOOGL",
        "GPRO",
        "GS",
        "GTLB",
        "HIMS",
        "HOOD",
        "HPE",
        "HUT",
        "IBKR",
        "IBM",
        "INTC",
        "IONQ",
        "IREN",
        "ISRG",
        "JNJ",
        "JPM",
        "KLAC",
        "KO",
        "KSTR",
        "LITE",
        "LLY",
        "LRCX",
        "LUNR",
        "MARA",
        "MCD",
        "META",
        "MP",
        "MPWR",
        "MRK",
        "MRNA",
        "MRVL",
        "MSFT",
        "MSTR",
        "MU",
        "NBIS",
        "NET",
        "NFLX",
        "NKE",
        "NOW",
        "NVDA",
        "OKLO",
        "OKTA",
        "ON",
        "ONDS",
        "ORCL",
        "OSCR",
        "OUST",
        "OXY",
        "PANW",
        "PEP",
        "PFE",
        "PLTR",
        "POET",
        "PYPL",
        "QCOM",
        "RDDT",
        "RDW",
        "RIOT",
        "RIVN",
        "RKLB",
        "ROK",
        "RUM",
        "SIMO",
        "SMCI",
        "SMR",
        "SNDK",
        "SNOW",
        "SOFI",
        "STRC",
        "TEAM",
        "TEM",
        "TER",
        "TSEM",
        "TSLA",
        "TTMI",
        "TTWO",
        "TWLO",
        "TWST",
        "TXN",
        "UNH",
        "USAR",
        "V",
        "VICR",
        "VRT",
        "VST",
        "WDC",
        "WEN",
        "WMT",
        "XOM",
        "ZM",
    }
)

# 已确认的美股上市交易所；其余美股正股 exchange 留空（未核实不填）。
US_EXCHANGES: dict[str, str] = {
    # Nasdaq
    "AAOI": "XNAS",
    "AAPL": "XNAS",
    "ADBE": "XNAS",
    "ADI": "XNAS",
    "ALAB": "XNAS",
    "AMAT": "XNAS",
    "AMD": "XNAS",
    "AMGN": "XNAS",
    "AMZN": "XNAS",
    "APP": "XNAS",
    "AVGO": "XNAS",
    "AXTI": "XNAS",
    "COIN": "XNAS",
    "COST": "XNAS",
    "CRDO": "XNAS",
    "CRM": "XNAS",
    "CRWD": "XNAS",
    "CSCO": "XNAS",
    "DDOG": "XNAS",
    "GILD": "XNAS",
    "GTLB": "XNAS",
    "HOOD": "XNAS",
    "INTC": "XNAS",
    "ISRG": "XNAS",
    "KLAC": "XNAS",
    "LRCX": "XNAS",
    "META": "XNAS",
    "MRNA": "XNAS",
    "MRVL": "XNAS",
    "MSFT": "XNAS",
    "MSTR": "XNAS",
    "MU": "XNAS",
    "NFLX": "XNAS",
    "NVDA": "XNAS",
    "OKTA": "XNAS",
    "ON": "XNAS",
    "PANW": "XNAS",
    "PLTR": "XNAS",
    "PYPL": "XNAS",
    "QCOM": "XNAS",
    "SMCI": "XNAS",
    "SNDK": "XNAS",
    "SOFI": "XNAS",
    "TEAM": "XNAS",
    "TSLA": "XNAS",
    "TTWO": "XNAS",
    "TXN": "XNAS",
    "WDC": "XNAS",
    "ZM": "XNAS",
    # NYSE
    "ABBV": "XNYS",
    "DELL": "XNYS",
    "HPE": "XNYS",
    "NET": "XNYS",
    "SNOW": "XNYS",
    "ACN": "XNYS",
    "BAC": "XNYS",
    "BRKB": "XNYS",
    "BX": "XNYS",
    "CEG": "XNYS",
    "GE": "XNYS",
    "GEV": "XNYS",
    "GS": "XNYS",
    "IBM": "XNYS",
    "JNJ": "XNYS",
    "JPM": "XNYS",
    "KO": "XNYS",
    "LLY": "XNYS",
    "MCD": "XNYS",
    "MRK": "XNYS",
    "NKE": "XNYS",
    "ORCL": "XNYS",
    "OXY": "XNYS",
    "PEP": "XNYS",
    "PFE": "XNYS",
    "UNH": "XNYS",
    "V": "XNYS",
    "VST": "XNYS",
    "WMT": "XNYS",
    "XOM": "XNYS",
}

ETF_EXCHANGE = "NYSE_ARCA"

# 相关性分析只认可「美股正股 + ETF」（P1 决策 A 第 ② 条）。
CORRELATION_ASSET_CLASSES: frozenset[str] = frozenset({"us_equity", "etf"})


@dataclass(frozen=True, slots=True)
class Classification:
    asset_class: str
    exchange: str | None


def classify(symbol: str) -> Classification:
    """按维护表给标的打类别；未知符号返回 `unclassified`。"""

    key = symbol.strip().upper()
    if key in PRIVATE_COMPANIES:
        return Classification("private_company", None)
    if key in INDEX_SYMBOLS:
        return Classification("index", None)
    if key in ETF_SYMBOLS:
        return Classification("etf", ETF_EXCHANGE)
    if key in FOREIGN_EQUITIES:
        return Classification("foreign_equity", FOREIGN_EQUITIES[key])
    if key in US_EQUITIES:
        return Classification("us_equity", US_EXCHANGES.get(key))
    return Classification("unclassified", None)


def participates_in_correlation(asset_class: str) -> bool:
    """该类别是否参与真实相关性分析（其余仅入库，不参与）。"""

    return asset_class in CORRELATION_ASSET_CLASSES
