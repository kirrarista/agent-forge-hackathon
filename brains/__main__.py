"""python -m brains [listings.json sold.json]   → prints comps, verdicts and ranked output.
Defaults: demo_data/ if Julius saved it, else tests/brains/fixture.json. BRAINS_LLM=0 for rules-only."""
import asyncio
import json
import sys
from pathlib import Path

import brains

ROOT = Path(__file__).resolve().parent.parent


def load():
    if len(sys.argv) == 3:
        return json.loads(Path(sys.argv[1]).read_text()), json.loads(Path(sys.argv[2]).read_text())
    demo = ROOT / "demo_data"
    if (demo / "listings.json").exists() and (demo / "sold.json").exists():
        return json.loads((demo / "listings.json").read_text()), json.loads((demo / "sold.json").read_text())
    d = json.loads((ROOT / "tests/brains/fixture.json").read_text())
    return d["listings"], d["sold"]


async def main():
    listings, sold = load()
    comps = brains.comps(sold)
    print("== comps"); [print(" ", c) for c in comps]
    verdicts = await brains.evaluate(listings, comps)
    ranked = await brains.rank(listings, verdicts)
    print("\n== top")
    for i, t in enumerate(ranked["top"], 1):
        l, v = t["listing"], t["verdict"]
        print(f"{i}. ¥{l['price_jpy']:,} {l['marketplace']} · score {v['deal_score']} · {v['risk']} · offer ¥{v['suggested_offer_jpy']:,}")
        print("   ✅", "; ".join(v["pros"])); print("   ⚠️", "; ".join(v["cons"]) or "-")
        print("   💬", t["draft_message"].replace("\n", "\n      "))
    print("\n== skipped")
    for s in ranked["skipped"]:
        print(f"🚩 ¥{s['listing']['price_jpy'] or 0:,} {s['listing']['marketplace']}: {s['reason']}")
    print("\n== sell"); print(json.dumps(await brains.sell_advice("item", comps), ensure_ascii=False, indent=1))


asyncio.run(main())
